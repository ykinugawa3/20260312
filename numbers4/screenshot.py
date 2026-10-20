"""抽せん結果のスクリーンショット (またはコピーしたテキスト) を Claude API で読み取る.

結果ページの画像を Claude に渡し、表を行ごとの JSON (numbers4.db.DRAW_COLUMNS と同じ列) で受け取る。
1 桁の読み違いが別の番号になってしまうため、既定では同じ画像を 2 回読んで食い違いを洗い出す
(compare_readings)。読み取った行は numbers4.validate でチェックし、人が確認してから保存する。

API キーは環境変数 ANTHROPIC_API_KEY (または `ant auth login`) から読む。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import pandas as pd

from numbers4 import db

MODEL = "claude-opus-5-5"
EFFORT = "medium"

_INT_OR_NULL = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "draw_no": {"type": "integer", "description": "回号 (第6800回 → 6800)"},
        "date": {"type": "string", "description": "抽せん日 YYYY-MM-DD"},
        "number": {"type": "string", "description": "ナンバーズ4 の当せん番号 4 桁 (先頭の 0 も残す)"},
        **{col: _INT_OR_NULL for col in db.OPTIONAL_COLUMNS},
    },
    "required": db.DRAW_COLUMNS,
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {"type": "array", "items": ROW_SCHEMA},
        "notes": {"type": "string", "description": "読みにくかった箇所・省いた行など. なければ空文字"},
    },
    "required": ["rows", "notes"],
    "additionalProperties": False,
}

INSTRUCTIONS = """\
これは宝くじ「ナンバーズ」の抽せん結果ページです。ナンバーズ4 の結果を 1 回 = 1 行 として書き起こしてください。

- draw_no: 回号の数字だけ (例: 「第6800回」→ 6800)
- date: 抽せん日を YYYY-MM-DD で (和暦・曜日表記も西暦に直す)
- number: ナンバーズ4 の当せん番号 4 桁を文字列で。先頭の 0 も残す (例: "0123")。
  ナンバーズ3 (3 桁) の番号は書かない
- 口数・当せん金・販売実績額 (円) は数字だけを整数で。ストレート / ボックス / セット(ストレート) /
  セット(ボックス) を取り違えないこと。載っていない項目や「該当なし」は null
- 見えている文字をそのまま写す。推測で埋めない。画像の端で切れていて読めない行は書かず、notes にその旨を書く
- ナンバーズ4 の結果が無い画像なら rows は空にする
"""


class ReadError(RuntimeError):
    pass


@dataclass
class Reading:
    rows: pd.DataFrame  # 列は db.DRAW_COLUMNS (値は読み取ったまま. 検証前)
    notes: str


def _client():
    import anthropic

    return anthropic.Anthropic()


def _request(content: list[dict], client=None, model: str = MODEL) -> Reading:
    client = client or _client()
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        # 拒否されたときはサーバー側で既定の代替モデルに切り替える
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise ReadError("読み取りを断られました。別の画像で試してください")
    if response.stop_reason == "max_tokens":
        raise ReadError("出力が長すぎて途中で切れました。画像を分けて読み取ってください")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ReadError("読み取り結果が空でした")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ReadError(f"読み取り結果を解釈できませんでした: {e}") from e
    rows = pd.DataFrame(data.get("rows", []), columns=db.DRAW_COLUMNS)
    rows["number"] = rows["number"].astype("string")
    return Reading(rows=rows, notes=data.get("notes", ""))


def read_image(image: bytes, media_type: str, client=None, model: str = MODEL) -> Reading:
    """画像 (PNG / JPEG / WebP / GIF) を読み取る."""
    data = base64.standard_b64encode(image).decode("ascii")
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
        {"type": "text", "text": INSTRUCTIONS},
    ]
    return _request(content, client, model)


def read_text(text: str, client=None, model: str = MODEL) -> Reading:
    """結果ページからコピーしたテキストを読み取る (画像より読み違いが起きにくい)."""
    content = [
        {"type": "text", "text": f"<page>\n{text}\n</page>"},
        {"type": "text", "text": INSTRUCTIONS.replace("抽せん結果ページです", "抽せん結果ページからコピーした文字です")},
    ]
    return _request(content, client, model)


def _same(a: object, b: object) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return str(a) == str(b)


def compare_readings(first: pd.DataFrame, second: pd.DataFrame) -> pd.DataFrame:
    """2 回の読み取りで値が食い違った箇所 (回号, 項目, 1 回目, 2 回目) の一覧."""
    a = first.drop_duplicates("draw_no").set_index("draw_no")
    b = second.drop_duplicates("draw_no").set_index("draw_no")
    diffs = []
    for no in sorted(set(a.index) | set(b.index), key=lambda x: (pd.isna(x), x)):
        if no not in a.index or no not in b.index:
            diffs.append({"draw_no": no, "column": "(行)", "first": "あり" if no in a.index else "なし",
                          "second": "あり" if no in b.index else "なし"})
            continue
        for col in db.DRAW_COLUMNS[1:]:
            if not _same(a.at[no, col], b.at[no, col]):
                diffs.append({"draw_no": no, "column": col, "first": a.at[no, col], "second": b.at[no, col]})
    return pd.DataFrame(diffs, columns=["draw_no", "column", "first", "second"])
