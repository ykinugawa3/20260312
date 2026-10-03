"""乱数性チェックと出目分析.

乱数性チェック: 抽せん結果が「各桁 0〜9 が等確率・各回独立」という前提と矛盾しないかを
カイ二乗検定で確かめる。
出目分析: ホット / コールド数字や出現間隔などの集計。抽せんは毎回独立なので、
これらは次回の当選確率に影響しない (娯楽として表示する)。
"""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd
from scipy import stats

POSITIONS = ["千の位", "百の位", "十の位", "一の位"]
ALPHA = 0.01  # 乱数性チェックの有意水準 (検定の数で割って使う)
MIN_EXPECTED = 5  # カイ二乗検定で各区分に必要な期待度数

# 数字の重なり方による型. 値は (ボックスの並べ替え通り数, 0000〜9999 のうちその型の個数)
PATTERNS = {
    "シングル": (24, 5040),     # 1234: 4 つとも違う
    "ダブル": (12, 4320),       # 1123: 2 つ同じ
    "ダブルダブル": (6, 270),   # 1122: 2 つ同じが 2 組
    "トリプル": (4, 360),       # 1112: 3 つ同じ
    "クアッド": (1, 10),        # 1111: ゾロ目 (ボックスは買えない)
}
_PATTERN_BY_COUNTS = {
    (1, 1, 1, 1): "シングル", (2, 1, 1): "ダブル", (2, 2): "ダブルダブル", (3, 1): "トリプル", (4,): "クアッド",
}
# 前回と同じ位置に同じ数字が 1 つ以上出る確率
CARRY_PROB = 1 - 0.9 ** 4

DISCLAIMER = "※ 抽せんは毎回独立です。過去の出目は次回の当選確率に影響しません (どの数字も 1/10,000)"


def digits(draws: pd.DataFrame) -> np.ndarray:
    """(回数, 4) の整数配列."""
    if draws.empty:
        return np.zeros((0, 4), dtype=int)
    return np.array([[int(c) for c in n] for n in draws["number"]], dtype=int)


def pattern_of(number: str) -> str:
    counts = tuple(sorted(pd.Series(list(number)).value_counts(), reverse=True))
    return _PATTERN_BY_COUNTS[counts]


def box_key(number: str) -> str:
    return "".join(sorted(number))


def _sum_distribution() -> pd.Series:
    """4 桁の合計 (0〜36) の理論確率."""
    sums = [sum(t) for t in product(range(10), repeat=4)]
    return pd.Series(sums).value_counts(normalize=True).sort_index()


def _merge_small_bins(observed: np.ndarray, expected: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """期待度数が MIN_EXPECTED 未満の区分を隣と合わせる (区分は順序付きの前提)."""
    obs, exp = list(map(float, observed)), list(map(float, expected))
    while len(exp) > 2 and min(exp) < MIN_EXPECTED:
        i = int(np.argmin(exp))
        if i == 0:
            j = 1
        elif i == len(exp) - 1:
            j = i - 1
        else:
            j = i - 1 if exp[i - 1] < exp[i + 1] else i + 1
        lo, hi = sorted((i, j))
        obs[lo] += obs.pop(hi)
        exp[lo] += exp.pop(hi)
    return np.array(obs), np.array(exp)


def _goodness_of_fit(name: str, detail: str, observed: np.ndarray, probs: np.ndarray,
                     merge: bool = False) -> dict:
    n = int(observed.sum())
    expected = probs * n
    if merge:
        observed, expected = _merge_small_bins(observed, expected)
    row = {"検定": name, "内容": detail, "回数": n, "統計量": np.nan, "自由度": len(expected) - 1, "p値": np.nan}
    if n == 0 or expected.min() < MIN_EXPECTED:
        return row
    chi2, p = stats.chisquare(observed, expected)
    return row | {"統計量": chi2, "p値": p}


def _independence(name: str, detail: str, prev: np.ndarray, curr: np.ndarray) -> dict:
    """前回の数字と今回の数字の 10×10 分割表で独立性を検定."""
    table = np.zeros((10, 10))
    np.add.at(table, (prev, curr), 1)
    row = {"検定": name, "内容": detail, "回数": len(prev), "統計量": np.nan, "自由度": 81, "p値": np.nan}
    if len(prev) == 0 or (table.sum(1)[:, None] * table.sum(0)[None, :] / len(prev)).min() < MIN_EXPECTED:
        return row
    chi2, p, dof, _ = stats.chi2_contingency(table, correction=False)
    return row | {"統計量": chi2, "自由度": dof, "p値": p}


def randomness_tests(draws: pd.DataFrame) -> pd.DataFrame:
    """乱数性チェックの結果表. 判定は検定の数で補正 (ボンフェローニ) した有意水準で行う."""
    d = digits(draws)
    uniform10 = np.full(10, 0.1)
    rows = []
    for i, pos in enumerate(POSITIONS):
        obs = np.bincount(d[:, i], minlength=10)
        rows.append(_goodness_of_fit("数字の出現回数", pos, obs, uniform10))
    rows.append(_goodness_of_fit("数字の出現回数", "4 桁まとめて", np.bincount(d.ravel(), minlength=10), uniform10))

    pats = draws["number"].map(pattern_of)
    names = ["クアッド", "トリプル", "ダブルダブル", "ダブル", "シングル"]  # 少ない順に並べて小さい区分をまとめる
    obs = np.array([(pats == k).sum() for k in names])
    probs = np.array([PATTERNS[k][1] / 10_000 for k in names])
    rows.append(_goodness_of_fit("型の分布", "シングル / ダブル / …", obs, probs, merge=True))

    dist = _sum_distribution()
    obs = np.bincount(d.sum(axis=1), minlength=37) if len(d) else np.zeros(37)
    rows.append(_goodness_of_fit("合計値の分布", "4 桁の合計 0〜36", obs, dist.reindex(range(37)).to_numpy(),
                                 merge=True))

    # 回号が連続している組だけで「前回 → 今回」の独立性を見る (データ欠けの回をまたがない)
    consecutive = np.diff(draws["draw_no"].to_numpy()) == 1
    for i, pos in enumerate(POSITIONS):
        rows.append(_independence("前回との独立性", pos, d[:-1][consecutive, i], d[1:][consecutive, i]))

    result = pd.DataFrame(rows)
    n_tests = len(result)
    threshold = ALPHA / n_tests
    result["判定"] = np.select(
        [result["p値"].isna(), result["p値"] < threshold], ["データ不足", "偏りの疑い"], "問題なし"
    )
    result.attrs["threshold"] = threshold
    return result


def summarize_tests(result: pd.DataFrame) -> str:
    threshold = result.attrs.get("threshold", ALPHA / len(result))
    n_bad = int((result["判定"] == "偏りの疑い").sum())
    n_ok = int((result["判定"] == "問題なし").sum())
    if n_ok + n_bad == 0:
        return "データが少なすぎて検定できません (目安: 500 回以上)"
    if n_bad:
        return (f"{n_bad} 件の検定で偏りの疑いがあります (p < {threshold:.4f})。"
                "データの取り込み誤り (回号・番号のずれ) がないかも確認してください")
    n_skip = len(result) - n_ok
    skipped = f", {n_skip} 件はデータ不足で未実施" if n_skip else ""
    return (f"偏りは見られません: 抽せん結果は一様な乱数と矛盾しません "
            f"({n_ok} 件の検定{skipped}, 判定基準 p < {threshold:.4f})")


def position_counts(draws: pd.DataFrame) -> pd.DataFrame:
    """行 = 数字 0〜9, 列 = 桁 の出現回数."""
    d = digits(draws)
    return pd.DataFrame(
        {pos: np.bincount(d[:, i], minlength=10) for i, pos in enumerate(POSITIONS)},
        index=pd.Index(range(10), name="数字"),
    )


def current_gaps(draws: pd.DataFrame) -> pd.DataFrame:
    """各桁の各数字が、最後に出てから何回出ていないか (0 = 直近の回に出た. 一度も出ていなければ NaN)."""
    d = digits(draws)
    n = len(d)
    gaps = pd.DataFrame(np.nan, index=pd.Index(range(10), name="数字"), columns=POSITIONS)
    for i, pos in enumerate(POSITIONS):
        for digit in range(10):
            hits = np.flatnonzero(d[:, i] == digit)
            if len(hits):
                gaps.loc[digit, pos] = n - 1 - hits[-1]
    return gaps


def hot_cold(draws: pd.DataFrame, last: int = 50, k: int = 3) -> pd.DataFrame:
    """直近 last 回で各桁によく出た数字 (ホット) / あまり出ていない数字 (コールド) を k 個ずつ."""
    counts = position_counts(draws.tail(last))
    rows = []
    for pos in POSITIONS:
        # 回数が同じなら数字の小さい順にそろえる
        hot = counts[pos].sort_values(ascending=False, kind="stable").head(k)
        cold = counts[pos].sort_values(ascending=True, kind="stable").head(k)
        rows.append({
            "桁": pos,
            "ホット": [(int(d), int(c)) for d, c in hot.items()],
            "コールド": [(int(d), int(c)) for d, c in cold.items()],
        })
    return pd.DataFrame(rows)


def pattern_table(draws: pd.DataFrame) -> pd.DataFrame:
    pats = draws["number"].map(pattern_of)
    n = max(len(draws), 1)
    return pd.DataFrame([
        {"型": k, "例": ex, "ボックス通り数": combos, "回数": int((pats == k).sum()),
         "割合": (pats == k).sum() / n, "理論値": count / 10_000}
        for (k, (combos, count)), ex in zip(PATTERNS.items(), ["1234", "1123", "1122", "1112", "1111"])
    ])


def carry_rate(draws: pd.DataFrame) -> tuple[float, int]:
    """前回と同じ位置に同じ数字が 1 つ以上出た (引っ張り) 回の割合と、対象の回数."""
    d = digits(draws)
    consecutive = np.diff(draws["draw_no"].to_numpy()) == 1
    same = (d[1:] == d[:-1]).any(axis=1)[consecutive]
    return (float(same.mean()) if len(same) else np.nan), int(len(same))


def lookup(draws: pd.DataFrame, number: str) -> dict:
    """数字を調べる: ストレート / ボックスでの過去の当選回など."""
    number = number.zfill(4)
    if len(number) != 4 or not number.isdigit():
        raise ValueError(f"4 桁の数字を指定してください: {number}")
    pattern = pattern_of(number)
    straight = draws[draws["number"] == number]
    box = draws[(draws["number"].map(box_key) == box_key(number)) & (draws["number"] != number)]
    last_seen = draws.index.get_loc(straight.index[-1]) if len(straight) else None
    return {
        "number": number,
        "pattern": pattern,
        "box_combinations": PATTERNS[pattern][0],
        "box_prob": PATTERNS[pattern][0] / 10_000,
        "n_draws": len(draws),
        "straight_hits": straight,
        "box_hits": box,
        "draws_since_straight": None if last_seen is None else len(draws) - 1 - last_seen,
    }
