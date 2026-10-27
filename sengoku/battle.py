"""オート合戦.

戦力 = 兵数 × (1 + 統率/100) × 士気補正 × 城補正 (守備側のみ) を、
ランチェスター型の消耗で数ラウンド戦わせる。
攻撃側は兵が出陣時の 40% を切ると退却し、守備側は 25% を切ると落城する。
決着がつかないまま最終ラウンドを迎えたら攻城失敗 (守備側の勝ち)。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

LOSS_RATE = 0.08
MAX_ROUNDS = 12
ATTACKER_ROUT = 0.40
DEFENDER_ROUT = 0.25
NO_GENERAL_LEADERSHIP = 40  # 武将不在 (国人衆など) の守備側の統率


def castle_bonus(defense: int) -> float:
    """城の防御度 0〜1000 を守備側の戦力倍率 1.0〜2.0 に換算する."""
    return 1.0 + max(defense, 0) / 1000


@dataclass
class BattleOutcome:
    attacker_won: bool
    attacker_left: int
    defender_left: int
    rounds: list[tuple[int, int]] = field(default_factory=list)  # 各ラウンド後の (攻撃側, 守備側) 兵数


def fight(att_troops: int, att_lead: int, def_troops: int, def_lead: int, defense: int,
          rng: random.Random) -> BattleOutcome:
    if def_troops <= 0:
        return BattleOutcome(True, att_troops, 0, [(att_troops, 0)])
    if att_troops <= 0:
        return BattleOutcome(False, 0, def_troops, [(0, def_troops)])

    att_mult = (1 + att_lead / 100) * rng.uniform(0.85, 1.15)
    def_mult = (1 + def_lead / 100) * castle_bonus(defense) * rng.uniform(0.85, 1.15)
    a, d = float(att_troops), float(def_troops)
    rounds = [(att_troops, def_troops)]
    for _ in range(MAX_ROUNDS):
        a, d = (max(a - LOSS_RATE * d * def_mult / att_mult, 0.0),
                max(d - LOSS_RATE * a * att_mult / def_mult, 0.0))
        rounds.append((round(a), round(d)))
        if d <= def_troops * DEFENDER_ROUT:
            return BattleOutcome(True, round(a), round(d), rounds)
        if a <= att_troops * ATTACKER_ROUT:
            return BattleOutcome(False, round(a), round(d), rounds)
    return BattleOutcome(False, round(a), round(d), rounds)
