"""keiba.ai_analyst のテスト (API は呼ばず、偽のクライアントで流れを確認する)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace as NS

import pytest

from keiba import ai_analyst
from keiba.ai_analyst import JST, AnalysisRequest


def test_master_prompt_has_all_sections():
    text = ai_analyst.load_master_prompt()
    for n in range(1, 19):
        assert f"# {n}．" in text
    for n in range(1, 11):
        assert f"【{n}】" in text


def test_user_message():
    req = AnalysisRequest(race_name=" ジャパンカップ ", notes="東京11R",
                          now=datetime(2026, 11, 9, 12, 0, tzinfo=JST))
    msg = ai_analyst.build_user_message(req)
    assert "レース名：ジャパンカップ" in msg
    assert "次に開催" in msg
    assert "重視する方針：的中率最優先" in msg
    assert "東京11R" in msg
    assert "2026年11月09日 12:00" in msg


class FakeStream:
    def __init__(self, events, message):
        self._events, self._message = events, message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._message


def _usage(i, o, searches):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=0,
              server_tool_use=NS(web_search_requests=searches))


class FakeClient:
    """1 回目は検索して pause_turn、2 回目でレポートを返す."""

    def __init__(self):
        self.calls = []
        search = NS(type="server_tool_use", name="web_search", input={"query": "ジャパンカップ 出馬表"})
        result = NS(type="web_search_tool_result",
                    content=[NS(url="https://www.jra.go.jp/x", title="JRA 出馬表")])
        text = NS(type="text", text="【1】レース基本情報", citations=[NS(url="https://n.example/y", title="N")])
        self.turns = [
            FakeStream([NS(type="content_block_stop", content_block=search)],
                       NS(stop_reason="pause_turn", content=[search, result], usage=_usage(100, 10, 1))),
            FakeStream([NS(type="text", text="【1】"), NS(type="text", text="レース基本情報")],
                       NS(stop_reason="end_turn", content=[text], usage=_usage(200, 50, 0))),
        ]
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return self.turns[len(self.calls) - 1]


def test_stream_analysis_handles_pause_turn_and_collects_sources(tmp_path):
    client = FakeClient()
    req = AnalysisRequest(race_name="ジャパンカップ")
    events = list(ai_analyst.stream_analysis(req, client=client))
    kinds = [e.kind for e in events]
    assert kinds[0] == "search" and events[0].text == "ジャパンカップ 出馬表"
    assert "info" in kinds and kinds[-1] == "done"

    done = events[-1]
    assert done.report == "【1】レース基本情報"
    assert ("JRA 出馬表", "https://www.jra.go.jp/x") in done.sources
    assert ("N", "https://n.example/y") in done.sources
    assert done.usage == {"input_tokens": 300, "output_tokens": 60, "web_search_requests": 1}

    # 2 回目のリクエストは 1 回目の応答を assistant として付けて再送している
    assert len(client.calls) == 2
    second = client.calls[1]["messages"]
    assert second[-1]["role"] == "assistant"
    assert client.calls[0]["tools"][0]["type"] == "web_search_20260209"

    text = ai_analyst.format_report(req, done)
    path = ai_analyst.save_report(text, "ジャパン/カップ", tmp_path)
    assert path.exists() and "/" not in path.name
    assert "https://www.jra.go.jp/x" in path.read_text(encoding="utf-8")


def test_validation():
    with pytest.raises(ValueError):
        list(ai_analyst.stream_analysis(AnalysisRequest(race_name=" "), client=object()))
    with pytest.raises(ValueError):
        list(ai_analyst.stream_analysis(AnalysisRequest(race_name="x", effort="huge"), client=object()))
