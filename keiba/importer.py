"""CSV からのデータ取込.

races.csv / entries.csv の列は keiba.db.RACE_COLUMNS / ENTRY_COLUMNS に合わせる。
JRA-VAN 等から取得したデータをこの形式に変換して取り込む想定。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from keiba import db

REQUIRED_RACE_COLUMNS = ["race_id", "date", "course", "surface", "distance"]
REQUIRED_ENTRY_COLUMNS = ["race_id", "horse_id", "horse_number"]


class ImportErrorWithDetail(ValueError):
    pass


def _check_columns(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ImportErrorWithDetail(f"{name}: 必須列がありません: {missing}")


def normalize_races(races: pd.DataFrame) -> pd.DataFrame:
    _check_columns(races, REQUIRED_RACE_COLUMNS, "races")
    races = races.copy()
    for col in db.RACE_COLUMNS:
        if col not in races.columns:
            races[col] = None
    races["race_id"] = races["race_id"].astype(str)
    races["date"] = pd.to_datetime(races["date"]).dt.strftime("%Y-%m-%d")
    return races


def normalize_entries(entries: pd.DataFrame) -> pd.DataFrame:
    _check_columns(entries, REQUIRED_ENTRY_COLUMNS, "entries")
    entries = entries.copy()
    for col in db.ENTRY_COLUMNS:
        if col not in entries.columns:
            entries[col] = None
    for col in ("race_id", "horse_id", "jockey_id", "trainer_id"):
        entries[col] = entries[col].where(entries[col].isna(), entries[col].astype(str))
    # 中止・除外などで着順が数値でない行は未確定扱い
    entries["finish_position"] = pd.to_numeric(entries["finish_position"], errors="coerce")
    return entries


def import_frames(races: pd.DataFrame, entries: pd.DataFrame, db_path: str | Path) -> tuple[int, int]:
    races = normalize_races(races)
    entries = normalize_entries(entries)
    db.init_db(db_path)
    unknown = set(entries["race_id"]) - set(races["race_id"])
    if unknown:
        # DB に既存のレースなら OK
        with db.connect(db_path) as conn:
            existing = {r[0] for r in conn.execute("SELECT race_id FROM races")}
        unknown -= existing
        if unknown:
            sample = sorted(unknown)[:5]
            raise ImportErrorWithDetail(f"entries に races に無い race_id があります: {sample}")
    with db.connect(db_path) as conn:
        n_races = db.save_races(conn, races)
        n_entries = db.save_entries(conn, entries)
    return n_races, n_entries


def import_csv(races_csv: str | Path, entries_csv: str | Path, db_path: str | Path) -> tuple[int, int]:
    races = pd.read_csv(races_csv, dtype={"race_id": str})
    entries = pd.read_csv(
        entries_csv, dtype={"race_id": str, "horse_id": str, "jockey_id": str, "trainer_id": str}
    )
    return import_frames(races, entries, db_path)
