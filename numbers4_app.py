"""ナンバーズ4 分析ソフト Web UI (抽せん結果の取り込み).

起動:  streamlit run numbers4_app.py

結果ページのスクリーンショット (またはコピーした文字) を Claude API で読み取り、
表で確認・修正してから DB に保存する。API キーは環境変数 ANTHROPIC_API_KEY か、サイドバーで入力する。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from numbers4 import db, importer, screenshot, validate

st.set_page_config(page_title="ナンバーズ4 取り込み", page_icon="🔢", layout="wide")

MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
INT_COLUMNS = ["draw_no", *db.OPTIONAL_COLUMNS]
LEVEL_ICON = {validate.ERROR: "🟥 エラー", validate.WARNING: "🟨 注意"}


# ---------------------------------------------------------------- サイドバー

with st.sidebar:
    st.header("設定")
    db_path = Path(st.text_input("DB のパス", str(db.DEFAULT_DB_PATH)))
    env_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    api_key = st.text_input(
        "Claude API キー", type="password",
        placeholder="環境変数 ANTHROPIC_API_KEY を使用中" if env_key else "sk-ant-...",
        help="入力したキーはこの画面を開いている間だけ使い、保存しません",
    )
    double_read = st.checkbox(
        "2 回読んで食い違いを確認する", value=True,
        help="同じ画像を 2 回読み、結果が違った箇所を「注意」として表示します。料金は 2 倍になります",
    )
    st.caption(f"読み取りモデル: {screenshot.MODEL}")


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=api_key or None)


def _existing() -> pd.DataFrame:
    return db.load_draws(db_path)


# ---------------------------------------------------------------- 読み取り

state = st.session_state
state.setdefault("readings", {})  # key -> {"name", "rows", "notes", "diffs", "image", "media_type"}
state.setdefault("draft", None)    # 確認・修正中の表
state.setdefault("editor_version", 0)


def _read(key: str, name: str, reader) -> None:
    """reader() -> Reading を (必要なら 2 回) 呼び、結果を state に入れる."""
    first = reader()
    diffs = pd.DataFrame(columns=["draw_no", "column", "first", "second"])
    if double_read:
        diffs = screenshot.compare_readings(first.rows, reader().rows)
    state.readings[key] |= {"rows": first.rows.assign(source=name), "notes": first.notes, "diffs": diffs}


def _rebuild_draft() -> None:
    frames = [r["rows"] for r in state.readings.values() if "rows" in r]
    if not frames:
        state.draft = None
        return
    draft = pd.concat(frames, ignore_index=True).sort_values("draw_no", kind="stable").reset_index(drop=True)
    draft["date"] = draft["date"].astype("string")
    draft["number"] = draft["number"].astype("string")
    for col in INT_COLUMNS:
        draft[col] = pd.to_numeric(draft[col], errors="coerce").astype("Int64")
    state.draft = draft[["source", *db.DRAW_COLUMNS]]
    state.editor_version += 1  # 表を作り直したときは編集内容をリセット


def _run(items: list[tuple[str, str, object, bytes | None, str | None]]) -> None:
    """items: (key, 表示名, reader, 画像, media_type). 読み取り済みの key は読み直さない."""
    todo = [it for it in items if "rows" not in state.readings.get(it[0], {})]
    if not todo:
        st.info("すべて読み取り済みです")
        return
    bar = st.progress(0.0)
    for i, (key, name, reader, image, media_type) in enumerate(todo):
        bar.progress(i / len(todo), text=f"読み取り中: {name} ({i + 1}/{len(todo)})")
        state.readings[key] = {"name": name, "image": image, "media_type": media_type}
        try:
            _read(key, name, reader)
        except screenshot.ReadError as e:
            state.readings[key]["error"] = str(e)
        except Exception as e:  # noqa: BLE001 - API キー未設定・通信エラーなどをそのまま画面に出す
            state.readings[key]["error"] = f"{type(e).__name__}: {e}"
    bar.empty()
    _rebuild_draft()


tab_import, tab_db = st.tabs(["取り込み", "登録済みデータ"])

with tab_import:
    st.subheader("1. 結果ページを読み取る")
    source = st.radio("読み取るもの", ["スクリーンショット", "ページの文字を貼り付け"], horizontal=True,
                      help="ページの文字をコピーして貼り付けるほうが、画像より読み違いが起きにくくなります")
    if source == "スクリーンショット":
        files = st.file_uploader("結果ページの画像 (複数可)", type=list(MEDIA_TYPES), accept_multiple_files=True)
        if st.button("読み取る", type="primary", disabled=not files):
            items = []
            for f in files:
                data = f.getvalue()
                media_type = MEDIA_TYPES[f.name.rsplit(".", 1)[-1].lower()]
                key = hashlib.sha256(data).hexdigest()[:16]

                def reader(data=data, media_type=media_type):
                    return screenshot.read_image(data, media_type, client=_client())

                items.append((key, f.name, reader, data, media_type))
            _run(items)
    else:
        text = st.text_area("結果ページの表をコピーして貼り付け", height=200)
        if st.button("読み取る", type="primary", disabled=not text.strip()):
            key = hashlib.sha256(text.encode()).hexdigest()[:16]
            _run([(key, f"貼り付け {key[:6]}", lambda: screenshot.read_text(text, client=_client()), None, None)])

    for key, r in list(state.readings.items()):
        label = r["name"]
        if "error" in r:
            label = f"⚠️ {label} — 読み取れませんでした"
        elif "rows" in r:
            label = f"{label} — {len(r['rows'])} 回分"
            if len(r["diffs"]):
                label += f" (食い違い {len(r['diffs'])} 箇所)"
        with st.expander(label, expanded="error" in r):
            if "error" in r:
                st.error(r["error"])
            if r.get("notes"):
                st.caption(f"読み取りメモ: {r['notes']}")
            if r.get("image") is not None:
                st.image(r["image"])
            if st.button("この結果を外す", key=f"drop-{key}"):
                del state.readings[key]
                _rebuild_draft()
                st.rerun()

    if state.draft is not None:
        st.subheader("2. 画像と見比べて確認・修正する")
        st.caption("セルを直接書き換えられます。行の追加・削除もできます (表の右上・行の左端)")
        labels = validate.COLUMN_LABELS
        column_config = {
            "source": st.column_config.TextColumn("読み取り元", disabled=True),
            "draw_no": st.column_config.NumberColumn(labels["draw_no"], format="%d", step=1),
            "date": st.column_config.TextColumn(labels["date"], help="YYYY-MM-DD"),
            "number": st.column_config.TextColumn(labels["number"], help="4 桁 (先頭の 0 も入れる)"),
            **{c: st.column_config.NumberColumn(labels[c], format="%d", step=1) for c in db.OPTIONAL_COLUMNS},
        }
        edited = st.data_editor(state.draft, column_config=column_config, num_rows="dynamic", hide_index=True,
                                use_container_width=True, key=f"editor-{state.editor_version}")

        st.subheader("3. チェック結果")
        rows = edited.drop(columns="source")
        diffs = [r["diffs"] for r in state.readings.values() if "diffs" in r and len(r["diffs"])]
        mismatches = validate.mismatch_issues(pd.concat(diffs)) if diffs else validate.mismatch_issues(pd.DataFrame(
            columns=["draw_no", "column", "first", "second"]))
        issues = pd.concat([validate.check(rows, _existing()), mismatches], ignore_index=True)
        n_err = int((issues["level"] == validate.ERROR).sum())
        n_warn = int((issues["level"] == validate.WARNING).sum())
        if issues.empty:
            st.success(f"問題は見つかりませんでした ({len(rows)} 回分)")
        else:
            st.write(f"エラー {n_err} 件 / 注意 {n_warn} 件")
            st.dataframe(
                issues.assign(level=issues["level"].map(LEVEL_ICON)).rename(columns={
                    "level": "種類", "draw_no": "回号", "column": "項目", "message": "内容"}),
                hide_index=True, use_container_width=True,
            )
            st.caption("「注意」は保存できますが、読み違いの可能性があるので画像と見比べてください。"
                       "食い違いの注意は、表を直しても消えません (確認したら保存して構いません)")

        col_save, col_csv = st.columns([1, 1])
        with col_save:
            if st.button(f"{len(rows)} 回分を DB に保存", type="primary", disabled=n_err > 0 or rows.empty):
                n = importer.import_frame(validate.to_import_frame(rows), db_path)
                state.readings = {}
                state.draft = None
                st.success(f"保存しました: {n} 回 ({db_path})")
                st.rerun()
            if n_err:
                st.caption("エラーを直すと保存できます")
        with col_csv:
            st.download_button("CSV でダウンロード", rows.to_csv(index=False).encode("utf-8-sig"),
                               file_name="numbers4_draws.csv", mime="text/csv",
                               help="保存せずに CSV で残す場合 (numbers4 import で取り込めます)")

with tab_db:
    draws = _existing()
    if draws.empty:
        st.info(f"まだデータがありません: {db_path}")
    else:
        first, last = draws.iloc[0], draws.iloc[-1]
        st.write(f"第{first['draw_no']}回 ({first['date']:%Y-%m-%d}) 〜 第{last['draw_no']}回 "
                 f"({last['date']:%Y-%m-%d}), {len(draws):,} 回")
        missing = (last["draw_no"] - first["draw_no"] + 1) - len(draws)
        if missing:
            st.warning(f"この範囲で {missing:,} 回分が未登録です")
        st.dataframe(
            draws.iloc[::-1].assign(date=draws["date"].dt.strftime("%Y-%m-%d")).rename(
                columns=validate.COLUMN_LABELS),
            hide_index=True, use_container_width=True,
        )
        st.caption("分析は CLI で: numbers4 check (乱数性チェック) / numbers4 stats (出目分析) / numbers4 lookup 0123")
