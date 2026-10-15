from datetime import date, timedelta

import pytest

from todo import db

TODAY = date(2026, 10, 15)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "todo.db"


def titles(tasks):
    return [t.title for t in tasks]


def test_add_and_get(path):
    tid = db.add_task("  牛乳を買う ", TODAY, 1, "買い物、 家事,買い物", "低脂肪", path=path)
    task = db.get_task(tid, path=path)
    assert task.title == "牛乳を買う"
    assert task.due_date == TODAY
    assert task.priority == 1
    assert task.tags == ["買い物", "家事"]
    assert task.note == "低脂肪"
    assert not task.done and task.completed_at is None


def test_validation(path):
    with pytest.raises(ValueError):
        db.add_task("  ", path=path)
    with pytest.raises(ValueError):
        db.add_task("x", priority=5, path=path)
    with pytest.raises(ValueError):
        db.list_tasks("unknown", path=path)


def test_update_and_delete(path):
    tid = db.add_task("旧", TODAY, path=path)
    db.update_task(tid, "新", None, 3, ["a"], "メモ", path=path)
    task = db.get_task(tid, path=path)
    assert (task.title, task.due_date, task.priority, task.tags, task.note) == ("新", None, 3, ["a"], "メモ")
    db.delete_task(tid, path=path)
    assert db.get_task(tid, path=path) is None


def test_done_toggle(path):
    tid = db.add_task("x", path=path)
    db.set_done(tid, True, path=path)
    task = db.get_task(tid, path=path)
    assert task.done and task.completed_at is not None
    db.set_done(tid, False, path=path)
    task = db.get_task(tid, path=path)
    assert not task.done and task.completed_at is None


def test_views_and_overdue(path):
    db.add_task("昨日", TODAY - timedelta(days=1), path=path)
    db.add_task("今日", TODAY, path=path)
    db.add_task("明日", TODAY + timedelta(days=1), path=path)
    db.add_task("期限なし", None, path=path)
    done = db.add_task("済", TODAY, path=path)
    db.set_done(done, True, path=path)

    today = db.list_tasks("today", today=TODAY, path=path)
    assert titles(today) == ["昨日", "今日"]
    assert [t.is_overdue(TODAY) for t in today] == [True, False]
    assert titles(db.list_tasks("open", today=TODAY, path=path)) == ["昨日", "今日", "明日", "期限なし"]
    assert titles(db.list_tasks("done", path=path)) == ["済"]
    assert len(db.list_tasks("all", path=path)) == 5
    assert db.counts(TODAY, path=path) == {"today": 2, "overdue": 1, "open": 4, "done": 1}


def test_sort_and_filters(path):
    db.add_task("A", TODAY + timedelta(days=2), 3, "仕事", path=path)
    db.add_task("B", TODAY + timedelta(days=5), 1, "仕事,家", "請求書", path=path)
    db.add_task("C", None, 2, "仕事場", path=path)

    assert titles(db.list_tasks(sort="due", path=path)) == ["A", "B", "C"]
    assert titles(db.list_tasks(sort="priority", path=path)) == ["B", "C", "A"]
    # タグは完全一致 (「仕事場」は「仕事」に含めない)
    assert titles(db.list_tasks(tag="仕事", path=path)) == ["A", "B"]
    assert titles(db.list_tasks(priority=2, path=path)) == ["C"]
    assert titles(db.list_tasks(keyword="請求", path=path)) == ["B"]
    assert db.all_tags(path=path) == ["仕事", "仕事場", "家"]
