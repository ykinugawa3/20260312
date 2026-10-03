"""コマンドラインインターフェース.

使い方:
    numbers4 sample                  # 合成データを生成して DB に投入
    numbers4 import draws.csv        # 抽せん結果の CSV を取り込み
    numbers4 check                   # 乱数性チェック
    numbers4 stats --last 50         # 出目分析
    numbers4 lookup 1234             # 数字を調べる
"""

from __future__ import annotations

import argparse
import signal
import sys
import unicodedata
from pathlib import Path

import pandas as pd

from numbers4 import analysis, db, importer, sample_data


def _pad(text: object, width: int, right: bool = False) -> str:
    """全角文字を幅 2 として数え、表示幅 width に揃える."""
    text = str(text)
    w = sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in text)
    space = " " * max(width - w, 0)
    return space + text if right else text + space


def _load(args: argparse.Namespace) -> pd.DataFrame:
    draws = db.load_draws(args.db)
    if draws.empty:
        sys.exit(f"データがありません: {args.db} (numbers4 sample / numbers4 import で投入してください)")
    if getattr(args, "since", None):
        draws = draws[draws["date"] >= pd.Timestamp(args.since)]
    if getattr(args, "until", None):
        draws = draws[draws["date"] <= pd.Timestamp(args.until)]
    if draws.empty:
        sys.exit("指定した期間に抽せん結果がありません")
    return draws


def _period(draws: pd.DataFrame) -> str:
    first, last = draws.iloc[0], draws.iloc[-1]
    return (f"第{first['draw_no']}回 ({first['date']:%Y-%m-%d}) 〜 第{last['draw_no']}回 ({last['date']:%Y-%m-%d}), "
            f"{len(draws):,} 回")


def cmd_init_db(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    print(f"DB を初期化しました: {args.db}")


def cmd_sample(args: argparse.Namespace) -> None:
    draws = sample_data.generate(n_draws=args.draws, seed=args.seed)
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        draws.to_csv(args.csv, index=False)
        print(f"CSV を出力しました: {args.csv}")
    n = importer.import_frame(draws, args.db)
    print(f"合成データを投入しました: {n:,} 回 ({draws['date'].iloc[0]} 〜 {draws['date'].iloc[-1]})")


def cmd_import(args: argparse.Namespace) -> None:
    try:
        n = importer.import_csv(args.csv, args.db)
    except importer.ImportErrorWithDetail as e:
        sys.exit(f"取込エラー: {e}")
    print(f"取り込みました: {n:,} 回")


def cmd_check(args: argparse.Namespace) -> None:
    draws = _load(args)
    result = analysis.randomness_tests(draws)
    print(f"対象: {_period(draws)}\n")
    widths = [("検定", 16, False), ("内容", 22, False), ("回数", 8, True), ("カイ二乗", 10, True),
              ("自由度", 7, True), ("p値", 8, True), ("  判定", 12, False)]
    print("".join(_pad(h, w, r) for h, w, r in widths))
    for _, row in result.iterrows():
        chi2 = "" if pd.isna(row["統計量"]) else f"{row['統計量']:.1f}"
        p = "" if pd.isna(row["p値"]) else f"{row['p値']:.3f}"
        values = [row["検定"], row["内容"], f"{row['回数']:,}", chi2, row["自由度"], p, "  " + row["判定"]]
        print("".join(_pad(v, w, r) for v, (_, w, r) in zip(values, widths)))
    print(f"\n{analysis.summarize_tests(result)}")
    print(f"  ※ p値が小さいほど「偶然とは考えにくい偏り」。検定を {len(result)} 件行うため、"
          f"1 件あたりの基準を {analysis.ALPHA} ÷ {len(result)} に厳しくしている")
    print("  ※ 「前回との独立性」は回号が連続する組だけで計算する (欠けている回をまたがない)")


def _fmt_digits(items: list[tuple[int, int]]) -> str:
    return " ".join(f"{d}({c})" for d, c in items)


def cmd_stats(args: argparse.Namespace) -> None:
    draws = _load(args)
    recent = draws.tail(args.last)
    print(f"対象: {_period(draws)}")
    print(analysis.DISCLAIMER + "\n")

    print("■ 直近の当せん番号")
    for _, r in draws.tail(args.recent).iloc[::-1].iterrows():
        print(f"  第{r['draw_no']}回 {r['date']:%Y-%m-%d}  {r['number']}  ({analysis.pattern_of(r['number'])})")

    counts = analysis.position_counts(draws)
    recent_counts = analysis.position_counts(recent)
    gaps = analysis.current_gaps(draws)
    print(f"\n■ 桁別の出現回数  全期間 / 直近 {len(recent)} 回 / 出ていない回数 "
          f"(全期間の期待値 {len(draws) / 10:.1f} 回)")
    print("  " + _pad("数字", 6) + "".join(_pad(pos, 20, True) for pos in analysis.POSITIONS))
    for digit in range(10):
        cells = []
        for pos in analysis.POSITIONS:
            gap = gaps.loc[digit, pos]
            gap_s = "-" if pd.isna(gap) else f"{int(gap)}"
            cells.append(_pad(f"{counts.loc[digit, pos]} / {recent_counts.loc[digit, pos]} / {gap_s}", 20, True))
        print("  " + _pad(digit, 6) + "".join(cells))

    print(f"\n■ ホット / コールド (直近 {len(recent)} 回, 数字(回数))")
    for _, r in analysis.hot_cold(draws, last=args.last).iterrows():
        print("  " + _pad(r["桁"], 8) + _pad("ホット " + _fmt_digits(r["ホット"]), 26)
              + "コールド " + _fmt_digits(r["コールド"]))

    print("\n■ 型の分布")
    print("  " + _pad("型", 14) + _pad("例", 6) + _pad("ボックス", 10, True) + _pad("回数", 8, True)
          + _pad("割合", 9, True) + _pad("理論値", 9, True))
    for _, r in analysis.pattern_table(draws).iterrows():
        combos = "買えない" if r["型"] == "クアッド" else f"{r['ボックス通り数']}通り"
        print("  " + _pad(r["型"], 14) + _pad(r["例"], 6) + _pad(combos, 10, True) + _pad(r["回数"], 8, True)
              + _pad(f"{r['割合']:.2%}", 9, True) + _pad(f"{r['理論値']:.2%}", 9, True))

    rate, n = analysis.carry_rate(draws)
    if n:
        print(f"\n■ 引っ張り (前回と同じ位置に同じ数字が 1 つ以上): {rate:.1%} ({n:,} 回中), "
              f"理論値 {analysis.CARRY_PROB:.1%}")
    sums = analysis.digits(draws).sum(axis=1)
    print(f"■ 4 桁の合計: 平均 {sums.mean():.2f} (理論値 18.00), 最小 {sums.min()}, 最大 {sums.max()}")


def cmd_lookup(args: argparse.Namespace) -> None:
    draws = _load(args)
    try:
        r = analysis.lookup(draws, args.number)
    except ValueError as e:
        sys.exit(str(e))
    print(f"{r['number']}: {r['pattern']}")
    print(f"  ストレートの当選確率: 1/10,000 (毎回同じ)")
    if r["pattern"] == "クアッド":
        print("  ボックス: ゾロ目は買えません")
    else:
        print(f"  ボックスの当選確率: {r['box_combinations']}/10,000 ({r['box_combinations']} 通りの並べ替え)")

    print(f"\n対象: {_period(draws)}")
    hits = r["straight_hits"]
    print(f"  ストレートで当選: {len(hits)} 回 (期待値 {r['n_draws'] / 10_000:.2f} 回)")
    for _, h in hits.iterrows():
        payout = "" if pd.isna(h["straight_payout"]) else f"  当せん金 {h['straight_payout']:,.0f} 円"
        print(f"    第{h['draw_no']}回 {h['date']:%Y-%m-%d}{payout}")
    if r["draws_since_straight"] is not None:
        print(f"  最後のストレート当選から {r['draws_since_straight']} 回")
    if r["pattern"] != "クアッド":
        box = r["box_hits"]
        expected = r["n_draws"] * (r["box_combinations"] - 1) / 10_000
        print(f"  並べ替えで一致 (ストレート以外のボックス当選): {len(box)} 回 (期待値 {expected:.2f} 回)")
        for _, h in box.tail(args.max_rows).iterrows():
            payout = "" if pd.isna(h["box_payout"]) else f"  当せん金 {h['box_payout']:,.0f} 円"
            print(f"    第{h['draw_no']}回 {h['date']:%Y-%m-%d}  {h['number']}{payout}")
        if len(box) > args.max_rows:
            print(f"    (ほか {len(box) - args.max_rows} 回)")
    print("\n" + analysis.DISCLAIMER)


def _add_period_args(s: argparse.ArgumentParser) -> None:
    s.add_argument("--since", help="この日以降の回だけを使う (YYYY-MM-DD)")
    s.add_argument("--until", help="この日までの回だけを使う (YYYY-MM-DD)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="numbers4", description="ナンバーズ4 分析ソフト")
    p.add_argument("--db", type=Path, default=db.DEFAULT_DB_PATH, help="SQLite DB のパス")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-db", help="DB を初期化")
    s.set_defaults(func=cmd_init_db)

    s = sub.add_parser("sample", help="動作確認用の合成データを生成して投入")
    s.add_argument("--draws", type=int, default=2000, help="回数")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--csv", help="生成データを CSV でも出力するパス")
    s.set_defaults(func=cmd_sample)

    s = sub.add_parser("import", help="抽せん結果の CSV を取り込み")
    s.add_argument("csv")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("check", help="乱数性チェック (出目に偏りがないかを検定)")
    _add_period_args(s)
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("stats", help="出目分析 (ホット / コールド, 出現間隔など)")
    s.add_argument("--last", type=int, default=50, help="直近の集計に使う回数")
    s.add_argument("--recent", type=int, default=10, help="表示する直近の当せん番号の数")
    _add_period_args(s)
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("lookup", help="数字を調べる (過去の当選回など)")
    s.add_argument("number", help="4 桁の数字 (例: 0123)")
    s.add_argument("--max-rows", type=int, default=10, help="ボックス一致の表示件数")
    _add_period_args(s)
    s.set_defaults(func=cmd_lookup)
    return p


def main(argv: list[str] | None = None) -> None:
    if hasattr(signal, "SIGPIPE"):
        # `numbers4 stats | head` などで出力先が閉じられても例外を出さずに終える
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
