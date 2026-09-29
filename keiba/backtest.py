"""ウォークフォワード・バックテストと資金配分シミュレーション.

1. walk_forward_predictions: 期間ごとに「その期間より前の確定データだけ」で学習し、期間内を予測する。
2. simulate: 予測結果に買い方 (Strategy) を当てはめ、資金推移と回収率を計算する。
   予測は重いが買い方の試行は軽いので、両者を分けてある。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from keiba import model as model_mod
from keiba.calibration import market_prob

PRED_COLUMNS = [
    "race_id", "date", "course", "race_number", "surface", "distance", "race_class",
    "horse_number", "horse_name", "odds", "popularity", "finish_position", "is_win",
]


def walk_forward_predictions(
    df: pd.DataFrame,
    start: str | pd.Timestamp,
    freq: str = "MS",
    progress=None,
    **train_kwargs,
) -> pd.DataFrame:
    """start 以降を freq ごと (既定: 月初区切り) に区切って予測する."""
    df = df[df["finished"]]
    start = pd.Timestamp(start)
    end = df["date"].max()
    bounds = list(pd.date_range(start, end, freq=freq))
    if not bounds or bounds[0] > start:
        bounds.insert(0, start)
    bounds.append(end + pd.Timedelta(days=1))

    out = []
    n_steps = len(bounds) - 1
    for i, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:])):
        train_df = df[df["date"] < lo]
        test_df = df[(df["date"] >= lo) & (df["date"] < hi)]
        if progress:
            progress(i, n_steps, lo)
        if test_df.empty or train_df.empty:
            continue
        m = model_mod.train(train_df, **train_kwargs)
        part = test_df[PRED_COLUMNS].copy()
        part["model_prob"] = m.predict_raw(test_df)
        part["win_prob"] = m.predict(test_df)
        part["market_prob"] = market_prob(test_df["odds"], test_df["race_id"])
        out.append(part)
    if progress:
        progress(n_steps, n_steps, end)
    if not out:
        raise ValueError(f"{start:%Y-%m-%d} 以降に予測できる期間がありません")
    return pd.concat(out).sort_values(["date", "race_id", "horse_number"]).reset_index(drop=True)


@dataclass
class Strategy:
    ev_threshold: float = 1.2      # 期待値 (勝率×オッズ) がこれを超える馬だけ買う
    min_prob: float = 0.03         # 勝率がこれ未満の馬は買わない (大穴の過大評価対策)
    max_odds: float = 50.0         # オッズ上限
    kelly_fraction: float = 0.1    # ケリー基準の何割を賭けるか
    max_bet_ratio: float = 0.01    # 1 点あたりの上限 (資金比)
    max_race_ratio: float = 0.03   # 1 レースあたりの上限 (資金比)
    flat_stake: int | None = None  # 指定すると常にこの金額の定額買い
    unit: int = 100                # 購入単位 (円)


def kelly(prob: pd.Series | np.ndarray, odds: pd.Series | np.ndarray):
    """単勝のケリー比率 f* = (p·o − 1) / (o − 1). 期待値がマイナスなら 0."""
    f = (prob * odds - 1) / (odds - 1)
    return np.clip(f, 0, None)


def select_candidates(preds: pd.DataFrame, s: Strategy) -> pd.DataFrame:
    c = preds.copy()
    c["expected_value"] = c["win_prob"] * c["odds"]
    c = c[
        (c["expected_value"] > s.ev_threshold)
        & (c["win_prob"] >= s.min_prob)
        & (c["odds"] <= s.max_odds)
        & c["odds"].notna()
    ].copy()
    c["kelly"] = kelly(c["win_prob"], c["odds"])
    return c


def stakes_for_race(cands: pd.DataFrame, bankroll: float, s: Strategy) -> np.ndarray:
    """1 レース分の候補に対する購入金額 (unit 単位に切り捨て)."""
    if s.flat_stake:
        stakes = np.full(len(cands), float(s.flat_stake))
    else:
        stakes = bankroll * s.kelly_fraction * cands["kelly"].to_numpy()
        stakes = np.minimum(stakes, bankroll * s.max_bet_ratio)
        total = stakes.sum()
        cap = bankroll * s.max_race_ratio
        if total > cap:
            stakes *= cap / total
    return np.floor(stakes / s.unit) * s.unit


def simulate(preds: pd.DataFrame, strategy: Strategy, bankroll: float = 100_000) -> tuple[pd.DataFrame, dict]:
    """レースを時系列順に処理して資金推移を計算する. (買い目ごとの明細, 集計) を返す."""
    cands = select_candidates(preds, strategy)
    initial = bankroll
    rows = []
    for (date, race_id), race in cands.groupby(["date", "race_id"], sort=True):
        if bankroll < strategy.unit:
            break
        stakes = stakes_for_race(race, bankroll, strategy)
        if stakes.sum() > bankroll:
            stakes = np.floor(stakes * bankroll / stakes.sum() / strategy.unit) * strategy.unit
        payout = stakes * race["odds"].to_numpy() * race["is_win"].to_numpy()
        bankroll += payout.sum() - stakes.sum()
        bet = race.assign(stake=stakes, payout=payout)
        bet = bet[bet["stake"] > 0]
        if not bet.empty:
            bet["bankroll_after"] = bankroll
            rows.append(bet)

    bets = pd.concat(rows).reset_index(drop=True) if rows else cands.iloc[0:0].assign(
        stake=[], payout=[], bankroll_after=[]
    )
    return bets, summarize(bets, initial)


def bankroll_curve(bets: pd.DataFrame, initial: float) -> pd.DataFrame:
    """レース単位の資金推移."""
    if bets.empty:
        return pd.DataFrame({"date": [], "race_id": [], "bankroll": []})
    curve = bets.groupby(["date", "race_id"], sort=True)["bankroll_after"].last().reset_index()
    return curve.rename(columns={"bankroll_after": "bankroll"})


def max_drawdown(values: pd.Series, initial: float) -> float:
    """最大ドローダウン (ピークからの最大下落率)."""
    series = pd.concat([pd.Series([initial]), values.reset_index(drop=True)])
    peak = series.cummax()
    return float(((peak - series) / peak).max())


def summarize(bets: pd.DataFrame, initial: float) -> dict:
    if bets.empty:
        return {"n_bets": 0, "n_races": 0, "hit_rate": float("nan"), "total_stake": 0.0,
                "total_payout": 0.0, "roi": float("nan"), "profit": 0.0,
                "final_bankroll": initial, "max_drawdown": 0.0, "avg_odds_hit": float("nan")}
    curve = bankroll_curve(bets, initial)
    stake, payout = float(bets["stake"].sum()), float(bets["payout"].sum())
    hits = bets[bets["is_win"] == 1]
    return {
        "n_bets": int(len(bets)),
        "n_races": int(bets["race_id"].nunique()),
        "hit_rate": float(bets["is_win"].mean()),
        "total_stake": stake,
        "total_payout": payout,
        "roi": payout / stake if stake else float("nan"),
        "profit": payout - stake,
        "final_bankroll": float(curve["bankroll"].iloc[-1]),
        "max_drawdown": max_drawdown(curve["bankroll"], initial),
        "avg_odds_hit": float(hits["odds"].mean()) if len(hits) else float("nan"),
    }


def monthly_summary(bets: pd.DataFrame) -> pd.DataFrame:
    if bets.empty:
        return pd.DataFrame(columns=["month", "n_bets", "hits", "stake", "payout", "profit", "roi"])
    m = bets.assign(month=pd.to_datetime(bets["date"]).dt.to_period("M").astype(str))
    out = m.groupby("month").agg(
        n_bets=("stake", "size"), hits=("is_win", "sum"), stake=("stake", "sum"), payout=("payout", "sum")
    ).reset_index()
    out["profit"] = out["payout"] - out["stake"]
    out["roi"] = out["payout"] / out["stake"]
    return out


def compare_baselines(preds: pd.DataFrame) -> pd.DataFrame:
    """定額 1 点買いの単純戦略との比較 (回収率)."""
    fav = preds.loc[preds.groupby("race_id")["market_prob"].idxmax()]
    top = preds.loc[preds.groupby("race_id")["win_prob"].idxmax()]
    top_raw = preds.loc[preds.groupby("race_id")["model_prob"].idxmax()]
    rows = [
        ("1番人気を毎レース", fav),
        ("較正後モデル1位を毎レース", top),
        ("モデル単体1位を毎レース", top_raw),
    ]
    return pd.DataFrame(
        [{"戦略": name, "点数": len(b), "的中率": b["is_win"].mean(), "回収率": model_mod.roi(b)} for name, b in rows]
    )
