"""動作確認用の合成レースデータ生成器.

実データが無い環境でもパイプライン全体を試せるよう、
馬の潜在能力・距離/馬場適性・騎手/調教師の腕を持つ簡易シミュレーションでデータを作る。
市場 (オッズ) は潜在能力をノイズ付きでしか知らず、控除率 20% を反映する。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COURSES = ["東京", "中山", "阪神", "京都", "中京", "新潟", "福島", "小倉", "札幌", "函館"]
SURFACES = ["芝", "ダート"]
DISTANCES = {"芝": [1200, 1400, 1600, 1800, 2000, 2400], "ダート": [1200, 1400, 1700, 1800, 2100]}
CONDITIONS = ["良", "稍重", "重", "不良"]
CONDITION_P = [0.65, 0.2, 0.1, 0.05]
CLASSES = ["未勝利", "1勝", "2勝", "3勝", "OP"]
SEXES = ["牡", "牝", "セ"]
TAKEOUT = 0.8  # 単勝の払戻率


def generate(
    n_days: int = 200,
    races_per_day: int = 12,
    n_horses: int = 1500,
    n_jockeys: int = 80,
    n_trainers: int = 150,
    start_date: str = "2023-01-07",
    upcoming_days: int = 1,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(races, entries) を返す. 最後の upcoming_days 日は結果未確定 (出馬表のみ)."""
    rng = np.random.default_rng(seed)

    horses = pd.DataFrame({
        "horse_id": [f"H{i:05d}" for i in range(n_horses)],
        "horse_name": [f"サンプルホース{i}" for i in range(n_horses)],
        "ability": rng.normal(0, 1, n_horses),
        "turf_pref": rng.normal(0, 0.5, n_horses),       # 正: 芝向き
        "best_distance": rng.uniform(1200, 2400, n_horses),
        "sex": rng.choice(SEXES, n_horses, p=[0.55, 0.4, 0.05]),
        "birth_year": rng.integers(2018, 2021, n_horses),
        "base_weight": rng.normal(470, 25, n_horses),
        "trainer_id": [f"T{t:03d}" for t in rng.integers(0, n_trainers, n_horses)],
        "mud_pref": rng.normal(0, 0.4, n_horses),
    }).set_index("horse_id")
    jockey_skill = rng.normal(0, 0.35, n_jockeys)
    trainer_skill = rng.normal(0, 0.25, n_trainers)
    last_run = pd.Series(pd.Timestamp("2000-01-01"), index=horses.index)

    race_rows, entry_rows = [], []
    dates = pd.date_range(start_date, periods=n_days, freq="W-SAT")
    for d_idx, date in enumerate(dates):
        is_upcoming = d_idx >= n_days - upcoming_days
        day_courses = rng.choice(COURSES, 2, replace=False)
        for r in range(races_per_day):
            course = day_courses[r % 2]
            race_number = r // 2 + 1
            surface = rng.choice(SURFACES)
            distance = int(rng.choice(DISTANCES[surface]))
            cond = rng.choice(CONDITIONS, p=CONDITION_P)
            race_class = rng.choice(CLASSES, p=[0.35, 0.3, 0.15, 0.1, 0.1])
            race_id = f"{date:%Y%m%d}{COURSES.index(course):02d}{race_number:02d}"

            # 休養明けすぎない馬から出走馬を選ぶ
            rested = horses.index[(date - last_run).dt.days >= 21]
            n_runners = int(rng.integers(8, 17))
            runners = rng.choice(rested, n_runners, replace=False)
            last_run[runners] = date

            h = horses.loc[runners]
            jockeys = rng.choice(n_jockeys, n_runners, replace=False)
            trainers = h["trainer_id"].str[1:].astype(int).to_numpy()
            surf_sign = 1 if surface == "芝" else -1
            wet = CONDITIONS.index(cond) / 3
            strength = (
                h["ability"].to_numpy()
                + surf_sign * h["turf_pref"].to_numpy()
                - np.abs(h["best_distance"].to_numpy() - distance) / 600
                + wet * h["mud_pref"].to_numpy()
                + jockey_skill[jockeys]
                + trainer_skill[trainers]
            )
            weights = h["base_weight"].to_numpy() + rng.normal(0, 6, n_runners)
            perf = strength + rng.normal(0, 1.0, n_runners)
            order = (-perf).argsort().argsort() + 1

            base_time = distance / 16.5 + (1.5 if surface == "ダート" else 0) + wet
            time_sec = base_time - perf * 0.4 + rng.normal(0, 0.2, n_runners)
            last_3f = 35.5 - perf * 0.3 + rng.normal(0, 0.4, n_runners)

            # 市場の見積り: 真の強さにノイズを乗せたもの
            market = strength + rng.normal(0, 0.6, n_runners)
            p_market = np.exp(market * 1.3)
            p_market /= p_market.sum()
            odds = np.maximum(1.1, np.round(TAKEOUT / p_market, 1))
            popularity = odds.argsort().argsort() + 1

            race_rows.append({
                "race_id": race_id, "date": f"{date:%Y-%m-%d}", "course": course,
                "race_number": race_number, "surface": surface, "distance": distance,
                "track_condition": cond, "race_class": race_class,
            })
            numbers = rng.permutation(n_runners) + 1
            for i, hid in enumerate(runners):
                num = int(numbers[i])
                entry_rows.append({
                    "race_id": race_id,
                    "horse_id": hid,
                    "horse_name": h.at[hid, "horse_name"],
                    "jockey_id": f"J{jockeys[i]:03d}",
                    "trainer_id": h.at[hid, "trainer_id"],
                    "frame_number": _frame_number(num, n_runners),
                    "horse_number": num,
                    "sex": h.at[hid, "sex"],
                    "age": int(date.year - h.at[hid, "birth_year"]),
                    "weight_carried": 55.0 if h.at[hid, "sex"] != "牝" else 53.0,
                    "horse_weight": round(float(weights[i])),
                    "horse_weight_diff": round(float(rng.normal(0, 4))),
                    "odds": float(odds[i]),
                    "popularity": int(popularity[i]),
                    "finish_position": None if is_upcoming else int(order[i]),
                    "time_sec": None if is_upcoming else round(float(time_sec[i]), 1),
                    "last_3f": None if is_upcoming else round(float(last_3f[i]), 1),
                })
    return pd.DataFrame(race_rows), pd.DataFrame(entry_rows)


def _frame_number(horse_number: int, n_runners: int) -> int:
    """JRA 方式の枠番. 8 頭以下は馬番=枠番、それ以上は外枠から 2 頭ずつ入る."""
    if n_runners <= 8:
        return horse_number
    doubles = n_runners - 8  # 2 頭入る枠の数 (外側から)
    singles = 8 - doubles
    if horse_number <= singles:
        return horse_number
    return singles + (horse_number - singles + 1) // 2
