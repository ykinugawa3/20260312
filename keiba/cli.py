"""コマンドラインインターフェース.

使い方:
    keiba sample                     # 合成データを生成して DB に投入
    keiba import races.csv entries.csv
    keiba train --test-start 2026-01-01
    keiba evaluate --test-start 2026-01-01
    keiba predict --date 2026-09-26
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

import pandas as pd

from keiba import db, importer, model, sample_data
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
    m = model.train(df)
    m.save(args.model)
    print(f"学習期間: {m.train_period[0]} 〜 {m.train_period[1]}")
    print(f"モデルを保存しました: {args.model}")
    print("\n特徴量重要度 (上位10):")
    for name, val in m.feature_importance().head(10).items():
        print(f"  {name:<34} {val:>10.0f}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    df = _load_features(args.db)
    train_df, test_df = model.split_by_date(df, args.test_start)
    if test_df["finished"].sum() == 0:
        sys.exit(f"{args.test_start} 以降に確定済みレースがありません")
    m = model.train(train_df)
    r = model.evaluate(m, test_df)
    print(f"学習: {m.train_period[0]} 〜 {m.train_period[1]} / 検証: {args.test_start} 〜")
    print(f"検証レース数: {r['n_races']} ({r['n_entries']} 頭)\n")
    rows = [
        ("指標", "モデル", "市場(オッズ)"),
        ("LogLoss", f"{r['logloss_model']:.4f}", f"{r['logloss_market']:.4f}"),
        ("AUC", f"{r['auc_model']:.4f}", f"{r['auc_market']:.4f}"),
        ("本命的中率", f"{r['top_pick_hit_rate']:.1%}", f"{r['favorite_hit_rate']:.1%}"),
        ("本命単勝回収率", f"{r['top_pick_roi']:.1%}", f"{r['favorite_roi']:.1%}"),
    ]
    for label, a, b in rows:
        print(_pad(label, 16) + _pad(a, 10, True) + _pad(b, 14, True))
    print(f"\n期待値 > 1.2 の単勝: {r['ev_over_1.2_bets']} 点, 回収率 {r['ev_over_1.2_roi']:.1%}")
    print("  ※ 本命 = モデル予測1位 (モデル列) / 1番人気 (市場列)")


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
    if args.output:
        cols = ["race_id", "date", "course", "race_number", "horse_number", "horse_name", "mark",
                "pred_rank", "win_prob", "odds", "expected_value", "finish_position"]
        result[cols].to_csv(args.output, index=False)
        print(f"予測結果を出力しました: {args.output}")
    cols_fmt = [("印", 3, False), ("馬番", 5, True), ("  馬名", 22, False), ("勝率", 7, True),
                ("オッズ", 9, True), ("期待値", 8, True), ("着順", 6, True)]
    for race_id, race in result.groupby("race_id", sort=False):
        head = race.iloc[0]
        print(f"\n■ {head['date']:%Y-%m-%d} {head['course']} {head['race_number']}R "
              f"{head['surface']}{head['distance']}m {head['track_condition']} {head['race_class']} "
              f"({race_id}, {len(race)}頭)")
        print("  " + "".join(_pad(h, w, right) for h, w, right in cols_fmt))
        for _, r in race.iterrows():
            finish = "" if pd.isna(r["finish_position"]) else f"{int(r['finish_position'])}"
            ev_flag = " *" if r["expected_value"] > args.ev_threshold else ""
            values = [r["mark"], int(r["horse_number"]), "  " + r["horse_name"], f"{r['win_prob']:.1%}",
                      f"{r['odds']:.1f}", f"{r['expected_value']:.2f}", finish]
            print("  " + "".join(_pad(v, w, right) for v, (_, w, right) in zip(values, cols_fmt)) + ev_flag)
    print(f"\n* = 期待値 {args.ev_threshold} 超")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="keiba", description="競馬予想支援ソフト (Phase 1)")
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
    s.set_defaults(func=cmd_train)

    s = sub.add_parser("evaluate", help="時系列分割でモデルを検証")
    s.add_argument("--test-start", required=True, help="検証期間の開始日 (YYYY-MM-DD)")
    s.set_defaults(func=cmd_evaluate)

    s = sub.add_parser("predict", help="レースの勝率を予測して表示")
    s.add_argument("--model", type=Path, default=model.DEFAULT_MODEL_PATH)
    s.add_argument("--date", help="対象日 (YYYY-MM-DD)")
    s.add_argument("--race-id", help="対象レース ID")
    s.add_argument("--output", help="結果を CSV 出力するパス")
    s.add_argument("--ev-threshold", type=float, default=1.2)
    s.set_defaults(func=cmd_predict)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
