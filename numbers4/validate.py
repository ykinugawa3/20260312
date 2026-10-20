"""取り込み前のチェック (スクリーンショットの読み取り結果など、人が確認する前提のデータ向け).

importer.normalize はおかしな行があると例外にするが、ここでは行ごとに問題を一覧にして返す。
「エラー」が残っている間は保存できない。「注意」は読み違いの可能性があるので画像と見比べて確認する。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from numbers4 import analysis, db, importer

ERROR = "エラー"
WARNING = "注意"

COLUMN_LABELS = {
    "draw_no": "回号",
    "date": "抽せん日",
    "number": "当せん番号",
    "straight_winners": "ストレート口数",
    "straight_payout": "ストレート当せん金",
    "box_winners": "ボックス口数",
    "box_payout": "ボックス当せん金",
    "set_straight_winners": "セット(ストレート)口数",
    "set_straight_payout": "セット(ストレート)当せん金",
    "set_box_winners": "セット(ボックス)口数",
    "set_box_payout": "セット(ボックス)当せん金",
    "sales": "販売実績額",
}
# 当せん金の目安 (これを外れたら読み違いを疑う). 実績のストレートはおおむね数十万〜百数十万円
STRAIGHT_PAYOUT_RANGE = (100_000, 5_000_000)
BOX_PAYOUT_RANGE = (5_000, 1_500_000)


def to_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """編集途中の表 (文字列混じり) を DRAW_COLUMNS の型にそろえる. 読めない値は NaN / NaT."""
    out = pd.DataFrame(index=rows.index)
    for col in db.DRAW_COLUMNS:
        values = rows[col] if col in rows.columns else pd.Series(pd.NA, index=rows.index)
        if col == "date":
            out[col] = importer._to_date(values.fillna(""))
        elif col == "number":
            out[col] = importer._to_number(values.fillna("")).astype("string")
        else:
            out[col] = importer._to_int(values)
    return out


def check(rows: pd.DataFrame, existing: pd.DataFrame | None = None) -> pd.DataFrame:
    """問題の一覧 (列: level, draw_no, column, message). existing は DB に登録済みの回 (db.load_draws の結果)."""
    df = to_frame(rows)
    issues: list[dict] = []

    def add(level: str, no: object, col: str, message: str) -> None:
        issues.append({"level": level, "draw_no": no, "column": COLUMN_LABELS.get(col, col), "message": message})

    for _, r in df.iterrows():
        no = r["draw_no"]
        if pd.isna(no):
            add(ERROR, no, "draw_no", "回号が読めません")
        if pd.isna(r["date"]):
            add(ERROR, no, "date", "抽せん日が読めません")
        elif r["date"].weekday() >= 5:
            add(WARNING, no, "date", f"{r['date']:%Y-%m-%d} は土日です (抽せんは平日)")
        number = r["number"]
        if pd.isna(number) or not str(number).isdigit() or len(str(number)) != 4:
            add(ERROR, no, "number", f"当せん番号が 4 桁の数字ではありません: {number}")
            continue

        sp, bp = r["straight_payout"], r["box_payout"]
        if pd.notna(sp) and not STRAIGHT_PAYOUT_RANGE[0] <= sp <= STRAIGHT_PAYOUT_RANGE[1]:
            add(WARNING, no, "straight_payout", f"ストレート当せん金 {sp:,} 円は普段の範囲から外れています")
        if pd.notna(bp) and not BOX_PAYOUT_RANGE[0] <= bp <= BOX_PAYOUT_RANGE[1]:
            add(WARNING, no, "box_payout", f"ボックス当せん金 {bp:,} 円は普段の範囲から外れています")
        if pd.notna(sp) and pd.notna(bp) and bp >= sp:
            add(WARNING, no, "box_payout", "ボックスの当せん金がストレート以上です (列の取り違え?)")
        if analysis.pattern_of(str(number)) == "クアッド" and (pd.notna(bp) or pd.notna(r["box_winners"])):
            add(WARNING, no, "box_payout", "ゾロ目にはボックスがありません (列の取り違え?)")
        for kind in ("straight", "box", "set_straight", "set_box"):
            w, p = r[f"{kind}_winners"], r[f"{kind}_payout"]
            if pd.notna(w) and pd.notna(p) and pd.notna(r["sales"]) and w * p > r["sales"]:
                add(WARNING, no, f"{kind}_payout", "口数 × 当せん金 が販売実績額を超えています")

    valid = df.dropna(subset=["draw_no"])
    for no in valid.loc[valid["draw_no"].duplicated(), "draw_no"].unique():
        add(ERROR, no, "draw_no", "同じ回号が複数あります")

    ordered = valid.drop_duplicates("draw_no").sort_values("draw_no")
    nos = ordered["draw_no"].to_numpy(dtype=float)
    for prev, nxt in zip(nos[:-1], nos[1:]):
        if nxt - prev > 1:
            missing = f"第{int(prev) + 1}回" + (f"〜第{int(nxt) - 1}回" if nxt - prev > 2 else "")
            add(WARNING, int(nxt), "draw_no", f"{missing} が抜けています (画像の端で切れていませんか)")
    dates = ordered.dropna(subset=["date"])
    back = dates[dates["date"].diff() <= pd.Timedelta(0)]
    for no in back["draw_no"]:
        add(WARNING, no, "date", "前の回より抽せん日が前 (または同じ) です")

    if existing is not None and not existing.empty:
        known = existing.set_index("draw_no")["number"]
        for _, r in valid.iterrows():
            no = int(r["draw_no"])
            if no in known.index and pd.notna(r["number"]) and known[no] != r["number"]:
                add(WARNING, no, "number", f"登録済みの番号 {known[no]} と違います (保存すると上書きされます)")

    result = pd.DataFrame(issues, columns=["level", "draw_no", "column", "message"])
    order = {ERROR: 0, WARNING: 1}
    return result.sort_values(["draw_no", "level"], key=lambda s: s.map(order) if s.name == "level" else s,
                              na_position="first", kind="stable").reset_index(drop=True)


def mismatch_issues(diffs: pd.DataFrame) -> pd.DataFrame:
    """2 回読み取りの食い違い (screenshot.compare_readings の結果) を check と同じ形の一覧にする."""
    rows = []
    for _, d in diffs.iterrows():
        if d["column"] == "(行)":
            message = f"1 回目の読み取りでは{d['first']}・2 回目では{d['second']}"
            column = "回号"
        else:
            first = "空欄" if pd.isna(d["first"]) else d["first"]
            second = "空欄" if pd.isna(d["second"]) else d["second"]
            message = f"読み取りが食い違いました: 1 回目 {first} / 2 回目 {second}"
            column = COLUMN_LABELS.get(d["column"], d["column"])
        rows.append({"level": WARNING, "draw_no": d["draw_no"], "column": column, "message": message})
    return pd.DataFrame(rows, columns=["level", "draw_no", "column", "message"])


def has_errors(issues: pd.DataFrame) -> bool:
    return bool((issues["level"] == ERROR).any())


def to_import_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """保存用. check でエラーが無いことを確認してから使う."""
    df = to_frame(rows)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["number"] = df["number"].astype(str)
    return df.astype({c: object for c in db.OPTIONAL_COLUMNS}).replace({np.nan: None, pd.NA: None})
