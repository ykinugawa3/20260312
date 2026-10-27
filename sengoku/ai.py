"""AI大名 (ルールベース).

国ごとに、未行動の武将を統率の高い順に使う。
1. 前線: 戦力比が「2.0 - 好戦度」以上の隣国があれば、最も有利な国へ兵の8割で出陣
2. 内地: 兵と武将を前線に近い隣の自国へ送る
3. 残りの武将: 前線なら徴兵・築城、内地なら開墾・商業のうち低い方
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import Clan, Game, General, Province

SEND_RATIO = 0.8
MIN_SEND = 300
FOOD_RESERVE_SEASONS = 2  # 出陣後も、この季節数ぶんの兵糧消費は残す


def take_turn(game: Game, clan_name: str) -> None:
    clan = game.clans[clan_name]
    if not clan.alive or game.status != "playing":
        return
    dist = game.front_distance(clan_name)
    for prov in sorted(game.owned(clan_name), key=lambda p: dist[p.name]):
        idle = sorted(game.idle_generals(prov.name), key=lambda g: -g.leadership)
        if idle and dist[prov.name] == 0 and _try_attack(game, clan, prov, idle[0]):
            idle.pop(0)
        if idle and dist[prov.name] > 0 and _try_forward(game, prov, idle[0], dist):
            idle.pop(0)
        for g in idle:
            _domestic(game, clan, prov, g, frontline=dist[prov.name] == 0)


def _try_attack(game: Game, clan: Clan, prov: Province, g: General) -> bool:
    send = int(prov.troops * SEND_RATIO)
    if send < MIN_SEND:
        return False
    targets = game.attack_targets(prov.name)
    if not targets:
        return False
    mine = send * (1 + g.leadership / 100)
    ratio, target = max((mine / max(game.defense_strength(t), 1.0), t) for t in targets)
    if ratio < 2.0 - clan.aggression:
        return False
    reserve = game.clan_troops(clan.name) * FOOD_RESERVE_SEASONS / 40
    if clan.food - game.march_food(send) < reserve:
        return False
    game.attack(g.name, target, send)
    return True


def _try_forward(game: Game, prov: Province, g: General, dist: dict[str, int]) -> bool:
    if prov.troops < 500 and len(game.idle_generals(prov.name)) < 2:
        return False
    closer = [n for n in game.neighbors(prov.name) if n in dist and dist[n] < dist[prov.name]]
    if not closer:
        return False
    dest = min(closer, key=lambda n: (dist[n], game.provinces[n].troops))
    game.move(g.name, dest, int(prov.troops * SEND_RATIO))
    return True


def _domestic(game: Game, clan: Clan, prov: Province, g: General, frontline: bool) -> None:
    from .engine import COMMAND_COST, RECRUIT_GOLD, CommandError

    try:
        amount = game.recruit_amount(g.name)
        if frontline and prov.troops < game.max_troops(prov.name) * 0.9 and amount > 0 \
                and clan.gold >= amount * RECRUIT_GOLD + 1:
            game.recruit(g.name)
        elif clan.gold < COMMAND_COST:
            return
        elif frontline and prov.defense < 500:
            game.fortify(g.name)
        elif prov.farm / prov.farm_max <= prov.commerce / prov.commerce_max and prov.farm < prov.farm_max:
            game.develop(g.name)
        elif prov.commerce < prov.commerce_max:
            game.trade(g.name)
        elif prov.farm < prov.farm_max:
            game.develop(g.name)
    except CommandError:
        pass
