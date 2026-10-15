"""TODO の SQLite スキーマ定義と入出力."""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator

DEFAULT_DB_PATH = Path("data/todo.db")

PRIORITIES = {1: "高", 2: "中", 3: "低"}

VIEWS = ("today", "open", "all", "done")
SORTS = ("due", "priority")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    due_date      TEXT,                       -- YYYY-MM-DD (期限なしは NULL)
    priority      INTEGER NOT NULL DEFAULT 2, -- 1=高 / 2=中 / 3=低
    tags          TEXT NOT NULL DEFAULT '',   -- カンマ区切り
    done          INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,              -- YYYY-MM-DD HH:MM:SS
    completed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_done_due ON tasks (done, due_date);
"""

# 列を追加するときは SCHEMA を変えずに MIGRATIONS に ALTER 文を足す (user_version で管理)
MIGRATIONS: list[str] = []


@dataclass
class Task:
    id: int
    title: str
    note: str
    due_date: date | None
    priority: int
    tags: list[str]
    done: bool
    created_at: datetime
    completed_at: datetime | None

    def is_overdue(self, today: date | None = None) -> bool:
        today = today or date.today()
        return not self.done and self.due_date is not None and self.due_date < today

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Task:
        return cls(
            id=row["id"],
            title=row["title"],
            note=row["note"],
            due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
            priority=row["priority"],
            tags=parse_tags(row["tags"]),
            done=bool(row["done"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )


def parse_tags(text: str | Iterable[str] | None) -> list[str]:
    """「仕事, 家事、買い物」のような入力をタグのリストにする (空白除去・重複除去)."""
    if not text:
        return []
    if isinstance(text, str):
        text = text.replace("、", ",").replace("，", ",").split(",")
    tags: list[str] = []
    for t in text:
        t = t.strip()
        if t and t not in tags:
            tags.append(t)
    return tags


def connect(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    version = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        con.execute(sql)
        con.execute(f"PRAGMA user_version = {i}")
    con.commit()
    return con


@contextmanager
def _session(path: str | Path) -> Iterator[sqlite3.Connection]:
    """成功時にコミットし, 最後に必ず接続を閉じる."""
    with closing(connect(path)) as con, con:
        yield con


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _check_priority(priority: int) -> int:
    if priority not in PRIORITIES:
        raise ValueError(f"priority は 1〜3 で指定してください: {priority}")
    return priority


def add_task(
    title: str,
    due_date: date | None = None,
    priority: int = 2,
    tags: str | Iterable[str] | None = None,
    note: str = "",
    path: str | Path = DEFAULT_DB_PATH,
) -> int:
    title = title.strip()
    if not title:
        raise ValueError("タイトルを入力してください")
    with _session(path) as con:
        cur = con.execute(
            "INSERT INTO tasks (title, note, due_date, priority, tags, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                title,
                note.strip(),
                due_date.isoformat() if due_date else None,
                _check_priority(priority),
                ",".join(parse_tags(tags)),
                _now(),
            ),
        )
        return cur.lastrowid


def get_task(task_id: int, path: str | Path = DEFAULT_DB_PATH) -> Task | None:
    with _session(path) as con:
        row = con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return Task.from_row(row) if row else None


def update_task(
    task_id: int,
    title: str,
    due_date: date | None,
    priority: int,
    tags: str | Iterable[str] | None,
    note: str,
    path: str | Path = DEFAULT_DB_PATH,
) -> None:
    title = title.strip()
    if not title:
        raise ValueError("タイトルを入力してください")
    with _session(path) as con:
        con.execute(
            "UPDATE tasks SET title = ?, note = ?, due_date = ?, priority = ?, tags = ? WHERE id = ?",
            (
                title,
                note.strip(),
                due_date.isoformat() if due_date else None,
                _check_priority(priority),
                ",".join(parse_tags(tags)),
                task_id,
            ),
        )


def set_done(task_id: int, done: bool, path: str | Path = DEFAULT_DB_PATH) -> None:
    with _session(path) as con:
        con.execute(
            "UPDATE tasks SET done = ?, completed_at = ? WHERE id = ?",
            (int(done), _now() if done else None, task_id),
        )


def delete_task(task_id: int, path: str | Path = DEFAULT_DB_PATH) -> None:
    with _session(path) as con:
        con.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def list_tasks(
    view: str = "open",
    sort: str = "due",
    tag: str | None = None,
    priority: int | None = None,
    keyword: str | None = None,
    today: date | None = None,
    path: str | Path = DEFAULT_DB_PATH,
) -> list[Task]:
    """タスクを絞り込んで返す.

    view: today=未完了で期限が今日以前 / open=未完了 / all=すべて / done=完了済み (完了日の新しい順)
    sort: due=期限の近い順 (期限なしは最後) / priority=優先度の高い順
    """
    if view not in VIEWS:
        raise ValueError(f"view は {VIEWS} のいずれか: {view}")
    if sort not in SORTS:
        raise ValueError(f"sort は {SORTS} のいずれか: {sort}")
    today = today or date.today()

    where, params = [], []
    if view == "today":
        where.append("done = 0 AND due_date IS NOT NULL AND due_date <= ?")
        params.append(today.isoformat())
    elif view == "open":
        where.append("done = 0")
    elif view == "done":
        where.append("done = 1")
    if priority is not None:
        where.append("priority = ?")
        params.append(priority)
    if keyword:
        where.append("(title LIKE ? OR note LIKE ?)")
        params += [f"%{keyword}%"] * 2
    if tag:
        # カンマ区切りの前後にカンマを付けて完全一致させる
        where.append("(',' || tags || ',') LIKE ?")
        params.append(f"%,{tag},%")

    due = "due_date IS NULL, due_date"
    if view == "done":
        order = "completed_at DESC, id DESC"
    elif sort == "due":
        order = f"done, {due}, priority, id"
    else:
        order = f"done, priority, {due}, id"

    sql = "SELECT * FROM tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order}"
    with _session(path) as con:
        return [Task.from_row(r) for r in con.execute(sql, params)]


def all_tags(path: str | Path = DEFAULT_DB_PATH) -> list[str]:
    with _session(path) as con:
        rows = con.execute("SELECT tags FROM tasks WHERE tags != ''").fetchall()
    return sorted({t for r in rows for t in parse_tags(r["tags"])})


def counts(today: date | None = None, path: str | Path = DEFAULT_DB_PATH) -> dict[str, int]:
    """サイドバー表示用の件数."""
    today = (today or date.today()).isoformat()
    with _session(path) as con:
        row = con.execute(
            "SELECT"
            " SUM(done = 0 AND due_date <= ?) AS today,"
            " SUM(done = 0 AND due_date < ?) AS overdue,"
            " SUM(done = 0) AS open,"
            " SUM(done = 1) AS done"
            " FROM tasks",
            (today, today),
        ).fetchone()
    return {k: row[k] or 0 for k in ("today", "overdue", "open", "done")}
