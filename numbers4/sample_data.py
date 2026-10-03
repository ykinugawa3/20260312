"""動作確認用の合成抽せんデータ生成器.

当せん番号は本物と同じく 0000〜9999 の一様乱数 (各回独立)。
当選口数と当せん金は、Phase 2 の人気推定を試せるよう「人気のある数字ほど多く買われる」
簡易モデルで作る (ゾロ目・月日・連番・7 を含む数字が買われやすい)。値の大きさは実際の
ナンバーズ4 (ストレート平均 約 90 万円, 24 通りのボックス 約 3.7 万円) に近づけてあるが、
人気の強さは仮の値で、実データの傾向を表すものではない。
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

PRICE = 200          # 1 口の価格 (円)
PAYOUT_RATE = 0.45   # 還元率
MEAN_SALES = 2.0e8   # 1 回あたりの平均売上 (円)
STRAIGHT_SHARE = 0.45  # 売上のうちストレート / ボックスの割合 (残りはセット. 仮データでは作らない)
BOX_SHARE = 0.35
DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _is_month_day(n: str) -> bool:
    m, d = int(n[:2]), int(n[2:])
    return 1 <= m <= 12 and 1 <= d <= DAYS_IN_MONTH[m - 1]


def _is_sequence(n: str) -> bool:
    diffs = {int(b) - int(a) for a, b in zip(n, n[1:])}
    return diffs in ({1}, {-1})


def popularity_weight(n: str) -> float:
    """その数字がどれだけ買われやすいか (相対値)."""
    w = 1.0
    if len(set(n)) == 1:
        w += 6.0      # ゾロ目
    if _is_sequence(n):
        w += 4.0      # 連番
    if _is_month_day(n):
        w += 1.0      # 誕生日・記念日
    if n[:2] == n[2:]:
        w += 1.0      # 1212 のような繰り返し
    w += 0.3 * n.count("7")
    return w


@lru_cache(maxsize=1)
def _weights() -> tuple[np.ndarray, dict[str, float]]:
    numbers = [f"{i:04d}" for i in range(10_000)]
    w = np.array([popularity_weight(n) for n in numbers])
    w /= w.sum()
    box: dict[str, float] = {}
    for n, p in zip(numbers, w):
        key = "".join(sorted(n))
        box[key] = box.get(key, 0.0) + p
    return w, box


def _payout(pool: float, winners: int) -> float:
    # 当せん金は 1 口あたり 100 円未満切り捨てとして作る. 該当なしは NaN
    return np.floor(pool / winners / 100) * 100 if winners > 0 else np.nan


def generate(n_draws: int = 2000, start_date: str = "2018-01-01", first_draw_no: int = 4800,
             seed: int = 42) -> pd.DataFrame:
    """平日に 1 回ずつ抽せんした n_draws 回分の結果を返す (列は numbers4.db.DRAW_COLUMNS)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start_date, periods=n_draws)
    numbers = [f"{i:04d}" for i in rng.integers(0, 10_000, n_draws)]
    sales = np.round(MEAN_SALES * rng.lognormal(-0.02, 0.2, n_draws), -3)
    w, box_w = _weights()

    rows = []
    for no, date, n, s in zip(range(first_draw_no, first_draw_no + n_draws), dates, numbers, sales):
        straight_units = s * STRAIGHT_SHARE / PRICE
        box_units = s * BOX_SHARE / PRICE
        sw = int(rng.poisson(straight_units * w[int(n)]))
        bw = int(rng.poisson(box_units * box_w["".join(sorted(n))]))
        rows.append({
            "draw_no": no,
            "date": date.strftime("%Y-%m-%d"),
            "number": n,
            "straight_winners": sw,
            "straight_payout": _payout(s * STRAIGHT_SHARE * PAYOUT_RATE, sw),
            "box_winners": bw,
            "box_payout": _payout(s * BOX_SHARE * PAYOUT_RATE, bw),
            "set_straight_winners": None,
            "set_straight_payout": None,
            "set_box_winners": None,
            "set_box_payout": None,
            "sales": int(s),
        })
    return pd.DataFrame(rows)
