import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from numbers4 import db, importer, screenshot, validate


def _row(no, date, number, **extra):
    row = {c: None for c in db.DRAW_COLUMNS} | {"draw_no": no, "date": date, "number": number}
    return row | extra


class FakeClient:
    """client.beta.messages.create だけを持つ偽物. 呼ばれるたびに responses を順に返す."""

    def __init__(self, *payloads, stop_reason="end_turn"):
        self.payloads = list(payloads)
        self.stop_reason = stop_reason
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        text = json.dumps(self.payloads.pop(0), ensure_ascii=False)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)])


GOOD = {"rows": [_row(6800, "2026-10-01", "0123", straight_payout=1013700, box_payout=37800),
                 _row(6801, "2026-10-02", "4455")], "notes": ""}


def test_read_image_request_and_result():
    client = FakeClient(GOOD)
    reading = screenshot.read_image(b"\x89PNG", "image/png", client=client)
    assert reading.rows["number"].tolist() == ["0123", "4455"]
    assert list(reading.rows.columns) == db.DRAW_COLUMNS
    call = client.calls[0]
    assert call["model"] == screenshot.MODEL
    assert call["output_config"]["format"]["schema"] == screenshot.OUTPUT_SCHEMA
    image = call["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"


def test_read_text_sends_text():
    client = FakeClient(GOOD)
    screenshot.read_text("第6800回 2026/10/01 0123", client=client)
    assert "第6800回" in client.calls[0]["messages"][0]["content"][0]["text"]


@pytest.mark.parametrize("stop_reason, message", [("refusal", "断られ"), ("max_tokens", "途中で切れ")])
def test_read_errors(stop_reason, message):
    with pytest.raises(screenshot.ReadError, match=message):
        screenshot.read_image(b"x", "image/png", client=FakeClient(GOOD, stop_reason=stop_reason))


def test_schema_requires_every_column():
    assert set(screenshot.ROW_SCHEMA["required"]) == set(screenshot.ROW_SCHEMA["properties"]) == set(db.DRAW_COLUMNS)


def test_compare_readings():
    a = pd.DataFrame([_row(1, "2026-10-01", "0123", straight_payout=900000), _row(2, "2026-10-02", "4455")])
    b = pd.DataFrame([_row(1, "2026-10-01", "0128", straight_payout=900000), _row(3, "2026-10-05", "1111")])
    diffs = screenshot.compare_readings(a, b)
    assert diffs[diffs["column"] == "number"][["draw_no", "first", "second"]].values.tolist() == [[1, "0123", "0128"]]
    assert set(diffs[diffs["column"] == "(行)"]["draw_no"]) == {2, 3}
    assert screenshot.compare_readings(a, a).empty
    issues = validate.mismatch_issues(diffs)
    assert (issues["level"] == validate.WARNING).all() and len(issues) == len(diffs)


def _messages(issues, no):
    return issues[issues["draw_no"] == no]["message"].tolist()


def test_check_clean_rows():
    rows = pd.DataFrame(GOOD["rows"])
    assert validate.check(rows).empty


def test_check_finds_problems():
    rows = pd.DataFrame([
        _row(1, "2026-10-01", "123"),                       # 3 桁 (先頭の 0 落ちは importer が直すので OK)
        _row(2, "2026-10-03", "12a4"),                      # 土曜 + 番号が読めない
        _row(4, "2026-10-05", "5555", box_payout=40000),    # 第3回が抜け + ゾロ目にボックス
        _row(5, "2026-10-05", "1234", straight_payout=30000, box_payout=40000),  # 日付が前回と同じ + 金額
        _row(5, "2026-10-06", "1234"),                      # 回号の重複
        _row(None, "", "9999"),
    ])
    issues = validate.check(rows)
    assert validate.has_errors(issues)
    assert _messages(issues, 1) == []
    assert any("土日" in m for m in _messages(issues, 2))
    assert any("4 桁" in m for m in _messages(issues, 2))
    assert any("第3回 が抜け" in m for m in _messages(issues, 4))
    assert any("ゾロ目" in m for m in _messages(issues, 4))
    m5 = _messages(issues, 5)
    assert any("重複" in m or "複数" in m for m in m5)
    assert any("抽せん日が前" in m for m in m5)
    assert any("ストレート以上" in m for m in m5) and any("範囲" in m for m in m5)
    nan_rows = issues[issues["draw_no"].isna()]
    assert any("回号が読めません" in m for m in nan_rows["message"])


def test_check_against_existing():
    existing = pd.DataFrame({"draw_no": [6800], "number": ["0123"]})
    rows = pd.DataFrame([_row(6800, "2026-10-01", "0128")])
    assert any("登録済みの番号 0123" in m for m in validate.check(rows, existing)["message"])


def test_sales_check():
    rows = pd.DataFrame([_row(1, "2026-10-01", "1234", straight_winners=500, straight_payout=900000,
                              sales=200_000_000)])
    assert any("販売実績額" in m for m in validate.check(rows)["message"])


def test_edited_strings_are_saved(tmp_path):
    # data_editor で書き換えた値は文字列や欠損が混ざる
    rows = pd.DataFrame([_row("6800", "2026/10/01", "0123", straight_payout="1,013,700", box_payout=pd.NA)])
    assert not validate.has_errors(validate.check(rows))
    path = tmp_path / "n.db"
    importer.import_frame(validate.to_import_frame(rows), path)
    saved = db.load_draws(path).iloc[0]
    assert saved["number"] == "0123" and saved["straight_payout"] == 1_013_700 and pd.isna(saved["box_payout"])


def test_app_flow(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    calls = []

    def fake_read_text(text, client=None, model=None):
        calls.append(text)
        rows = GOOD["rows"] if len(calls) == 1 else [{**GOOD["rows"][0], "number": "0128"}, GOOD["rows"][1]]
        return screenshot.Reading(rows=pd.DataFrame(rows, columns=db.DRAW_COLUMNS).astype({"number": "string"}),
                                  notes="")

    monkeypatch.setattr(screenshot, "read_text", fake_read_text)
    at = AppTest.from_file(str(Path(__file__).parent.parent / "numbers4_app.py"), default_timeout=30).run()
    at.sidebar.text_input[0].set_value(str(tmp_path / "n.db")).run()
    at.radio[0].set_value("ページの文字を貼り付け").run()
    at.text_area[0].set_value("第6800回 ...").run()
    at.button[0].click().run()
    assert not at.exception
    assert len(calls) == 2  # 2 回読み
    assert any("食い違い" in e.label for e in at.expander)
    assert "エラー 0 件 / 注意 1 件" in [m.value for m in at.markdown]
    save = next(b for b in at.button if "DB に保存" in b.label)
    save.click().run()
    assert not at.exception
    assert db.load_draws(tmp_path / "n.db")["number"].tolist() == ["0123", "4455"]
