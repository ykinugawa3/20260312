import random
from collections import deque

import pytest

from sengoku import data
from sengoku.battle import fight
from sengoku.engine import COMMAND_COST, CommandError, Game


def test_map_is_connected_and_consistent():
    names = {p[0] for p in data.PROVINCES}
    assert len(names) == len(data.PROVINCES) == 65
    for a, bs in data.ADJACENCY.items():
        assert a in names and set(bs) <= names and a not in bs
    g = Game("織田", seed=0)
    seen, queue = {"尾張"}, deque(["尾張"])
    while queue:
        for n in g.adj[queue.popleft()] - seen:
            seen.add(n)
            queue.append(n)
    assert seen == names


def test_scenario_data_is_consistent():
    owned = [p for c in data.CLANS for p in c[2]]
    assert len(owned) == len(set(owned))
    g = Game("織田", seed=0)
    for clan in g.clans.values():
        leader = g.generals[clan.leader]
        assert leader.clan == clan.name
        assert g.provinces[leader.province].owner == clan.name
    assert 50 <= len(g.generals) <= 60


def test_domestic_commands_change_province_and_cost_gold():
    g = Game("織田", seed=1)
    owari = g.provinces["尾張"]
    gold, farm = g.clans["織田"].gold, owari.farm
    g.develop("丹羽長秀")
    assert owari.farm > farm
    assert g.clans["織田"].gold == gold - COMMAND_COST
    with pytest.raises(CommandError):
        g.develop("丹羽長秀")  # 1季節に1回まで
    troops = owari.troops
    g.recruit("木下藤吉郎")
    assert owari.troops > troops


def test_attack_resolves_at_end_of_turn():
    g = Game("織田", seed=2)
    g.attack("柴田勝家", "三河", 3000)
    assert g.provinces["尾張"].troops == 57 * 80 - 3000
    assert g.generals["柴田勝家"].province is None
    report = g.end_turn()
    battle = next(b for b in report.battles if b.att_general == "柴田勝家")
    assert battle.province == "三河"
    assert g.generals["柴田勝家"].province in {"三河", "尾張"}
    assert not g.armies


def test_cannot_attack_snow_country_in_winter():
    g = Game("長尾", seed=0)
    g.turn = 3
    assert g.attack_targets("越後") == []
    with pytest.raises(CommandError):
        g.attack("柿崎景家", "越中", 1000)


def test_castle_favours_defender():
    wins = sum(fight(3000, 70, 3000, 70, 800, random.Random(s)).attacker_won for s in range(200))
    assert wins < 40
    wins = sum(fight(9000, 70, 3000, 70, 0, random.Random(s)).attacker_won for s in range(200))
    assert wins > 190


def test_same_seed_replays_same_game():
    def play(seed):
        g = Game("武田", seed=seed)
        for _ in range(8):
            g.delegate()
            g.end_turn()
        return {p.name: (p.owner, p.troops) for p in g.provinces.values()}

    assert play(5) == play(5)


@pytest.mark.parametrize("seed", range(3))
def test_full_game_keeps_invariants(seed):
    g = Game("織田", seed=seed)
    while g.status == "playing":
        g.delegate()
        g.end_turn()
        alive = {c.name for c in g.alive_clans()}
        for p in g.provinces.values():
            assert p.troops >= 0 and 0 <= p.farm <= p.farm_max and p.owner in alive | {None}
        for gen in g.generals.values():
            if gen.clan is not None:
                assert gen.clan in alive
                assert g.provinces[gen.province].owner == gen.clan
        for c in g.alive_clans():
            assert c.gold >= 0 and c.food >= 0
            assert g.generals[c.leader].clan == c.name
    assert g.turn <= data.TOTAL_TURNS
    assert g.status in {"won", "lost"} and g.result
