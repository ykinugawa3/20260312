"""Claude + Web 検索による「全頭徹底分析」予想レポートの生成。

マスタープロンプト (keiba/prompts/master_prompt.md) をシステムプロンプトとして渡し、
Claude にWeb検索・Webページ取得をさせながら、指定レースの予想レポートを Markdown で書かせる。

使い方:
    for ev in stream_analysis(AnalysisRequest(race_name="ジャパンカップ")):
        ...  # ev.kind は "search" / "fetch" / "text" / "info" / "done"
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROMPT_PATH = Path(__file__).parent / "prompts" / "master_prompt.md"
DEFAULT_MODEL = "claude-opus-5-5"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "high"
POLICIES = ("的中率最優先", "的中率・回収率バランス", "回収率（期待値）重視")
JST = ZoneInfo("Asia/Tokyo")

# サーバー側ツール (Anthropic 側で実行される)。検索回数の上限はコスト管理のため。
MAX_SEARCHES = 30
MAX_FETCHES = 20
# サーバー側の検索ループが上限に達すると pause_turn で返るので、続きを依頼する回数の上限
MAX_CONTINUATIONS = 8
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def load_master_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


@dataclass
class AnalysisRequest:
    race_name: str
    year: str = ""  # 空なら「次回開催」
    policy: str = POLICIES[0]
    notes: str = ""  # 開催日・競馬場の指定や、利用者が把握している補足情報
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    now: datetime | None = None  # テスト用。None なら現在時刻 (JST)


@dataclass
class AnalysisEvent:
    kind: str  # "search" | "fetch" | "text" | "info" | "done"
    text: str = ""
    report: str = ""
    sources: list[tuple[str, str]] = field(default_factory=list)  # (title, url)
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None


def build_user_message(req: AnalysisRequest) -> str:
    """マスタープロンプト末尾の【予想するレース】に相当する部分。"""
    now = (req.now or datetime.now(JST)).astimezone(JST)
    year = req.year.strip() or "未指定（調査日時点で次に開催される該当レース）"
    lines = [
        "【予想するレース】",
        f"レース名：{req.race_name.strip()}",
        f"開催年：{year}",
        f"重視する方針：{req.policy}",
    ]
    if req.notes.strip():
        lines.append(f"補足（利用者からの指定・情報）：{req.notes.strip()}")
    lines += [
        "",
        f"調査実行日時：{now:%Y年%m月%d日 %H:%M}（日本時間）",
        "",
        "上記のレースについて、利用可能な最新情報を調査し、全頭分析から最終結論・具体的な買い目まで一括して実行してください。",
    ]
    return "\n".join(lines)


def _make_client(api_key: str | None = None):
    import anthropic

    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def _tools() -> list[dict]:
    return [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": MAX_SEARCHES,
            "user_location": {"type": "approximate", "country": "JP", "timezone": "Asia/Tokyo"},
        },
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": MAX_FETCHES},
    ]


def _block_get(block, key, default=None):
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _collect_sources(content, sources: dict[str, str]) -> None:
    """検索結果・引用から (url -> title) を集める。"""
    for block in content:
        btype = _block_get(block, "type")
        if btype == "web_search_tool_result":
            results = _block_get(block, "content")
            if isinstance(results, list):  # エラー時は list ではなく error オブジェクト
                for r in results:
                    url = _block_get(r, "url")
                    if url:
                        sources.setdefault(url, _block_get(r, "title") or url)
        elif btype == "text":
            for c in _block_get(block, "citations") or []:
                url = _block_get(c, "url")
                if url:
                    sources.setdefault(url, _block_get(c, "title") or url)


def _tool_event(block) -> AnalysisEvent | None:
    if _block_get(block, "type") != "server_tool_use":
        return None
    name = _block_get(block, "name")
    inp = _block_get(block, "input") or {}
    if name == "web_search":
        return AnalysisEvent("search", text=str(inp.get("query", "")))
    if name == "web_fetch":
        return AnalysisEvent("fetch", text=str(inp.get("url", "")))
    return None


def stream_analysis(req: AnalysisRequest, client=None, api_key: str | None = None) -> Iterator[AnalysisEvent]:
    """予想レポートを生成しながら、進捗イベントを順に返す。最後は kind="done"。"""
    if not req.race_name.strip():
        raise ValueError("レース名を入力してください")
    if req.effort not in EFFORT_LEVELS:
        raise ValueError(f"effort は {EFFORT_LEVELS} のいずれか")
    client = client or _make_client(api_key)

    system = [{"type": "text", "text": load_master_prompt(), "cache_control": {"type": "ephemeral"}}]
    messages: list[dict] = [{"role": "user", "content": build_user_message(req)}]
    report_parts: list[str] = []
    sources: dict[str, str] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "web_search_requests": 0}
    stop_reason = None

    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(
            model=req.model,
            max_tokens=64000,
            system=system,
            messages=messages,
            tools=_tools(),
            thinking={"type": "adaptive"},
            output_config={"effort": req.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",  # 安全分類器による拒否時は推奨モデルで自動再実行
        ) as stream:
            for event in stream:
                etype = getattr(event, "type", None)
                if etype == "text":
                    yield AnalysisEvent("text", text=event.text)
                elif etype == "content_block_stop":
                    tool_ev = _tool_event(event.content_block)
                    if tool_ev:
                        yield tool_ev
            message = stream.get_final_message()

        stop_reason = message.stop_reason
        _collect_sources(message.content, sources)
        u = message.usage
        usage["input_tokens"] += (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        stu = getattr(u, "server_tool_use", None)
        usage["web_search_requests"] += getattr(stu, "web_search_requests", 0) or 0
        report_parts += [_block_get(b, "text") for b in message.content if _block_get(b, "type") == "text"]

        if stop_reason == "pause_turn":
            # サーバー側の検索ループが一時停止。応答をそのまま付けて再送すると続きから再開する。
            messages.append({"role": "assistant", "content": message.content})
            yield AnalysisEvent("info", text="調査を継続しています…")
            continue
        break

    report = "".join(p for p in report_parts if p).strip()
    if stop_reason == "refusal":
        report += "\n\n> ⚠️ モデルがこのリクエストへの回答を中止しました。"
    elif stop_reason == "max_tokens":
        report += "\n\n> ⚠️ 出力の上限に達したため、レポートが途中で切れています。"
    elif stop_reason == "pause_turn":
        report += "\n\n> ⚠️ 調査の継続回数の上限に達したため、レポートが未完成の可能性があります。"

    yield AnalysisEvent(
        "done",
        report=report,
        sources=[(title, url) for url, title in sources.items()],
        usage=usage,
        stop_reason=stop_reason,
    )


def format_report(req: AnalysisRequest, done: AnalysisEvent, generated_at: datetime | None = None) -> str:
    """保存用 Markdown (レポート本文 + 検索で参照した URL 一覧 + 注意書き)。"""
    at = (generated_at or datetime.now(JST)).astimezone(JST)
    head = (
        f"# {req.race_name} 予想レポート\n\n"
        f"- 生成日時: {at:%Y-%m-%d %H:%M} (JST)\n"
        f"- 開催年: {req.year or '次回開催'} / 方針: {req.policy} / モデル: {req.model} (effort={req.effort})\n\n"
        "> AI による調査・推定であり、的中を保証するものではありません。"
        "馬番・オッズなどは必ず公式発表で確認してください。\n\n---\n\n"
    )
    body = done.report
    if done.sources:
        body += "\n\n---\n\n## 検索で取得したページ (自動収集)\n\n"
        body += "\n".join(f"- [{t}]({u})" for t, u in done.sources)
    return head + body + "\n"


def save_report(text: str, race_name: str, out_dir: str | Path = "reports", now: datetime | None = None) -> Path:
    at = (now or datetime.now(JST)).astimezone(JST)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", race_name.strip())[:40] or "race"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{at:%Y%m%d_%H%M}_{safe}.md"
    path.write_text(text, encoding="utf-8")
    return path


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
