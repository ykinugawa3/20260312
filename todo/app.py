"""TODO 管理 Web UI.

起動:  streamlit run todo/app.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

# `streamlit run todo/app.py` ではリポジトリ直下が import パスに入らないため追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from todo import db  # noqa: E402

DB_PATH = db.DEFAULT_DB_PATH
PRIORITY_ICON = {1: "🔴", 2: "🟡", 3: "⚪"}

st.set_page_config(page_title="TODO", page_icon="✅", layout="centered")


def priority_label(p: int) -> str:
    return f"{PRIORITY_ICON[p]} {db.PRIORITIES[p]}"


# ---------------------------------------------------------------- 操作 (コールバック)

def toggle_done(task_id: int) -> None:
    db.set_done(task_id, st.session_state[f"done_{task_id}"], path=DB_PATH)


def delete(task_id: int) -> None:
    db.delete_task(task_id, path=DB_PATH)
    st.toast("削除しました")


# ---------------------------------------------------------------- 部品

def add_form() -> None:
    with st.form("add", clear_on_submit=True, border=True):
        title = st.text_input("タスク", placeholder="例: 牛乳を買う", label_visibility="collapsed")
        c1, c2, c3 = st.columns([1, 1, 2])
        due = c1.date_input("期限", value=date.today(), format="YYYY/MM/DD")
        no_due = c1.checkbox("期限なし")
        priority = c2.selectbox("優先度", [1, 2, 3], index=1, format_func=priority_label)
        tags = c3.text_input("タグ (カンマ区切り)", placeholder="仕事, 買い物")
        if st.form_submit_button("追加", type="primary", use_container_width=True):
            if not title.strip():
                st.warning("タスク名を入力してください")
            else:
                db.add_task(title, None if no_due else due, priority, tags, path=DB_PATH)
                st.toast(f"追加しました: {title.strip()}")


def edit_form(task: db.Task) -> None:
    with st.form(f"edit_{task.id}", border=False):
        title = st.text_input("タイトル", task.title)
        c1, c2 = st.columns(2)
        due = c1.date_input("期限", value=task.due_date, format="YYYY/MM/DD", help="空欄で期限なし")
        priority = c2.selectbox(
            "優先度", [1, 2, 3], index=task.priority - 1, format_func=priority_label
        )
        tags = st.text_input("タグ (カンマ区切り)", ", ".join(task.tags))
        note = st.text_area("メモ", task.note, height=80)
        if st.form_submit_button("保存", type="primary"):
            if not title.strip():
                st.warning("タイトルを入力してください")
            else:
                db.update_task(task.id, title, due, priority, tags, note, path=DB_PATH)
                st.rerun()
    st.button("🗑 削除", key=f"del_{task.id}", on_click=delete, args=(task.id,))


def due_text(task: db.Task, today: date) -> str:
    if task.due_date is None:
        return ""
    d = task.due_date
    label = "今日" if d == today else "明日" if (d - today).days == 1 else f"{d:%m/%d}"
    if task.is_overdue(today):
        return f":red[**期限切れ {d:%m/%d}**]"
    return f":orange[{label}]" if d == today else label


def task_row(task: db.Task, today: date) -> None:
    with st.container(border=True):
        c1, c2 = st.columns([0.08, 0.92], vertical_alignment="center")
        c1.checkbox(
            "完了", value=task.done, key=f"done_{task.id}",
            on_change=toggle_done, args=(task.id,), label_visibility="collapsed",
        )
        title = f"~~{task.title}~~" if task.done else f"**{task.title}**"
        meta = [PRIORITY_ICON[task.priority]]
        if task.done and task.completed_at:
            meta.append(f"完了 {task.completed_at:%m/%d %H:%M}")
        elif text := due_text(task, today):
            meta.append(text)
        meta += [f"`{t}`" for t in task.tags]
        c2.markdown(f"{title}  \n{' · '.join(meta)}")
        if task.note:
            c2.caption(task.note)
        with c2.expander("編集"):
            edit_form(task)


def task_list(tasks: list[db.Task], today: date, empty: str) -> None:
    if not tasks:
        st.info(empty)
    for task in tasks:
        task_row(task, today)


# ---------------------------------------------------------------- 画面

today = date.today()
counts = db.counts(today, path=DB_PATH)

st.sidebar.title("✅ TODO")
pages = {
    "今日": f"📅 今日 ({counts['today']})",
    "一覧": f"📋 一覧 ({counts['open']})",
    "完了履歴": f"✔️ 完了履歴 ({counts['done']})",
}
page = st.sidebar.radio("画面", list(pages), format_func=pages.get, label_visibility="collapsed")
if counts["overdue"]:
    st.sidebar.error(f"期限切れのタスクが {counts['overdue']} 件あります")

if page == "今日":
    st.header(f"今日 {today:%m/%d}")
    add_form()
    tasks = db.list_tasks("today", sort="priority", today=today, path=DB_PATH)
    overdue = [t for t in tasks if t.is_overdue(today)]
    if overdue:
        st.subheader(f"期限切れ ({len(overdue)})")
        task_list(overdue, today, "")
        st.subheader("今日まで")
    task_list(
        [t for t in tasks if not t.is_overdue(today)], today,
        "今日が期限のタスクはありません 🎉",
    )

elif page == "一覧":
    st.header("一覧")
    add_form()
    c1, c2, c3 = st.columns(3)
    status = c1.selectbox("状態", ["open", "all"], format_func={"open": "未完了", "all": "すべて"}.get)
    tag = c2.selectbox("タグ", [None, *db.all_tags(path=DB_PATH)], format_func=lambda t: t or "すべて")
    priority = c3.selectbox(
        "優先度", [None, 1, 2, 3], format_func=lambda p: priority_label(p) if p else "すべて"
    )
    c1, c2 = st.columns([2, 1])
    keyword = c1.text_input("検索", placeholder="タイトル・メモで検索")
    sort = c2.radio("並び順", ["due", "priority"], horizontal=True,
                    format_func={"due": "期限順", "priority": "優先度順"}.get)
    tasks = db.list_tasks(status, sort, tag, priority, keyword, today, path=DB_PATH)
    st.caption(f"{len(tasks)} 件")
    task_list(tasks, today, "該当するタスクはありません")

else:
    st.header("完了履歴")
    tasks = db.list_tasks("done", today=today, path=DB_PATH)
    if not tasks:
        st.info("まだ完了したタスクはありません")
    current = None
    for task in tasks:
        day = task.completed_at.date() if task.completed_at else None
        if day != current:
            current = day
            st.subheader(f"{day:%Y/%m/%d}" if day else "日付不明")
        task_row(task, today)
    st.caption("チェックを外すと未完了に戻ります")
