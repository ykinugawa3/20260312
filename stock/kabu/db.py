"""SQLite スキーマと入出力.

株価は **調整前** の値で保存し、分割・配当は corporate_actions に別に持つ。
調整後株価は kabu.adjust で毎回計算する (提供元が過去の調整後株価を書き換えても再現できるように)。
銘柄はティッカーではなくソフト内の security_id で管理する (ティッカー変更・再利用に備える)。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("data/kabu.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS securities (
    security_id   INTEGER PRIMARY KEY,
    ticker        TEXT NOT NULL UNIQUE,
    name          TEXT,
    sector        TEXT,
    listed_date   TEXT,
    delisted_date TEXT
);
CREATE TABLE IF NOT EXISTS prices_daily (
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL NOT NULL,
    volume      REAL,
    PRIMARY KEY (security_id, date)
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    date        TEXT NOT NULL,
    split_ratio REAL NOT NULL DEFAULT 1.0,
    dividend    REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (security_id, date)
);
CREATE TABLE IF NOT EXISTS index_membership (
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    index_name  TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    PRIMARY KEY (security_id, index_name, start_date)
);
"""

SECURITY_COLUMNS = ["ticker", "name", "sector", "listed_date", "delisted_date"]
PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
ACTION_COLUMNS = ["date", "split_ratio", "dividend"]
MEMBERSHIP_COLUMNS = ["index_name", "start_date", "end_date"]


def connect(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def _none_if_na(values: list) -> list:
    return [None if pd.isna(v) else v for v in values]


def upsert_securities(conn: sqlite3.Connection, securities: pd.DataFrame) -> dict[str, int]:
    """ティッカーで照合して銘柄を登録・更新し、ticker → security_id の対応を返す.

    既存の銘柄で新しい値が空欄の項目は上書きしない.
    """
    df = securities.reindex(columns=SECURITY_COLUMNS)
    conn.executemany(
        """
        INSERT INTO securities (ticker, name, sector, listed_date, delisted_date)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            name = COALESCE(excluded.name, name),
            sector = COALESCE(excluded.sector, sector),
            listed_date = COALESCE(excluded.listed_date, listed_date),
            delisted_date = COALESCE(excluded.delisted_date, delisted_date)
        """,
        [_none_if_na(row) for row in df.itertuples(index=False, name=None)],
    )
    rows = conn.execute("SELECT ticker, security_id FROM securities").fetchall()
    return dict(rows)


def _upsert(conn: sqlite3.Connection, table: str, key_cols: list[str], df: pd.DataFrame) -> int:
    cols = list(df.columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in key_cols)
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT({', '.join(key_cols)}) DO UPDATE SET {updates}"
    )
    conn.executemany(sql, [_none_if_na(row) for row in df.itertuples(index=False, name=None)])
    return len(df)


def upsert_prices(conn: sqlite3.Connection, prices: pd.DataFrame) -> int:
    """prices: security_id + PRICE_COLUMNS. 同じ銘柄・日付は上書き (何度取り込んでも同じ結果になる)."""
    return _upsert(conn, "prices_daily", ["security_id", "date"], prices[["security_id", *PRICE_COLUMNS]])


def upsert_actions(conn: sqlite3.Connection, actions: pd.DataFrame) -> int:
    return _upsert(conn, "corporate_actions", ["security_id", "date"], actions[["security_id", *ACTION_COLUMNS]])


def replace_membership(conn: sqlite3.Connection, index_name: str, membership: pd.DataFrame) -> int:
    """指数の構成銘柄履歴を丸ごと入れ替える. membership: security_id, start_date, end_date."""
    conn.execute("DELETE FROM index_membership WHERE index_name = ?", (index_name,))
    df = membership.assign(index_name=index_name)[["security_id", *MEMBERSHIP_COLUMNS]]
    conn.executemany(
        "INSERT OR REPLACE INTO index_membership VALUES (?, ?, ?, ?)",
        [_none_if_na(row) for row in df.itertuples(index=False, name=None)],
    )
    return len(df)


def load_securities(path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    with closing(connect(path)) as conn:
        return pd.read_sql("SELECT * FROM securities ORDER BY security_id", conn)


def load_prices(path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """全銘柄の調整前日足に ticker と sector を付けて返す."""
    with closing(connect(path)) as conn:
        df = pd.read_sql(
            """
            SELECT p.*, s.ticker, s.sector
            FROM prices_daily p JOIN securities s USING (security_id)
            ORDER BY p.security_id, p.date
            """,
            conn,
        )
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_actions(path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    with closing(connect(path)) as conn:
        df = pd.read_sql("SELECT * FROM corporate_actions ORDER BY security_id, date", conn)
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_membership(path: str | Path = DEFAULT_DB_PATH, index_name: str = "SP500") -> pd.DataFrame:
    with closing(connect(path)) as conn:
        df = pd.read_sql(
            "SELECT security_id, start_date, end_date FROM index_membership WHERE index_name = ?",
            conn,
            params=(index_name,),
        )
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    return df
