"""コマンドライン.

kabu sample     仮データを DB に投入
kabu import     CSV を取り込む
kabu fetch      yfinance から取得して取り込む
kabu check      DB のデータをチェック
kabu evaluate   指定日より前で学習し、以降でベースラインと比較
kabu train      全期間で学習してモデルを保存
kabu predict    最新日 (または指定日) の銘柄ランキングを表示
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

from kabu import db, evaluate, importer, model, sample_data
from kabu.features import DEFAULT_HORIZON, build_features

PCT_COLUMNS = ["IC>0 の割合", "上位-下位20%", "年率リターン", "SPY 年率", "超過 (年率)", "最大DD", "回転率"]


def _load_features(db_path: Path, horizon: int) -> pd.DataFrame:
    prices = db.load_prices(db_path)
    if prices.empty:
        raise SystemExit(f"{db_path} に株価がありません。先に kabu sample / import / fetch を実行してください")
    membership = db.load_membership(db_path)
    if membership.empty:
        print("注意: 指数の構成銘柄履歴が無いため、DB の全銘柄を対象にします")
    return build_features(prices, db.load_actions(db_path), membership, horizon=horizon)


def _format_table(table: pd.DataFrame) -> str:
    out = table.copy().astype(object)
    for col in out.columns:
        if col in PCT_COLUMNS:
            out[col] = table[col].map(lambda v: f"{v:+.1%}" if col != "IC>0 の割合" and col != "回転率" else f"{v:.0%}")
        elif col == "IC 平均":
            out[col] = table[col].map(lambda v: f"{v:+.4f}")
        else:
            out[col] = table[col].map(lambda v: f"{v:.2f}")
    return out.T.to_string()


def cmd_sample(args) -> None:
    frames = sample_data.generate(n_stocks=args.stocks, n_days=args.days, index_size=args.index_size, seed=args.seed)
    if args.csv_dir:
        for p in importer.export_csv(frames, args.csv_dir):
            print(f"書き出し: {p}")
    report = importer.import_frames(
        frames["securities"], frames["prices"], args.db, frames["actions"], frames["membership"]
    )
    print(report.summary())
    print(f"仮データを {args.db} に投入しました ({frames['prices']['date'].min()} 〜 {frames['prices']['date'].max()})")


def cmd_import(args) -> None:
    report = importer.import_csv(
        args.prices, args.db, args.securities, args.actions, args.membership, args.index_name
    )
    print(report.summary())


def cmd_fetch(args) -> None:
    from kabu import sources

    securities = membership = None
    tickers = list(args.tickers or [])
    if args.universe == "sp500":
        securities, membership = sources.fetch_sp500_list()
        tickers += securities["ticker"].tolist()
        print(f"S&P 500 の現在の構成銘柄 {len(securities)} 件を取得しました")
        print("注意: 上場廃止・除外された銘柄は含まれないため、過去の検証成績は実際より良く見えます (生存者バイアス)")
    if not tickers:
        raise SystemExit("--tickers か --universe sp500 を指定してください")
    prices, actions, failed = sources.fetch_yfinance(tickers, args.start, args.end)
    if failed:
        print(f"取得できなかった銘柄 ({len(failed)} 件): {' '.join(failed[:30])}{' ...' if len(failed) > 30 else ''}")
    if prices.empty:
        raise SystemExit("株価を 1 件も取得できませんでした (ネットワークや yfinance の状態を確認してください)")
    sessions = importer.nyse_sessions(prices["date"].min(), prices["date"].max())
    report = importer.import_frames(securities, prices, args.db, actions, membership, sessions=sessions)
    print(report.summary())


def cmd_check(args) -> None:
    prices = db.load_prices(args.db)
    if prices.empty:
        raise SystemExit("株価がありません")
    actions = db.load_actions(args.db).merge(prices.drop_duplicates("security_id")[["security_id", "ticker"]])
    sessions = importer.nyse_sessions(prices["date"].min(), prices["date"].max()) if args.calendar else None
    warnings = importer.validate_prices(prices, actions, sessions)
    print(f"{prices['ticker'].nunique()} 銘柄 / {len(prices)} 行 / {prices['date'].min():%Y-%m-%d} 〜 {prices['date'].max():%Y-%m-%d}")
    print("\n".join(f"  警告: {w}" for w in warnings) if warnings else "  問題は見つかりませんでした")


def cmd_evaluate(args) -> None:
    df = _load_features(args.db, args.horizon)
    test_start = pd.Timestamp(args.test_start)
    dates = pd.Series(sorted(df["date"].unique()))
    before = dates[dates < test_start]
    if len(before) <= args.horizon + 1:
        raise SystemExit("--test-start より前の学習データが足りません")
    # 学習データの目的変数が検証期間に食い込まないよう、境界の手前 horizon+1 日を外す
    train_end = before.iloc[-(args.horizon + 1)]
    train_df = df[df["date"] < train_end]
    test_df = df[df["date"] >= test_start].dropna(subset=["target"])
    if test_df.empty:
        raise SystemExit("検証期間に結果が確定したデータがありません")
    m = model.train(train_df, horizon=args.horizon, objective=args.objective, rounds=args.rounds)
    scores = {f"LightGBM ({args.objective})": m.predict(test_df), **evaluate.baseline_scores(test_df)}
    table = evaluate.evaluate_scores(test_df, scores, args.horizon, args.top_n, args.cost_bps)
    print(f"学習: {m.train_period[0]} 〜 {m.train_period[1]} / 検証: {test_df['date'].min():%Y-%m-%d} 〜 {test_df['date'].max():%Y-%m-%d}")
    print(f"予測期間 {args.horizon} 営業日 / 上位 {args.top_n} 銘柄を等金額 / 片道コスト {args.cost_bps:g}bp\n")
    print(_format_table(table))
    print("\n特徴量の重要度 (上位 10):")
    imp = m.feature_importance()
    print((imp / imp.sum()).head(10).map(lambda v: f"{v:.1%}").to_string())


def cmd_train(args) -> None:
    df = _load_features(args.db, args.horizon)
    m = model.train(df, horizon=args.horizon, objective=args.objective, rounds=args.rounds)
    m.save(args.model)
    print(f"学習期間 {m.train_period[0]} 〜 {m.train_period[1]} のモデルを {args.model} に保存しました")


def cmd_predict(args) -> None:
    if not Path(args.model).exists():
        raise SystemExit(f"{args.model} がありません。先に kabu train を実行してください")
    m = model.RankModel.load(args.model)
    df = _load_features(args.db, m.horizon)
    date = pd.Timestamp(args.date) if args.date else df["date"].max()
    day = df[df["date"] == date].copy()
    if day.empty:
        raise SystemExit(f"{date:%Y-%m-%d} の対象銘柄がありません")
    day["score"] = m.predict(day)
    day["順位"] = day["score"].rank(ascending=False, method="first").astype(int)
    day = day.sort_values("順位")
    out = pd.DataFrame({
        "順位": day["順位"],
        "ticker": day["ticker"],
        "sector": day["sector"],
        "終値": day["close"].round(2),
        "上位%": (100 * day["順位"] / len(day)).map(lambda v: f"{math.ceil(v)}%"),
        "12-1ヶ月": day["mom_12_1"].map(lambda v: f"{v:+.0%}"),
        "5日": day["ret_5"].map(lambda v: f"{v:+.1%}"),
        "ボラ(年率)": (day["vol_60"] * 252 ** 0.5).map(lambda v: f"{v:.0%}"),
    })
    print(f"{date:%Y-%m-%d} 引け時点の予測 (今後 {m.horizon} 営業日の対 SPY 超過リターンの順位) / 対象 {len(day)} 銘柄")
    print("※ 順位は相対的な強さの予想であり、値上がりを保証するものではありません\n")
    print(out.head(args.top_n).to_string(index=False))
    if args.output:
        out.to_csv(args.output, index=False)
        print(f"\n全銘柄の順位を {args.output} に保存しました")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kabu", description="米国株の相対順位予測ソフト")
    p.add_argument("--db", type=Path, default=db.DEFAULT_DB_PATH, help="SQLite ファイル (既定: data/kabu.db)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sample", help="仮データを DB に投入")
    s.add_argument("--stocks", type=int, default=300)
    s.add_argument("--days", type=int, default=2000)
    s.add_argument("--index-size", type=int, default=200)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--csv-dir", type=Path, help="見本の CSV も書き出す")
    s.set_defaults(func=cmd_sample)

    s = sub.add_parser("import", help="CSV を取り込む")
    s.add_argument("prices", type=Path, help="ticker,date,open,high,low,close,volume[,split_ratio,dividend]")
    s.add_argument("--securities", type=Path, help="ticker,name,sector,listed_date,delisted_date")
    s.add_argument("--actions", type=Path, help="ticker,date,split_ratio,dividend")
    s.add_argument("--membership", type=Path, help="ticker,start_date,end_date (指数の構成銘柄履歴)")
    s.add_argument("--index-name", default="SP500")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("fetch", help="yfinance から取得して取り込む (開発用)")
    s.add_argument("--tickers", nargs="+", help="例: AAPL MSFT NVDA (SPY は自動で追加)")
    s.add_argument("--universe", choices=["sp500"], help="Wikipedia の S&P 500 構成銘柄一覧を使う")
    s.add_argument("--start", default="2010-01-01")
    s.add_argument("--end")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("check", help="DB のデータをチェック")
    s.add_argument("--calendar", action="store_true", help="NYSE の取引日と照合して欠損日も調べる")
    s.set_defaults(func=cmd_check)

    for name, func, help_ in [
        ("evaluate", cmd_evaluate, "指定日より前で学習し、以降でベースラインと比較"),
        ("train", cmd_train, "全期間で学習してモデルを保存"),
    ]:
        s = sub.add_parser(name, help=help_)
        s.add_argument("--horizon", type=int, default=DEFAULT_HORIZON, help="予測期間 (営業日)")
        s.add_argument("--objective", choices=model.OBJECTIVES, default="rank_regression")
        s.add_argument("--rounds", type=int, default=model.DEFAULT_ROUNDS, help="LightGBM の学習回数")
        if name == "evaluate":
            s.add_argument("--test-start", required=True)
            s.add_argument("--top-n", type=int, default=20)
            s.add_argument("--cost-bps", type=float, default=10.0, help="片道の売買コスト (bp)")
        else:
            s.add_argument("--model", type=Path, default=model.DEFAULT_MODEL_PATH)
        s.set_defaults(func=func)

    s = sub.add_parser("predict", help="銘柄ランキングを表示")
    s.add_argument("--model", type=Path, default=model.DEFAULT_MODEL_PATH)
    s.add_argument("--date", help="既定: データの最新日")
    s.add_argument("--top-n", type=int, default=20)
    s.add_argument("--output", type=Path, help="全銘柄の順位を CSV に保存")
    s.set_defaults(func=cmd_predict)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0
