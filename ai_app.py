"""AI 全頭分析 (Claude + Web 検索) の Web UI.

起動: streamlit run ai_app.py   (Windows は ai_start.bat をダブルクリック)
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from keiba import ai_analyst

st.set_page_config(page_title="AI 全頭分析 競馬予想", page_icon="🏇", layout="wide")

REPORT_DIR = Path("reports")

# ---------------------------------------------------------------- サイドバー

with st.sidebar:
    st.header("🏇 AI 全頭分析")
    key_in_env = ai_analyst.has_api_key()
    api_key = None
    if key_in_env:
        st.caption("Claude API キー: 環境変数から読み込み済み")
    else:
        api_key = st.text_input("Claude API キー", type="password",
                                help="console.anthropic.com で発行したキー。保存はされません。") or None

    with st.expander("詳細設定"):
        model_name = st.text_input("モデル", ai_analyst.DEFAULT_MODEL)
        effort = st.select_slider("推論の深さ (effort)", ai_analyst.EFFORT_LEVELS,
                                  value=ai_analyst.DEFAULT_EFFORT,
                                  help="上げるほど丁寧だが、時間と料金が増える")
        save = st.checkbox("レポートを reports/ に保存", value=True)

    st.divider()
    st.subheader("保存済みレポート")
    saved = sorted(REPORT_DIR.glob("*.md"), reverse=True) if REPORT_DIR.exists() else []
    chosen = st.selectbox("開く", ["—"] + [p.name for p in saved])

# ---------------------------------------------------------------- 入力

st.title("競馬予想 ― 全頭徹底分析")
st.caption("レース名を入れて実行すると、Claude が Web で最新の出馬表・オッズ・馬場・調教などを調べ、"
           "全頭評価・展開予測・買い目・信頼度判定までをレポートにします (数分〜十数分)。")

with st.form("req"):
    c1, c2, c3 = st.columns([3, 1, 2])
    race_name = c1.text_input("レース名", placeholder="例: ジャパンカップ / 有馬記念 / 東京大賞典")
    year = c2.text_input("開催年", placeholder="未指定=次回")
    policy = c3.selectbox("重視する方針", ai_analyst.POLICIES)
    notes = st.text_input("補足 (任意)", placeholder="例: 2026年11月29日 東京11R / 馬場は稍重見込み")
    submitted = st.form_submit_button("調査・分析を開始", type="primary", width="stretch")

st.info("AI による調査・推定です。的中を保証するものではありません。"
        "馬番・オッズ・出走取消などは必ず公式発表で確認し、馬券は無理のない範囲で購入してください。", icon="⚠️")

# ---------------------------------------------------------------- 実行

if submitted:
    if not race_name.strip():
        st.error("レース名を入力してください")
        st.stop()
    if not (key_in_env or api_key):
        st.error("サイドバーで Claude API キーを入力してください")
        st.stop()

    req = ai_analyst.AnalysisRequest(race_name=race_name, year=year, policy=policy, notes=notes,
                                     model=model_name.strip() or ai_analyst.DEFAULT_MODEL, effort=effort)
    status = st.status("調査を開始しています…", expanded=True)
    report_box = st.empty()
    text = ""
    done = None
    n_search = 0
    try:
        for ev in ai_analyst.stream_analysis(req, api_key=api_key):
            if ev.kind == "search":
                n_search += 1
                status.update(label=f"Web 検索中… ({n_search} 回目)")
                status.write(f"🔍 {ev.text}")
            elif ev.kind == "fetch":
                status.write(f"📄 {ev.text}")
            elif ev.kind == "info":
                status.write(f"… {ev.text}")
            elif ev.kind == "text":
                if not text:
                    status.update(label="レポートを作成しています…")
                text += ev.text
                report_box.markdown(text + " ▌")
            elif ev.kind == "done":
                done = ev
    except Exception as ex:  # API キー誤り・通信エラーなどを画面に出す
        import anthropic

        status.update(label="エラーが発生しました", state="error")
        if isinstance(ex, anthropic.AuthenticationError):
            st.error("API キーが正しくありません。")
        elif isinstance(ex, anthropic.RateLimitError):
            st.error("API の利用上限に達しました。少し待ってから再実行してください。")
        elif isinstance(ex, anthropic.APIConnectionError):
            st.error("Claude API に接続できませんでした。ネットワークを確認してください。")
        elif isinstance(ex, anthropic.APIStatusError):
            st.error(f"API エラー ({ex.status_code}): {ex.message}")
        else:
            st.exception(ex)
        st.stop()

    if done is None:
        status.update(label="レポートを取得できませんでした", state="error")
        st.stop()
    u = done.usage
    status.update(label=f"完了 (Web 検索 {u['web_search_requests']} 回 / 入力 {u['input_tokens']:,}・"
                        f"出力 {u['output_tokens']:,} トークン)", state="complete", expanded=False)
    full = ai_analyst.format_report(req, done)
    report_box.markdown(done.report)
    if done.sources:
        with st.expander(f"検索で取得したページ ({len(done.sources)} 件)"):
            st.markdown("\n".join(f"- [{t}]({u})" for t, u in done.sources))
    if save:
        path = ai_analyst.save_report(full, req.race_name, REPORT_DIR)
        st.success(f"保存しました: {path}")
    st.download_button("レポートをダウンロード (.md)", full.encode("utf-8"),
                       file_name=f"{req.race_name}_予想.md", mime="text/markdown")

elif chosen != "—":
    path = REPORT_DIR / chosen
    content = path.read_text(encoding="utf-8")
    st.markdown(content)
    st.download_button("ダウンロード (.md)", content.encode("utf-8"), file_name=chosen, mime="text/markdown")
