"""コマンドラインインターフェース.

使い方:
    keiba sample                     # 合成データを生成して DB に投入
    keiba import races.csv entries.csv
    keiba train --test-start 2026-01-01
    keiba evaluate --test-start 2026-01-01
    keiba predict --date 2026-09-26 --bankroll 100000
    keiba backtest --start 2026-01-01
"""

from __future__ import annotations

import argparse
import signal
import sys
import unicodedata
from pathlib import Path

import pandas as pd

from keiba import backtest, db, importer, model, sample_data
from keiba.features import build_features


def _pad(text: object, width: int, right: bool = False) -> str:
    """全角文字を幅 2 として数え、表示幅 width に揃える."""
    text = str(text)
    w = sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in text)
    space = " " * max(width - w, 0)
    return space + text if right else text + space


def _load_features(db_path: Path) -> pd.DataFrame:
    raw = db.load_joined(db_path)
    if raw.empty:
        sys.exit(f"データがありません: {db_path} (keiba sample / keiba import で投入してください)")
    return build_features(raw)


def cmd_init_db(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    print(f"DB を初期化しました: {args.db}")


def cmd_sample(args: argparse.Namespace) -> None:
    races, entries = sample_data.generate(n_days=args.days, seed=args.seed)
    if args.csv_dir:
        out = Path(args.csv_dir)
        out.mkdir(parents=True, exist_ok=True)
        races.to_csv(out / "races.csv", index=False)
        entries.to_csv(out / "entries.csv", index=False)
        print(f"CSV を出力しました: {out}/races.csv, {out}/entries.csv")
    n_r, n_e = importer.import_frames(races, entries, args.db)
    print(f"合成データを投入しました: {n_r} レース / {n_e} 頭 ({races['date'].min()} 〜 {races['date'].max()})")


def cmd_import(args: argparse.Namespace) -> None:
    try:
        n_r, n_e = importer.import_csv(args.races_csv, args.entries_csv, args.db)
    except importer.ImportErrorWithDetail as e:
        sys.exit(f"取込エラー: {e}")
    print(f"取り込みました: {n_r} レース / {n_e} 頭")


def cmd_train(args: argparse.Namespace) -> None:
    df = _load_features(args.db)
    if args.test_start:
        df, _ = model.split_by_date(df, args.test_start)
    m = model.train(df, use_market=not args.no_market)
    m.save(args.model)
    print(f"学習期間: {m.train_period[0]} 〜 {m.train_period[1]}")
    if m.calibrator:
        print(f"較正係数: モデル a={m.calibrator.a:.3f}, 市場 b={m.calibrator.b:.3f}")
    print(f"モデルを保存しました: {args.model}")
    print("\n特徴量重要度 (上位10):")
    for name, val in m.feature_importance().head(10).items():
        print(f"  {name:<34} {val:>10.0f}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    df = _load_features(args.db)
    train_df, test_df = model.split_by_date(df, args.test_start)
    if test_df["finished"].sum() == 0:
        sys.exit(f"{args.test_start} 以降に確定済みレースがありません")
    m = model.train(train_df, use_market=not args.no_market)
    r = model.evaluate(m, test_df)
    print(f"学習: {m.train_period[0]} 〜 {m.train_period[1]} / 検証: {args.test_start} 〜")
    print(f"検証レース数: {r['n_races']} ({r['n_entries']} 頭)")
    cal = r["calibrator"]
    print(f"較正係数: モデル a={cal.a:.3f}, 市場 b={cal.b:.3f}\n")
    rows = [
        ("指標", "モデル単体", "較正後", "市場(オッズ)"),
        ("LogLoss", f"{r['logloss_raw']:.4f}", f"{r['logloss_model']:.4f}", f"{r['logloss_market']:.4f}"),
        ("AUC", f"{r['auc_raw']:.4f}", f"{r['auc_model']:.4f}", f"{r['auc_market']:.4f}"),
        ("本命的中率", "", f"{r['top_pick_hit_rate']:.1%}", f"{r['favorite_hit_rate']:.1%}"),
        ("本命単勝回収率", "", f"{r['top_pick_roi']:.1%}", f"{r['favorite_roi']:.1%}"),
    ]
    for label, a, b, c in rows:
        print(_pad(label, 16) + _pad(a, 12, True) + _pad(b, 10, True) + _pad(c, 14, True))
    preds = test_df[test_df["finished"]].assign(win_prob=m.predict(test_df[test_df["finished"]]))
    strategy = backtest.Strategy(ev_threshold=args.ev_threshold, flat_stake=100)
    _, ev = backtest.simulate(preds, strategy)
    print(f"\n期待値 > {strategy.ev_threshold} (勝率 ≥ {strategy.min_prob:.0%}, オッズ ≤ {strategy.max_odds}) "
          f"の単勝を 100 円ずつ: {ev['n_bets']} 点, 回収率 {ev['roi']:.1%}")
    print("  ※ LogLoss は小さいほど良い。本命 = 較正後の予測1位 / 1番人気")


def _strategy_from_args(args: argparse.Namespace) -> backtest.Strategy:
    return backtest.Strategy(
        ev_threshold=args.ev_threshold,
        min_prob=args.min_prob,
        max_odds=args.max_odds,
        kelly_fraction=args.kelly,
        flat_stake=args.flat,
    )


def cmd_backtest(args: argparse.Namespace) -> None:
    if args.load_preds:
        preds = pd.read_csv(args.load_preds, parse_dates=["date"], dtype={"race_id": str})
    else:
        df = _load_features(args.db)

        def progress(i: int, n: int, when: pd.Timestamp) -> None:
            if i < n:
                print(f"  [{i + 1}/{n}] {when:%Y-%m} を予測中...", file=sys.stderr)

        start = args.start or model._date_at_fraction(df[df["finished"]], 0.7)
        preds = backtest.walk_forward_predictions(
            df, start, freq=args.freq, progress=progress, use_market=not args.no_market
        )
        if args.save_preds:
            preds.to_csv(args.save_preds, index=False)
            print(f"予測結果を保存しました: {args.save_preds} (--load-preds で再利用できます)")

    strategy = _strategy_from_args(args)
    bets, summary = backtest.simulate(preds, strategy, bankroll=args.bankroll)
    print(f"\n期間: {preds['date'].min():%Y-%m-%d} 〜 {preds['date'].max():%Y-%m-%d} "
          f"({preds['race_id'].nunique()} レース)")
    stake_desc = f"定額 {strategy.flat_stake} 円" if strategy.flat_stake else f"ケリー × {strategy.kelly_fraction}"
    print(f"買い方: 期待値 > {strategy.ev_threshold}, 勝率 ≥ {strategy.min_prob:.0%}, "
          f"オッズ ≤ {strategy.max_odds}, {stake_desc}\n")

    if summary["n_bets"] == 0:
        print("条件に合う買い目がありませんでした")
    else:
        items = [
            ("購入点数", f"{summary['n_bets']} 点 ({summary['n_races']} レース)"),
            ("的中率", f"{summary['hit_rate']:.1%}"),
            ("投資額", f"{summary['total_stake']:,.0f} 円"),
            ("払戻額", f"{summary['total_payout']:,.0f} 円"),
            ("回収率", f"{summary['roi']:.1%}"),
            ("収支", f"{summary['profit']:+,.0f} 円"),
            ("資金", f"{args.bankroll:,.0f} → {summary['final_bankroll']:,.0f} 円"),
            ("最大ドローダウン", f"{summary['max_drawdown']:.1%}"),
        ]
        for k, v in items:
            print(_pad(k, 18) + v)

        print("\n月別:")
        print("  " + _pad("月", 9) + _pad("点数", 6, True) + _pad("的中", 6, True)
              + _pad("収支", 12, True) + _pad("回収率", 9, True))
        for _, r in backtest.monthly_summary(bets).iterrows():
            print("  " + _pad(r["month"], 9) + _pad(int(r["n_bets"]), 6, True) + _pad(int(r["hits"]), 6, True)
                  + _pad(f"{r['profit']:+,.0f}", 12, True) + _pad(f"{r['roi']:.1%}", 9, True))

    print("\n比較 (毎レース 1 点定額買い):")
    for _, r in backtest.compare_baselines(preds).iterrows():
        print("  " + _pad(r["戦略"], 28) + _pad(f"的中率 {r['的中率']:.1%}", 14, True)
              + _pad(f"回収率 {r['回収率']:.1%}", 17, True))
    if args.output and summary["n_bets"]:
        bets.to_csv(args.output, index=False)
        print(f"\n買い目の明細を出力しました: {args.output}")


def cmd_predict(args: argparse.Namespace) -> None:
    m = model.WinModel.load(args.model)
    df = _load_features(args.db)
    if args.race_id:
        target = df[df["race_id"] == args.race_id]
    elif args.date:
        target = df[df["date"] == pd.Timestamp(args.date)]
    else:
        # 中止・除外馬がいる確定済みレースを除くため、全頭が未確定のレースだけを対象にする
        pending = df[~df.groupby("race_id")["finished"].transform("any")]
        if pending.empty:
            sys.exit("未確定のレースがありません。--date か --race-id を指定してください")
        target = pending[pending["date"] == pending["date"].min()]
    if target.empty:
        sys.exit("対象レースが見つかりません")

    result = model.predict_races(m, target)
    strategy = _strategy_from_args(args)
    result["stake"] = 0.0
    if args.bankroll:
        cands = backtest.select_candidates(result, strategy)
        for _, race in cands.groupby("race_id"):
            result.loc[race.index, "stake"] = backtest.stakes_for_race(race, args.bankroll, strategy)

    if args.output:
        cols = ["race_id", "date", "course", "race_number", "horse_number", "horse_name", "mark",
                "pred_rank", "win_prob", "model_prob", "market_prob", "odds", "expected_value", "stake",
                "finish_position"]
        result[cols].to_csv(args.output, index=False)
        print(f"予測結果を出力しました: {args.output}")
    cols_fmt = [("印", 3, False), ("馬番", 5, True), ("  馬名", 22, False), ("勝率", 7, True),
                ("(モデル)", 9, True), ("(市場)", 8, True), ("オッズ", 9, True), ("期待値", 8, True),
                ("推奨額", 9, True), ("着順", 6, True)]
    total = 0.0
    for race_id, race in result.groupby("race_id", sort=False):
        head = race.iloc[0]
        print(f"\n■ {head['date']:%Y-%m-%d} {head['course']} {head['race_number']}R "
              f"{head['surface']}{head['distance']}m {head['track_condition']} {head['race_class']} "
              f"({race_id}, {len(race)}頭)")
        print("  " + "".join(_pad(h, w, right) for h, w, right in cols_fmt))
        for _, r in race.iterrows():
            finish = "" if pd.isna(r["finish_position"]) else f"{int(r['finish_position'])}"
            stake = f"{r['stake']:,.0f}" if r["stake"] > 0 else ""
            values = [r["mark"], int(r["horse_number"]), "  " + r["horse_name"], f"{r['win_prob']:.1%}",
                      f"{r['model_prob']:.1%}", f"{r['market_prob']:.1%}", f"{r['odds']:.1f}",
                      f"{r['expected_value']:.2f}", stake, finish]
            print("  " + "".join(_pad(v, w, right) for v, (_, w, right) in zip(values, cols_fmt)))
        total += race["stake"].sum()
    print("\n勝率 = モデルと市場を合成した較正後の勝率 / 期待値 = 勝率 × オッズ")
    if args.bankroll:
        print(f"推奨額: 資金 {args.bankroll:,.0f} 円, 期待値 > {strategy.ev_threshold}, ケリー × {strategy.kelly_fraction}"
              f" / 合計 {total:,.0f} 円")
    print("※ オッズは締切直前まで変わるため、購入前に最新オッズで再計算してください")


def _add_strategy_args(s: argparse.ArgumentParser) -> None:
    d = backtest.Strategy()
    s.add_argument("--ev-threshold", type=float, default=d.ev_threshold, help="この期待値を超える馬を買う")
    s.add_argument("--min-prob", type=float, default=d.min_prob, help="勝率の下限")
    s.add_argument("--max-odds", type=float, default=d.max_odds, help="オッズの上限")
    s.add_argument("--kelly", type=float, default=d.kelly_fraction, help="ケリー基準の何割を賭けるか")
    s.add_argument("--flat", type=int, help="定額買いの金額 (指定するとケリーを使わない)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="keiba", description="競馬予想支援ソフト")
    p.add_argument("--db", type=Path, default=db.DEFAULT_DB_PATH, help="SQLite DB のパス")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-db", help="DB を初期化")
    s.set_defaults(func=cmd_init_db)

    s = sub.add_parser("sample", help="動作確認用の合成データを生成して投入")
    s.add_argument("--days", type=int, default=200, help="開催日数 (最終日は結果未確定)")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--csv-dir", help="生成データを CSV でも出力するディレクトリ")
    s.set_defaults(func=cmd_sample)

    s = sub.add_parser("import", help="races.csv / entries.csv を取り込み")
    s.add_argument("races_csv")
    s.add_argument("entries_csv")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("train", help="モデルを学習して保存")
    s.add_argument("--model", type=Path, default=model.DEFAULT_MODEL_PATH)
    s.add_argument("--test-start", help="この日付より前のデータだけで学習する")
    s.add_argument("--no-market", action="store_true", help="較正にオッズを使わない")
    s.set_defaults(func=cmd_train)

    s = sub.add_parser("evaluate", help="時系列分割でモデルを検証")
    s.add_argument("--test-start", required=True, help="検証期間の開始日 (YYYY-MM-DD)")
    s.add_argument("--ev-threshold", type=float, default=1.2)
    s.add_argument("--no-market", action="store_true", help="較正にオッズを使わない")
    s.set_defaults(func=cmd_evaluate)

    s = sub.add_parser("backtest", help="ウォークフォワードで予測し、買い方をシミュレーション")
    s.add_argument("--start", default=None, help="検証開始日 (YYYY-MM-DD, 既定: データ期間の 70%% 地点)")
    s.add_argument("--freq", default="MS", help="再学習の間隔 (pandas の頻度文字列, 既定: 毎月)")
    s.add_argument("--bankroll", type=float, default=100_000, help="初期資金 (円)")
    s.add_argument("--save-preds", help="予測結果を CSV 保存 (買い方だけ変えて再試行するときに使う)")
    s.add_argument("--load-preds", help="保存した予測結果を読み込む (再学習しない)")
    s.add_argument("--output", help="買い目の明細を CSV 出力")
    s.add_argument("--no-market", action="store_true", help="較正にオッズを使わない")
    _add_strategy_args(s)
    s.set_defaults(func=cmd_backtest)

    s = sub.add_parser("predict", help="レースの勝率を予測して表示")
    s.add_argument("--model", type=Path, default=model.DEFAULT_MODEL_PATH)
    s.add_argument("--date", help="対象日 (YYYY-MM-DD)")
    s.add_argument("--race-id", help="対象レース ID")
    s.add_argument("--output", help="結果を CSV 出力するパス")
    s.add_argument("--bankroll", type=float, help="資金 (円). 指定すると推奨購入額を表示")
    _add_strategy_args(s)
    s.set_defaults(func=cmd_predict)
    return p


def main(argv: list[str] | None = None) -> None:
    if hasattr(signal, "SIGPIPE"):
        # `keiba predict | head` などで出力先が閉じられても例外を出さずに終える
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
