"""SQLite データベースのスキーマ定義と入出力."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("data/numbers4.db")

DRAW_COLUMNS = [
    "draw_no",               # 回号
    "date",                  # 抽せん日 YYYY-MM-DD
    "number",                # 当せん番号 (4 桁の文字列, 例: "0123")
    "straight_winners",      # ストレート 当せん口数
    "straight_payout",       # ストレート 1 口あたり当せん金 (円)
    "box_winners",           # ボックス
    "box_payout",
    "set_straight_winners",  # セット (ストレート部分)
    "set_straight_payout",
    "set_box_winners",       # セット (ボックス部分)
    "set_box_payout",
    "sales",                 # 販売実績額 (円)
]
# 当選口数・当せん金・売上は Phase 2 (人気推定) で使う。抽せん結果だけでも Phase 1 の分析はできる
OPTIONAL_COLUMNS = DRAW_COLUMNS[3:]

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    draw_no              INTEGER PRIMARY KEY,
    date                 TEXT NOT NULL,
    number               TEXT NOT NULL CHECK (length(number) = 4),
    straight_winners     INTEGER,
    straight_payout      INTEGER,
    box_winners          INTEGER,
    box_payout           INTEGER,
    set_straight_winners INTEGER,
    set_straight_payout  INTEGER,
    set_box_winners      INTEGER,
    set_box_payout       INTEGER,
    sales                INTEGER
);

CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(date);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def save_draws(conn: sqlite3.Connection, draws: pd.DataFrame) -> int:
    df = draws[DRAW_COLUMNS].astype(object).where(draws[DRAW_COLUMNS].notna(), None)
    placeholders = ", ".join("?" for _ in DRAW_COLUMNS)
    sql = f"INSERT OR REPLACE INTO draws ({', '.join(DRAW_COLUMNS)}) VALUES ({placeholders})"
    conn.executemany(sql, df.itertuples(index=False, name=None))
    return len(df)


def load_draws(db_path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """1 行 = 1 回 の抽せん結果を回号順で返す."""
    init_db(db_path)
    with connect(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM draws ORDER BY draw_no", conn, dtype={"number": str})
    df["date"] = pd.to_datetime(df["date"])
    return df
