"""競馬予想支援ソフト Web UI.

起動:  streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.metrics import log_loss, roc_auc_score

from keiba import backtest, db, importer, model, sample_data
from keiba.calibration import reliability_table
from keiba.features import build_features

# 参照パレット (dataviz スキルで検証済み). 系列は固定順で割り当てる
SERIES = {"較正後": "#2a78d6", "市場(オッズ)": "#eb6834", "モデル単体": "#1baf7a"}
POSITIVE, NEGATIVE = "#2a78d6", "#e34948"
MUTED = "#8a8984"

st.set_page_config(page_title="競馬予想支援", page_icon="🏇", layout="wide")


# ---------------------------------------------------------------- データ読み込み

def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


@st.cache_data(show_spinner="特徴量を計算中...")
def load_features(db_path: str, _mtime: float) -> pd.DataFrame:
    raw = db.load_joined(db_path)
    return build_features(raw) if not raw.empty else raw


@st.cache_resource(show_spinner=False)
def load_model(model_path: str, _mtime: float) -> model.WinModel | None:
    return model.WinModel.load(model_path) if Path(model_path).exists() else None


@st.cache_data(show_spinner=False)
def walk_forward(db_path: str, _mtime: float, start: str, freq: str) -> pd.DataFrame:
    df = load_features(db_path, _mtime)
    bar = st.progress(0.0, text="ウォークフォワード予測中...")

    def progress(i: int, n: int, when: pd.Timestamp) -> None:
        bar.progress(min(i / max(n, 1), 1.0), text=f"ウォークフォワード予測中... {when:%Y-%m} ({i}/{n})")

    preds = backtest.walk_forward_predictions(df, start, freq=freq, progress=progress)
    bar.empty()
    return preds


# ---------------------------------------------------------------- サイドバー

with st.sidebar:
    st.header("🏇 競馬予想支援")
    db_path = Path(st.text_input("DB ファイル", str(db.DEFAULT_DB_PATH)))
    model_path = Path(st.text_input("モデルファイル", str(model.DEFAULT_MODEL_PATH)))

    with st.expander("データ投入", expanded=not db_path.exists()):
        days = st.number_input("合成データの開催日数", 60, 400, 200, step=20)
        if st.button("合成データを生成", width="stretch"):
            with st.spinner("生成中..."):
                races, entries = sample_data.generate(n_days=int(days))
                importer.import_frames(races, entries, db_path)
            st.cache_data.clear()
            st.success(f"{len(races)} レースを投入しました")
        races_up = st.file_uploader("races.csv", type="csv")
        entries_up = st.file_uploader("entries.csv", type="csv")
        if races_up and entries_up and st.button("CSV を取り込む", width="stretch"):
            try:
                r = pd.read_csv(races_up, dtype={"race_id": str})
                e = pd.read_csv(entries_up, dtype={"race_id": str, "horse_id": str,
                                                   "jockey_id": str, "trainer_id": str})
                n_r, n_e = importer.import_frames(r, e, db_path)
                st.cache_data.clear()
                st.success(f"{n_r} レース / {n_e} 頭を取り込みました")
            except importer.ImportErrorWithDetail as ex:
                st.error(str(ex))

if not db_path.exists():
    st.info("左の「データ投入」から合成データを生成するか、CSV を取り込んでください。")
    st.stop()

features = load_features(str(db_path), _mtime(db_path))
if features.empty:
    st.info("DB にデータがありません。")
    st.stop()

with st.sidebar:
    finished = features[features["finished"]]
    st.caption(f"データ: {features['race_id'].nunique():,} レース "
               f"({features['date'].min():%Y-%m-%d} 〜 {features['date'].max():%Y-%m-%d})")
    if st.button("全期間で学習してモデルを保存", width="stretch"):
        with st.spinner("学習中..."):
            model.train(features).save(model_path)
        st.cache_resource.clear()
        st.success("モデルを保存しました")

win_model = load_model(str(model_path), _mtime(model_path))

tab_pred, tab_bt, tab_eval = st.tabs(["レース予想", "バックテスト", "モデル評価"])


# ---------------------------------------------------------------- レース予想

with tab_pred:
    if win_model is None:
        st.info("モデルがありません。サイドバーの「全期間で学習してモデルを保存」を押してください。")
    else:
        pending_mask = ~features.groupby("race_id")["finished"].transform("any")
        dates = sorted(features["date"].dt.date.unique(), reverse=True)
        default_date = features.loc[pending_mask, "date"].min() if pending_mask.any() else features["date"].max()
        c1, c2, c3 = st.columns([1, 1, 1])
        date = c1.selectbox("開催日", dates, index=dates.index(default_date.date()))
        bankroll = c2.number_input("資金 (円)", 10_000, 10_000_000, 100_000, step=10_000)
        ev_th = c3.slider("期待値のしきい値", 1.0, 1.5, backtest.Strategy().ev_threshold, 0.05, key="pred_ev")

        day = features[features["date"].dt.date == date]
        result = model.predict_races(win_model, day)
        strategy = backtest.Strategy(ev_threshold=ev_th)
        result["stake"] = 0.0
        cands = backtest.select_candidates(result, strategy)
        for _, race in cands.groupby("race_id"):
            result.loc[race.index, "stake"] = backtest.stakes_for_race(race, bankroll, strategy)

        # レース一覧: 妙味 (最大期待値) と推奨額
        summary = result.groupby("race_id", sort=False).agg(
            場=("course", "first"), R=("race_number", "first"), 条件=("surface", "first"),
            距離=("distance", "first"), 馬場=("track_condition", "first"), クラス=("race_class", "first"),
            頭数=("horse_number", "size"), 最大期待値=("expected_value", "max"), 推奨額=("stake", "sum"),
        ).reset_index().sort_values(["場", "R"])
        m1, m2, m3 = st.columns(3)
        m1.metric("レース数", len(summary))
        m2.metric("買い推奨レース", int((summary["推奨額"] > 0).sum()))
        m3.metric("推奨額合計", f"{summary['推奨額'].sum():,.0f} 円")

        st.dataframe(
            summary.drop(columns="race_id"), hide_index=True, width="stretch",
            column_config={
                "最大期待値": st.column_config.NumberColumn(format="%.2f"),
                "推奨額": st.column_config.NumberColumn(format="%d 円"),
            },
        )

        labels = {rid: f"{r['場']} {r['R']}R {r['条件']}{r['距離']}m {r['クラス']}"
                  for rid, r in summary.set_index("race_id").iterrows()}
        race_id = st.selectbox("レース詳細", list(labels), format_func=labels.get)
        race = result[result["race_id"] == race_id].sort_values("pred_rank")
        view = race[["mark", "horse_number", "horse_name", "win_prob", "model_prob", "market_prob",
                     "odds", "expected_value", "stake", "finish_position"]].rename(columns={
            "mark": "印", "horse_number": "馬番", "horse_name": "馬名", "win_prob": "勝率",
            "model_prob": "モデル単体", "market_prob": "市場", "odds": "オッズ",
            "expected_value": "期待値", "stake": "推奨額", "finish_position": "着順",
        })
        for col in ("勝率", "モデル単体", "市場"):
            view[col] = view[col] * 100
        # 空欄を "None" と表示させないよう文字列にする
        view["推奨額"] = view["推奨額"].map(lambda v: f"{v:,.0f} 円" if v > 0 else "")
        view["着順"] = view["着順"].map(lambda v: "" if pd.isna(v) else str(int(v)))
        st.dataframe(
            view, hide_index=True, width="stretch",
            column_config={
                "勝率": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "モデル単体": st.column_config.NumberColumn(format="%.1f%%"),
                "市場": st.column_config.NumberColumn(format="%.1f%%"),
                "オッズ": st.column_config.NumberColumn(format="%.1f"),
                "期待値": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.caption("勝率 = モデルと市場を合成した較正後の勝率 / 期待値 = 勝率 × オッズ。"
                   "オッズは締切直前まで変わるため、購入前に最新オッズで再計算してください。")


# ---------------------------------------------------------------- バックテスト

def _backtest_inputs() -> tuple[str, str] | None:
    fin_dates = finished["date"].drop_duplicates().sort_values()
    if len(fin_dates) < 30:
        st.info("確定済みの開催日が少なすぎます (30 日以上必要)。")
        return None
    default_start = fin_dates.iloc[int(len(fin_dates) * 0.7)].date()
    c1, c2 = st.columns(2)
    start = c1.date_input("検証開始日", default_start, min_value=fin_dates.iloc[10].date(),
                          max_value=fin_dates.iloc[-1].date(), key="bt_start")
    freq = c2.selectbox("再学習の間隔", ["MS", "QS"], format_func={"MS": "毎月", "QS": "四半期"}.get)
    return str(start), freq


with tab_bt:
    st.caption("検証期間を区切り、各区間より前のデータだけで学習 → 区間内を予測 (ウォークフォワード)。"
               "買い方の条件を変えても再学習は不要です。")
    inputs = _backtest_inputs()
    if inputs:
        preds = walk_forward(str(db_path), _mtime(db_path), *inputs)
        d = backtest.Strategy()
        c1, c2, c3, c4, c5 = st.columns(5)
        strategy = backtest.Strategy(
            ev_threshold=c1.slider("期待値 >", 1.0, 1.6, d.ev_threshold, 0.05),
            min_prob=c2.slider("勝率 ≥", 0.0, 0.2, d.min_prob, 0.01),
            max_odds=c3.slider("オッズ ≤", 5.0, 200.0, d.max_odds, 5.0),
            kelly_fraction=c4.slider("ケリー倍率", 0.02, 0.5, d.kelly_fraction, 0.02),
            flat_stake=100 if c5.radio("賭け方", ["ケリー", "定額100円"], horizontal=True) == "定額100円" else None,
        )
        initial = 100_000
        bets, s = backtest.simulate(preds, strategy, bankroll=initial)

        k = st.columns(5)
        k[0].metric("回収率", f"{s['roi']:.1%}" if s["n_bets"] else "-")
        k[1].metric("収支", f"{s['profit'] / 10_000:+,.1f} 万円")
        k[2].metric("購入点数", f"{s['n_bets']} 点")
        k[3].metric("的中率", f"{s['hit_rate']:.1%}" if s["n_bets"] else "-")
        k[4].metric("最大ドローダウン", f"{s['max_drawdown']:.1%}")

        if s["n_bets"]:
            curve = backtest.bankroll_curve(bets, initial)
            curve = pd.concat([pd.DataFrame({"date": [preds["date"].min()], "race_id": ["start"],
                                             "bankroll": [initial]}), curve])
            curve["n"] = range(len(curve))
            base = alt.Chart(curve).encode(
                x=alt.X("n:Q", title="購入したレース (時系列順)", axis=alt.Axis(grid=False),
                      scale=alt.Scale(domain=[0, len(curve) - 1], nice=False)),
            )
            line = base.mark_line(color=POSITIVE, strokeWidth=2).encode(
                y=alt.Y("bankroll:Q", title="資金 (円)", scale=alt.Scale(zero=False)),
            )
            hover = alt.selection_point(fields=["n"], nearest=True, on="pointerover", empty=False)
            points = base.mark_point(size=80, filled=True, color=POSITIVE).encode(
                y="bankroll:Q",
                opacity=alt.condition(hover, alt.value(1), alt.value(0)),
                tooltip=[alt.Tooltip("date:T", title="日付", format="%Y-%m-%d"),
                         alt.Tooltip("race_id:N", title="レース"),
                         alt.Tooltip("bankroll:Q", title="資金", format=",.0f")],
            ).add_params(hover)
            rule = alt.Chart(pd.DataFrame({"y": [initial]})).mark_rule(
                color=MUTED, strokeDash=[4, 4]).encode(y="y:Q")
            st.subheader("資金推移")
            st.altair_chart((rule + line + points).properties(height=320), width="stretch")

            monthly = backtest.monthly_summary(bets)
            monthly["符号"] = np.where(monthly["profit"] >= 0, "プラス", "マイナス")
            bars = alt.Chart(monthly).mark_bar(cornerRadiusEnd=4, size=24).encode(
                x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("profit:Q", title="収支 (円)"),
                color=alt.Color("符号:N", scale=alt.Scale(domain=["プラス", "マイナス"],
                                                          range=[POSITIVE, NEGATIVE]),
                                legend=alt.Legend(title=None, orient="top")),
                tooltip=[alt.Tooltip("month:N", title="月"), alt.Tooltip("n_bets:Q", title="点数"),
                         alt.Tooltip("hits:Q", title="的中"),
                         alt.Tooltip("profit:Q", title="収支", format="+,.0f"),
                         alt.Tooltip("roi:Q", title="回収率", format=".1%")],
            )
            zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=MUTED).encode(y="y:Q")
            st.subheader("月別収支")
            st.altair_chart((zero + bars).properties(height=260), width="stretch")

            with st.expander("月別の表 / 買い目の明細"):
                st.dataframe(monthly.drop(columns="符号"), hide_index=True, width="stretch")
                st.dataframe(bets[["date", "course", "race_number", "horse_number", "horse_name", "win_prob",
                                   "odds", "expected_value", "stake", "payout", "finish_position",
                                   "bankroll_after"]], hide_index=True, width="stretch")

        st.subheader("単純な買い方との比較 (毎レース 1 点・定額)")
        st.dataframe(backtest.compare_baselines(preds), hide_index=True, width="stretch",
                     column_config={"的中率": st.column_config.NumberColumn(format="%.3f"),
                                    "回収率": st.column_config.NumberColumn(format="%.3f")})


# ---------------------------------------------------------------- モデル評価

with tab_eval:
    st.caption("バックテストと同じウォークフォワード予測で、確率の精度と較正を確認します。")
    # タブは上から順に描画されるので、バックテストタブで選んだ期間をそのまま使う
    if inputs:
        preds = walk_forward(str(db_path), _mtime(db_path), *inputs)
        cols = {"較正後": "win_prob", "市場(オッズ)": "market_prob", "モデル単体": "model_prob"}
        y = preds["is_win"]
        metrics = pd.DataFrame([
            {"確率": name, "LogLoss (小さいほど良い)": log_loss(y, preds[c].clip(1e-6, 1 - 1e-6)),
             "AUC": roc_auc_score(y, preds[c])}
            for name, c in cols.items()
        ])
        st.dataframe(metrics, hide_index=True, width="stretch",
                     column_config={"LogLoss (小さいほど良い)": st.column_config.NumberColumn(format="%.4f"),
                                    "AUC": st.column_config.NumberColumn(format="%.4f")})

        rel = pd.concat([reliability_table(preds[c], y, bins=10).assign(確率=name) for name, c in cols.items()])
        # 勝率は 0〜10% に集中するので平方根目盛りで広げる
        sqrt = alt.Scale(type="sqrt", domain=[0, float(rel[["pred", "actual"]].max().max()) * 1.05], nice=False)
        diag = alt.Chart(pd.DataFrame({"x": [0, rel[["pred", "actual"]].max().max()]})).mark_line(
            color=MUTED, strokeDash=[4, 4]).encode(x=alt.X("x:Q", scale=sqrt), y=alt.Y("x:Q", scale=sqrt))
        color = alt.Color("確率:N", scale=alt.Scale(domain=list(SERIES), range=list(SERIES.values())),
                          legend=alt.Legend(title=None, orient="top"))
        lines = alt.Chart(rel).mark_line(strokeWidth=2).encode(
            x=alt.X("pred:Q", title="予測した勝率 (区間平均)", axis=alt.Axis(format="%"), scale=sqrt),
            y=alt.Y("actual:Q", title="実際の勝率", axis=alt.Axis(format="%"), scale=sqrt),
            color=color,
        )
        dots = alt.Chart(rel).mark_point(size=70, filled=True, stroke="white", strokeWidth=2).encode(
            x="pred:Q", y="actual:Q", color=color,
            tooltip=[alt.Tooltip("確率:N"), alt.Tooltip("pred:Q", title="予測", format=".1%"),
                     alt.Tooltip("actual:Q", title="実際", format=".1%"), alt.Tooltip("n:Q", title="頭数")],
        )
        st.subheader("較正曲線")
        st.caption("点線に近いほど「予測勝率 = 実際の勝率」。期待値の計算はこの一致が前提です。")
        st.altair_chart((diag + lines + dots).properties(height=380), width="stretch")

        if win_model is not None:
            st.subheader("特徴量重要度 (保存済みモデル)")
            imp = win_model.feature_importance().head(15).rename("重要度").reset_index().rename(
                columns={"index": "特徴量"})
            bar = alt.Chart(imp).mark_bar(color=POSITIVE, cornerRadiusEnd=4, size=14).encode(
                x=alt.X("重要度:Q", title="重要度 (gain)"),
                y=alt.Y("特徴量:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
                tooltip=["特徴量", alt.Tooltip("重要度:Q", format=",.0f")],
            )
            st.altair_chart(bar.properties(height=380), width="stretch")
            if win_model.calibrator:
                st.caption(f"較正係数: モデル a={win_model.calibrator.a:.3f}, 市場 b={win_model.calibrator.b:.3f}")
