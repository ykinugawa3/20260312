"""ゲーム本体: 状態と命令、ターン進行.

1ターン = 1季節。プレイヤーが命令を出したら end_turn() で
AI大名の行動 → 合戦の解決 → 季節の収支 → 次の季節のイベント の順に進む。
乱数は Game ごとの random.Random なので、seed を固定すれば同じ展開を再現できる。
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

from . import ai, data
from .battle import NO_GENERAL_LEADERSHIP, BattleOutcome, castle_bonus, fight

COMMAND_COST = 30          # 開墾・商業・築城にかかる金
DEFENSE_MAX = 1000
TROOPS_PER_FARM = 8        # 国の最大兵数 = 農業 × 8
MARCH_FOOD = 0.1           # 出陣時の兵糧 (兵1あたり)
UPKEEP_FOOD = 1 / 40       # 季節ごとの兵糧消費 (兵1あたり)
MIN_ATTACK_TROOPS = 100
RECRUIT_GOLD = 1 / 8       # 徴兵の金 (兵1あたり)
HIRE_CHANCE = 0.5          # 捕らえた武将が仕官する確率
DISASTER_CHANCE = 0.03     # 夏・秋に国ごとに起きる風水害の確率


class CommandError(Exception):
    """命令を実行できない (理由はメッセージ)."""


@dataclass
class Province:
    name: str
    kokudaka: int
    lon: float
    lat: float
    snow: bool
    farm: int
    farm_max: int
    commerce: int
    commerce_max: int
    defense: int
    troops: int
    owner: str | None  # None = 国人衆 (どの大名にも属さない)


@dataclass
class General:
    name: str
    clan: str | None      # None = 浪人 (Phase 1 では再登場しない)
    province: str | None  # None = 出陣中または浪人
    leadership: int
    valor: int
    intellect: int
    politics: int
    acted: bool = False


@dataclass
class Clan:
    name: str
    leader: str | None
    gold: int
    food: int
    color: str
    aggression: float
    alive: bool = True


@dataclass
class Army:
    clan: str
    general: str
    source: str
    target: str
    troops: int


@dataclass
class BattleRecord:
    province: str
    attacker: str
    defender: str | None
    att_general: str
    def_general: str | None
    att_start: int
    def_start: int
    outcome: BattleOutcome

    def summary(self) -> str:
        defender = f"{self.defender}家" if self.defender else "国人衆"
        def_general = self.def_general or "城兵"
        result = "攻略" if self.outcome.attacker_won else "撃退"
        return (f"{self.province}: {self.attacker}家 {self.att_general} {self.att_start}→{self.outcome.attacker_left} vs "
                f"{defender} {def_general} {self.def_start}→{self.outcome.defender_left} … {result}")


@dataclass
class TurnReport:
    label: str
    battles: list[BattleRecord] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


class Game:
    def __init__(self, player: str, seed: int | None = None):
        clan_names = [c[0] for c in data.CLANS]
        if player not in clan_names:
            raise ValueError(f"unknown clan: {player}")
        self.player = player
        self.rng = random.Random(seed)
        self.turn = 0
        self.armies: list[Army] = []
        self.reports: list[TurnReport] = []
        self.status = "playing"  # playing / won / lost
        self.result = ""

        self.adj: dict[str, set[str]] = {p[0]: set() for p in data.PROVINCES}
        for a, bs in data.ADJACENCY.items():
            for b in bs:
                self.adj[a].add(b)
                self.adj[b].add(a)

        owner_of = {p: c[0] for c in data.CLANS for p in c[2]}
        self.provinces: dict[str, Province] = {}
        for name, koku, lon, lat, snow, trade in data.PROVINCES:
            owner = owner_of.get(name)
            farm_max = koku * 20
            commerce_max = koku * 10 + trade
            self.provinces[name] = Province(
                name=name, kokudaka=koku, lon=lon, lat=lat, snow=snow,
                farm=int(farm_max * 0.6), farm_max=farm_max,
                commerce=int(commerce_max * 0.5), commerce_max=commerce_max,
                defense=400 if owner else 300,
                troops=koku * (80 if owner else 40),
                owner=owner,
            )

        self.clans: dict[str, Clan] = {}
        for name, leader, provs, color, aggression in data.CLANS:
            food = sum(self.provinces[p].farm for p in provs)
            self.clans[name] = Clan(name, leader, gold=300, food=food, color=color, aggression=aggression)
            self.provinces[provs[0]].defense = 500  # 本拠地

        self.generals: dict[str, General] = {}
        members: dict[str, int] = {}
        for name, clan, lead, val, intel, pol in data.GENERALS:
            provs = next(c[2] for c in data.CLANS if c[0] == clan)
            i = members.get(clan, 0)
            members[clan] = i + 1
            self.generals[name] = General(name, clan, provs[i % len(provs)], lead, val, intel, pol)

    # ------------------------------------------------------------ 状態の参照

    @property
    def year(self) -> int:
        return data.START_YEAR + self.turn // 4

    @property
    def season(self) -> int:
        return self.turn % 4

    @property
    def date_label(self) -> str:
        return f"{self.year}年 {data.SEASONS[self.season]}"

    def neighbors(self, prov: str) -> list[str]:
        return sorted(self.adj[prov])

    def owned(self, clan: str) -> list[Province]:
        return [p for p in self.provinces.values() if p.owner == clan]

    def alive_clans(self) -> list[Clan]:
        return [c for c in self.clans.values() if c.alive]

    def members(self, clan: str) -> list[General]:
        return [g for g in self.generals.values() if g.clan == clan]

    def generals_in(self, prov: str) -> list[General]:
        owner = self.provinces[prov].owner
        return [g for g in self.generals.values() if g.province == prov and g.clan == owner]

    def idle_generals(self, prov: str) -> list[General]:
        return [g for g in self.generals_in(prov) if not g.acted]

    def clan_troops(self, clan: str) -> int:
        return sum(p.troops for p in self.owned(clan)) + sum(a.troops for a in self.armies if a.clan == clan)

    def max_troops(self, prov: str) -> int:
        return self.provinces[prov].farm * TROOPS_PER_FARM

    def snowbound(self, prov: str) -> bool:
        return self.season == 3 and self.provinces[prov].snow

    def attack_targets(self, prov: str) -> list[str]:
        """prov から攻め込める隣国 (冬の雪国は出入りできない)."""
        p = self.provinces[prov]
        if self.snowbound(prov):
            return []
        return [n for n in self.neighbors(prov)
                if self.provinces[n].owner != p.owner and not self.snowbound(n)]

    def defense_strength(self, prov: str) -> float:
        """守備側の戦力の見積もり (士気の乱数を除く)."""
        p = self.provinces[prov]
        leads = [g.leadership for g in self.generals_in(prov)]
        lead = max(leads) if leads else NO_GENERAL_LEADERSHIP
        return p.troops * (1 + lead / 100) * castle_bonus(p.defense)

    def recruit_amount(self, general: str) -> int:
        g = self.generals[general]
        p = self.provinces[g.province]
        return max(min(200 + g.politics * 4, self.max_troops(p.name) - p.troops), 0)

    def front_distance(self, clan: str) -> dict[str, int]:
        """自領の各国から敵国 (国人衆を含む) と接する国までの距離 (前線 = 0)."""
        own = {p.name for p in self.owned(clan)}
        dist = {n: 0 for n in own if any(self.provinces[m].owner != clan for m in self.adj[n])}
        queue = deque(dist)
        while queue:
            cur = queue.popleft()
            for n in self.adj[cur]:
                if n in own and n not in dist:
                    dist[n] = dist[cur] + 1
                    queue.append(n)
        return {n: dist.get(n, 99) for n in own}

    # ------------------------------------------------------------ 命令

    def _ready(self, general: str) -> tuple[General, Province, Clan]:
        if self.status != "playing":
            raise CommandError("ゲームは終了しています")
        g = self.generals.get(general)
        if g is None or g.clan is None or g.province is None:
            raise CommandError(f"{general} は命令を受けられません")
        if g.acted:
            raise CommandError(f"{g.name} は今季すでに行動しました")
        p = self.provinces[g.province]
        if p.owner != g.clan:
            raise CommandError(f"{p.name} は {g.clan}家の国ではありません")
        return g, p, self.clans[g.clan]

    @staticmethod
    def _pay(clan: Clan, gold: int) -> None:
        if clan.gold < gold:
            raise CommandError(f"金が足りません (必要 {gold} / 所持 {clan.gold})")
        clan.gold -= gold

    def _gain(self, ability: int) -> int:
        return int(10 + ability * 0.4 + self.rng.randint(0, 10))

    def develop(self, general: str) -> str:
        g, p, clan = self._ready(general)
        if p.farm >= p.farm_max:
            raise CommandError(f"{p.name} の農業はこれ以上上がりません")
        self._pay(clan, COMMAND_COST)
        before = p.farm
        p.farm = min(p.farm + self._gain(g.politics), p.farm_max)
        g.acted = True
        return f"{g.name} が {p.name} を開墾 (農業 {before}→{p.farm})"

    def trade(self, general: str) -> str:
        g, p, clan = self._ready(general)
        if p.commerce >= p.commerce_max:
            raise CommandError(f"{p.name} の商業はこれ以上上がりません")
        self._pay(clan, COMMAND_COST)
        before = p.commerce
        p.commerce = min(p.commerce + self._gain(g.politics), p.commerce_max)
        g.acted = True
        return f"{g.name} が {p.name} の商業を振興 (商業 {before}→{p.commerce})"

    def fortify(self, general: str) -> str:
        g, p, clan = self._ready(general)
        if p.defense >= DEFENSE_MAX:
            raise CommandError(f"{p.name} の城はこれ以上固められません")
        self._pay(clan, COMMAND_COST)
        before = p.defense
        p.defense = min(p.defense + self._gain(g.leadership), DEFENSE_MAX)
        g.acted = True
        return f"{g.name} が {p.name} の城を修築 (防御 {before}→{p.defense})"

    def recruit(self, general: str) -> str:
        g, p, clan = self._ready(general)
        amount = self.recruit_amount(general)
        if amount <= 0:
            raise CommandError(f"{p.name} ではこれ以上徴兵できません (上限 {self.max_troops(p.name)})")
        self._pay(clan, math.ceil(amount * RECRUIT_GOLD))
        p.troops += amount
        g.acted = True
        return f"{g.name} が {p.name} で {amount} 人を徴兵 (兵 {p.troops})"

    def move(self, general: str, dest: str, troops: int, with_general: bool = True) -> str:
        """隣の自国へ移動する。with_general=False なら兵だけを送る (輸送)."""
        g, p, clan = self._ready(general)
        if dest not in self.adj[p.name] or self.provinces[dest].owner != clan.name:
            raise CommandError(f"{dest} は {p.name} に隣接する自国ではありません")
        if not 0 <= troops <= p.troops:
            raise CommandError(f"送れる兵は 0〜{p.troops} です")
        if not with_general and troops == 0:
            raise CommandError("輸送する兵を指定してください")
        p.troops -= troops
        self.provinces[dest].troops += troops
        g.acted = True
        if with_general:
            g.province = dest
            return f"{g.name} が兵 {troops} を率いて {p.name} から {dest} へ移動"
        return f"{g.name} が兵 {troops} を {p.name} から {dest} へ輸送"

    def march_food(self, troops: int) -> int:
        return math.ceil(troops * MARCH_FOOD)

    def attack(self, general: str, target: str, troops: int) -> str:
        g, p, clan = self._ready(general)
        if target not in self.attack_targets(p.name):
            raise CommandError(f"{p.name} から {target} へは攻め込めません")
        if not MIN_ATTACK_TROOPS <= troops <= p.troops:
            raise CommandError(f"出陣できる兵は {MIN_ATTACK_TROOPS}〜{p.troops} です")
        food = self.march_food(troops)
        if clan.food < food:
            raise CommandError(f"兵糧が足りません (必要 {food} / 所持 {clan.food})")
        clan.food -= food
        p.troops -= troops
        g.province = None
        g.acted = True
        self.armies.append(Army(clan.name, g.name, p.name, target, troops))
        return f"{g.name} が兵 {troops} で {target} へ出陣 (季節の終わりに合戦)"

    def delegate(self) -> None:
        """プレイヤーの未行動の武将を AI に任せる."""
        ai.take_turn(self, self.player)

    # ------------------------------------------------------------ ターン進行

    def end_turn(self) -> TurnReport:
        if self.status != "playing":
            raise CommandError("ゲームは終了しています")
        report = TurnReport(self.date_label)
        others = [c.name for c in self.alive_clans() if c.name != self.player]
        self.rng.shuffle(others)
        for name in others:
            ai.take_turn(self, name)
        self._resolve_battles(report)
        self._remove_fallen(report)
        self._season_end(report)
        self.turn += 1
        for g in self.generals.values():
            g.acted = False
        self._check_end(report)
        if self.status == "playing":
            self._season_start(report)
        self.reports.append(report)
        return report

    def _resolve_battles(self, report: TurnReport) -> None:
        armies, self.armies = self.armies, []
        self.rng.shuffle(armies)
        for army in armies:
            g = self.generals[army.general]
            target = self.provinces[army.target]
            if target.owner == army.clan:  # 先に味方が落としていた
                target.troops += army.troops
                g.province = target.name
                continue
            defenders = self.generals_in(target.name)
            best = max(defenders, key=lambda d: d.leadership, default=None)
            outcome = fight(army.troops, g.leadership, target.troops,
                            best.leadership if best else NO_GENERAL_LEADERSHIP, target.defense, self.rng)
            report.battles.append(BattleRecord(target.name, army.clan, target.owner, g.name,
                                               best.name if best else None, army.troops, target.troops, outcome))
            if outcome.attacker_won:
                self._capture(target, army.clan, outcome.attacker_left, outcome.defender_left, report)
                g.province = target.name
            else:
                target.troops = outcome.defender_left
                target.defense = int(target.defense * 0.9)
                self._retreat(army, outcome.attacker_left, report)

    def _capture(self, target: Province, captor: str, att_left: int, def_left: int, report: TurnReport) -> None:
        old = target.owner
        fleeing = self.generals_in(target.name)
        escapes = [n for n in self.neighbors(target.name) if old and self.provinces[n].owner == old]
        target.owner = captor
        target.troops = att_left
        target.defense = int(target.defense * 0.7)
        if escapes:
            dest = max(escapes, key=lambda n: self.provinces[n].troops)
            self.provinces[dest].troops += def_left
            for gen in fleeing:
                gen.province = dest
            if fleeing:
                report.events.append(f"{'・'.join(x.name for x in fleeing)} は {dest} へ退却した")
            return
        for gen in fleeing:
            self._captured(gen, captor, target.name, report)

    def _captured(self, gen: General, captor: str, prov: str, report: TurnReport) -> None:
        old = self.clans[gen.clan]
        if old.leader == gen.name:
            gen.clan = gen.province = None
            report.events.append(f"{old.name}家の当主 {gen.name} が {prov} で討ち死にした")
            self._succession(old, report)
        elif self.rng.random() < HIRE_CHANCE:
            gen.clan = captor
            gen.province = prov
            report.events.append(f"{gen.name} が捕らえられ、{captor}家に仕えた")
        else:
            gen.clan = gen.province = None
            report.events.append(f"{gen.name} は捕らえられたが仕官を拒み、浪人となった")

    def _succession(self, clan: Clan, report: TurnReport) -> None:
        heirs = self.members(clan.name)
        if not heirs:
            clan.leader = None
            return
        heir = max(heirs, key=lambda h: h.leadership + h.politics)
        clan.leader = heir.name
        report.events.append(f"{clan.name}家は {heir.name} が家督を継いだ")

    def _retreat(self, army: Army, left: int, report: TurnReport) -> None:
        g = self.generals[army.general]
        options = [army.source] + self.neighbors(army.target)
        home = next((n for n in options if self.provinces[n].owner == army.clan), None)
        if home:
            self.provinces[home].troops += left
            g.province = home
            return
        clan = self.clans[army.clan]
        g.clan = None
        report.events.append(f"{g.name} は帰る国を失い、軍は四散した")
        if clan.leader == g.name:
            self._succession(clan, report)

    def _remove_fallen(self, report: TurnReport) -> None:
        for clan in self.alive_clans():
            provs = self.owned(clan.name)
            gens = self.members(clan.name)
            if provs and gens:
                if clan.leader is None:
                    self._succession(clan, report)
                continue
            clan.alive = False
            for p in provs:
                p.owner = None
            for g in gens:
                g.clan = g.province = None
            report.events.append(f"{clan.name}家が滅亡した")

    def _season_end(self, report: TurnReport) -> None:
        for clan in self.alive_clans():
            provs = self.owned(clan.name)
            clan.gold += sum(p.commerce for p in provs) // 4
            clan.food -= math.ceil(sum(p.troops for p in provs) * UPKEEP_FOOD)
            if clan.food < 0:
                clan.food = 0
                for p in provs:
                    p.troops = int(p.troops * 0.9)
                if clan.name == self.player:
                    report.events.append("兵糧が尽き、兵の一割が逃げ出した")

    def _season_start(self, report: TurnReport) -> None:
        if self.season == 2:
            for clan in self.alive_clans():
                harvest = sum(p.farm for p in self.owned(clan.name))
                clan.food += harvest
                if clan.name == self.player:
                    report.events.append(f"秋の収穫: 兵糧 +{harvest}")
        if self.season in (1, 2):
            for p in self.provinces.values():
                if p.owner and self.rng.random() < DISASTER_CHANCE:
                    loss = p.farm // 10
                    p.farm -= loss
                    if p.owner == self.player:
                        report.events.append(f"{p.name} を風水害が襲った (農業 -{loss})")
        if self.season == 3:
            report.events.append("冬: 雪国 (北陸・飛騨・奥羽) では出陣できない")

    def _check_end(self, report: TurnReport) -> None:
        mine = len(self.owned(self.player))
        if mine == 0 or not self.clans[self.player].alive:
            self.status, self.result = "lost", f"{self.player}家は滅亡しました"
        elif mine == len(self.provinces):
            self.status, self.result = "won", f"{self.date_label}、{self.player}家が天下を統一しました"
        elif self.turn >= data.TOTAL_TURNS:
            ranking = sorted(self.alive_clans(), key=lambda c: len(self.owned(c.name)), reverse=True)
            top = ranking[0]
            if top.name == self.player or len(self.owned(top.name)) == mine:
                self.status = "won"
                self.result = f"時間切れ。{mine}か国を治める最大勢力として、{self.player}家が天下人と認められました"
            else:
                self.status = "lost"
                self.result = f"時間切れ。天下人となったのは {len(self.owned(top.name))}か国を治める{top.name}家でした"
        if self.status != "playing":
            report.events.append(self.result)
