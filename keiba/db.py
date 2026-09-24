"""SQLite データベースのスキーマ定義と入出力."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("data/keiba.db")

RACE_COLUMNS = [
    "race_id",          # 例: 202405050811 (年+場+回+日+R)
    "date",             # YYYY-MM-DD
    "course",           # 競馬場名 (東京, 中山, ...)
    "race_number",      # R 番号
    "surface",          # 芝 / ダート
    "distance",         # m
    "track_condition",  # 良 / 稍重 / 重 / 不良
    "race_class",       # 新馬 / 未勝利 / 1勝 / 2勝 / 3勝 / OP / G3 / G2 / G1
]

ENTRY_COLUMNS = [
    "race_id",
    "horse_id",
    "horse_name",
    "jockey_id",
    "trainer_id",
    "frame_number",       # 枠番
    "horse_number",       # 馬番
    "sex",                # 牡 / 牝 / セ
    "age",
    "weight_carried",     # 斤量 (kg)
    "horse_weight",       # 馬体重 (kg)
    "horse_weight_diff",  # 馬体重増減 (kg)
    "odds",               # 単勝オッズ
    "popularity",         # 人気
    "finish_position",    # 着順 (未確定のレースは NULL)
    "time_sec",           # 走破タイム (秒)
    "last_3f",            # 上がり3F (秒)
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS races (
    race_id         TEXT PRIMARY KEY,
    date            TEXT NOT NULL,
    course          TEXT NOT NULL,
    race_number     INTEGER,
    surface         TEXT NOT NULL,
    distance        INTEGER NOT NULL,
    track_condition TEXT,
    race_class      TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    race_id           TEXT NOT NULL REFERENCES races(race_id),
    horse_id          TEXT NOT NULL,
    horse_name        TEXT,
    jockey_id         TEXT,
    trainer_id        TEXT,
    frame_number      INTEGER,
    horse_number      INTEGER NOT NULL,
    sex               TEXT,
    age               INTEGER,
    weight_carried    REAL,
    horse_weight      REAL,
    horse_weight_diff REAL,
    odds              REAL,
    popularity        INTEGER,
    finish_position   INTEGER,
    time_sec          REAL,
    last_3f           REAL,
    PRIMARY KEY (race_id, horse_number)
);

CREATE INDEX IF NOT EXISTS idx_races_date ON races(date);
CREATE INDEX IF NOT EXISTS idx_entries_horse ON entries(horse_id);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _upsert(conn: sqlite3.Connection, table: str, df: pd.DataFrame, columns: list[str]) -> int:
    df = df[columns].astype(object).where(df[columns].notna(), None)
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, df.itertuples(index=False, name=None))
    return len(df)


def save_races(conn: sqlite3.Connection, races: pd.DataFrame) -> int:
    return _upsert(conn, "races", races, RACE_COLUMNS)


def save_entries(conn: sqlite3.Connection, entries: pd.DataFrame) -> int:
    return _upsert(conn, "entries", entries, ENTRY_COLUMNS)


def load_joined(db_path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """races と entries を結合した 1 行 = 1 頭 のデータを返す."""
    with connect(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT e.*, r.date, r.course, r.race_number, r.surface, r.distance,
                   r.track_condition, r.race_class
            FROM entries e JOIN races r USING (race_id)
            ORDER BY r.date, r.race_id, e.horse_number
            """,
            conn,
        )
    df["date"] = pd.to_datetime(df["date"])
    return df
