"""CSV からの抽せん結果の取込.

列名は numbers4.db.DRAW_COLUMNS (英語) か、結果サイトでよく使われる日本語の列名で書く。
必須は 回号・抽せん日・当せん番号 の 3 列。当選口数・当せん金・売上は任意 (Phase 2 で使う)。
"第6000回" / "2026年10月2日" / "1,013,700円" / "該当なし" のような表記はそのまま読める。
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from numbers4 import db

REQUIRED_COLUMNS = ["draw_no", "date", "number"]

COLUMN_ALIASES = {
    "回号": "draw_no", "回別": "draw_no", "回": "draw_no",
    "抽せん日": "date", "抽選日": "date", "日付": "date",
    "当せん番号": "number", "当選番号": "number", "抽せん数字": "number", "抽選数字": "number",
    "ストレート口数": "straight_winners", "ストレート当せん口数": "straight_winners",
    "ストレート当せん金": "straight_payout", "ストレート当選金額": "straight_payout",
    "ボックス口数": "box_winners", "ボックス当せん口数": "box_winners",
    "ボックス当せん金": "box_payout", "ボックス当選金額": "box_payout",
    "セットストレート口数": "set_straight_winners", "セット(ストレート)口数": "set_straight_winners",
    "セットストレート当せん金": "set_straight_payout", "セット(ストレート)当せん金": "set_straight_payout",
    "セットボックス口数": "set_box_winners", "セット(ボックス)口数": "set_box_winners",
    "セットボックス当せん金": "set_box_payout", "セット(ボックス)当せん金": "set_box_payout",
    "販売実績額": "sales", "売上": "sales", "販売額": "sales",
}


class ImportErrorWithDetail(ValueError):
    pass


def _to_int(series: pd.Series) -> pd.Series:
    """'1,013,700円' や '第6000回' から数字だけを取り出す. 数字が無い ('該当なし' 等) は NaN."""
    # "33700.0" (数値が文字列化されたもの) の小数部を数字に混ぜないよう先に落とす
    text = series.astype(str).str.strip().str.replace(r"\.0*$", "", regex=True)
    digits = text.str.replace(r"[^\d]", "", regex=True)
    return pd.to_numeric(digits.where(digits != "", None), errors="coerce").astype("Int64")


def _to_date(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    text = text.str.replace(r"(\d+)年(\d+)月(\d+)日.*", r"\1-\2-\3", regex=True)
    text = text.str.replace(r"\(.\)$", "", regex=True)  # "2026/10/02(金)" の曜日
    return pd.to_datetime(text, errors="coerce", format="mixed")


def _to_number(series: pd.Series) -> pd.Series:
    """当せん番号を 4 桁の文字列にそろえる. CSV で先頭の 0 が落ちた '123' は '0123' に戻す."""
    text = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    text = text.str.replace(r"[\s\-,]", "", regex=True)
    return text.where(~text.str.fullmatch(r"\d{1,3}"), text.str.zfill(4))


def normalize(draws: pd.DataFrame) -> pd.DataFrame:
    draws = draws.rename(columns=lambda c: COLUMN_ALIASES.get(str(c).strip(), str(c).strip()))
    missing = [c for c in REQUIRED_COLUMNS if c not in draws.columns]
    if missing:
        raise ImportErrorWithDetail(f"必須列がありません: {missing} (列: {list(draws.columns)})")
    draws = draws.copy()
    for col in db.OPTIONAL_COLUMNS:
        draws[col] = _to_int(draws[col]) if col in draws.columns else pd.NA

    draws["draw_no"] = _to_int(draws["draw_no"])
    draws["date"] = _to_date(draws["date"])
    draws["number"] = _to_number(draws["number"])

    bad = draws["draw_no"].isna() | draws["date"].isna() | ~draws["number"].str.fullmatch(r"\d{4}")
    if bad.any():
        rows = draws.loc[bad, ["draw_no", "date", "number"]].head(5).to_dict("records")
        raise ImportErrorWithDetail(f"読めない行が {int(bad.sum())} 行あります (先頭 5 行): {rows}")
    dup = draws["draw_no"].duplicated(keep=False)
    if dup.any():
        raise ImportErrorWithDetail(f"回号が重複しています: {sorted(draws.loc[dup, 'draw_no'].unique())[:5]}")
    draws["date"] = draws["date"].dt.strftime("%Y-%m-%d")
    return draws[db.DRAW_COLUMNS].sort_values("draw_no")


def import_frame(draws: pd.DataFrame, db_path: str | Path) -> int:
    draws = normalize(draws)
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        return db.save_draws(conn, draws)


def import_csv(csv_path: str | Path, db_path: str | Path) -> int:
    # 先頭の 0 が落ちないよう全列を文字列で読む. 結果サイトの CSV は Shift_JIS のことが多い
    try:
        draws = pd.read_csv(csv_path, dtype=str)
    except UnicodeDecodeError:
        draws = pd.read_csv(csv_path, dtype=str, encoding="cp932")
    return import_frame(draws, db_path)
