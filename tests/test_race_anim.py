import json

import numpy as np
import pandas as pd
import pytest

from keiba import race_anim


def _race(n=10, finished=True, seed=0):
    rng = np.random.default_rng(seed)
    total = 96 + np.sort(rng.exponential(0.3, n).cumsum())
    return pd.DataFrame({
        "race_id": ["R1"] * n,
        "course": ["東京"] * n, "race_number": [11] * n, "surface": ["芝"] * n, "distance": [1600] * n,
        "track_condition": ["良"] * n, "race_class": ["G1"] * n,
        "horse_number": np.arange(1, n + 1), "frame_number": [(i // 2) + 1 for i in range(n)],
        "horse_name": [f"テスト{i}" for i in range(n)],
        "odds": rng.uniform(2, 50, n),
        "mark": ["◎", "○", "▲", "△", "△"] + [""] * (n - 5),
        "stake": [0.0] * (n - 1) + [300.0],
        "time_sec": total if finished else np.nan,
        "last_3f": rng.uniform(33.5, 35.5, n) if finished else np.nan,
        "avg_last3f_rank_ratio_5": rng.uniform(0, 1, n),
    })


@pytest.mark.parametrize("mode", ["simulation", "replay"])
def test_script_is_physically_sane(mode):
    race = _race()
    if mode == "simulation":
        s = race_anim.simulate_race(race, np.full(len(race), 1 / len(race)), seed=3)
    else:
        s = race_anim.replay_race(race)
    P = np.array(s["positions"])
    assert P.shape[0] == len(race)
    assert (np.diff(P, axis=1) >= -1e-6).all()            # 後ろに戻らない
    assert (np.diff(P, axis=1) / s["dt"]).max() < 20.5    # 速すぎない
    assert np.allclose(P[:, -1], 1600, atol=41)            # 全馬ゴールして止まる
    # ゴールした順 = 台本のタイム順
    t_finish = np.array([np.argmax(p >= 1600) for p in P])
    times = np.array([h["time"] for h in s["horses"]])
    assert (np.argsort(t_finish, kind="stable")[:3] == np.argsort(times, kind="stable")[:3]).all()
    assert s["left_handed"] is True                        # 東京は左回り
    assert s["events"][0]["t"] == 0 and s["events"][-1].get("final")
    assert sorted(h["style"] for h in s["horses"]).count("逃げ") == 1


def test_replay_matches_actual_order():
    race = _race()
    s = race_anim.replay_race(race)
    by_time = [h["num"] for h in sorted(s["horses"], key=lambda h: h["time"])]
    assert by_time == list(race.sort_values("time_sec")["horse_number"])
    assert f"1着は{by_time[0]}番" in s["events"][-1]["text"]


def test_replay_needs_results():
    with pytest.raises(ValueError):
        race_anim.replay_race(_race(finished=False))


def test_simulation_follows_win_prob():
    p = np.array([0.6, 0.3, 0.1])
    rng = np.random.default_rng(0)
    wins = np.bincount([np.argmin(race_anim.sample_finish_order(p, rng)) for _ in range(4000)], minlength=3)
    assert np.allclose(wins / 4000, p, atol=0.03)


def test_simulation_is_reproducible_by_seed():
    race = _race()
    p = np.linspace(1, 2, len(race)); p /= p.sum()
    a = race_anim.simulate_race(race, p, seed=5)
    b = race_anim.simulate_race(race, p, seed=5)
    c = race_anim.simulate_race(race, p, seed=6)
    assert a["positions"] == b["positions"] and a["positions"] != c["positions"]


@pytest.mark.parametrize("meters,text", [
    (0.1, "ハナ差"), (1.0, "クビ差"), (1.4, "半馬身"), (2.4, "1馬身"), (3.6, "1馬身半"), (30, "大差"),
])
def test_margin_text(meters, text):
    assert race_anim.margin_text(meters) == text
    assert race_anim.gap_phrase(meters).endswith("差")


def test_render_html_embeds_data_safely():
    race = _race()
    race.loc[0, "horse_name"] = "</script><b>"
    html = race_anim.render_html(race_anim.replay_race(race))
    assert "__RACE_DATA__" not in html
    data = html.split("const RACE = ", 1)[1].split(";\nconst H", 1)[0]
    assert "</script>" not in data
    assert json.loads(data)["horses"][0]["name"] == "</script><b>"
