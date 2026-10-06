"""予測の評価とベースライン.

- IC: 日ごとの「予測スコアと実際の超過リターンの順位相関」. 株式の予測では 0.02〜0.05 でも有用とされる
- IC の t 値: 目的変数の期間が重なる日同士は独立でないため、horizon 日おきの IC だけで計算する
- 分位スプレッド: スコア上位 20% と下位 20% の平均超過リターンの差
- 簡易ポートフォリオ: horizon 日ごとに上位 N 銘柄を等金額で入れ替え、売買コストを差し引く
  (リバランス間の比率の変化は無視した近似. 本格的なバックテストは Phase 2)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from kabu.features import DEFAULT_HORIZON

TRADING_DAYS = 252


def baseline_scores(df: pd.DataFrame) -> dict[str, pd.Series]:
    """機械学習を使わない比較対象. 機械学習モデルはこれらに勝てて初めて採用する."""
    return {
        "モメンタム (12-1ヶ月)": df["mom_12_1_rank"],
        "複合ファクター": (df["mom_12_1_rank"] + (1 - df["ret_5_rank"]) + (1 - df["vol_60_rank"])) / 3,
    }


def daily_ic(df: pd.DataFrame, score: pd.Series) -> pd.Series:
    d = pd.DataFrame({"date": df["date"], "s": score, "y": df["target"]}).dropna()
    ranked = d.groupby("date")[["s", "y"]].rank()
    ranked["date"] = d["date"]
    return ranked.groupby("date").apply(lambda g: g["s"].corr(g["y"]), include_groups=False).dropna()


def quantile_spread(df: pd.DataFrame, score: pd.Series, q: float = 0.2) -> float:
    d = pd.DataFrame({"date": df["date"], "s": score, "y": df["target"]}).dropna()
    pct = d.groupby("date")["s"].rank(pct=True)
    top = d.loc[pct > 1 - q].groupby("date")["y"].mean()
    bottom = d.loc[pct <= q].groupby("date")["y"].mean()
    return float((top - bottom).mean())


@dataclass
class PortfolioResult:
    periods: pd.DataFrame  # date, ret, bench, turnover
    horizon: int

    def _annual(self, r: pd.Series) -> float:
        n_years = len(r) * self.horizon / TRADING_DAYS
        return float((1 + r).prod() ** (1 / n_years) - 1) if n_years > 0 else float("nan")

    def summary(self) -> dict[str, float]:
        r, b = self.periods["ret"], self.periods["bench"]
        per_year = TRADING_DAYS / self.horizon
        equity = (1 + r).cumprod()
        excess = r - b
        return {
            "年率リターン": self._annual(r),
            "SPY 年率": self._annual(b),
            "超過 (年率)": self._annual(r) - self._annual(b),
            "シャープ": float(r.mean() / r.std() * np.sqrt(per_year)) if r.std() > 0 else float("nan"),
            "情報比": float(excess.mean() / excess.std() * np.sqrt(per_year)) if excess.std() > 0 else float("nan"),
            "最大DD": float((equity / equity.cummax() - 1).min()),
            "回転率": float(self.periods["turnover"].mean()),
        }


def top_n_portfolio(
    df: pd.DataFrame, score: pd.Series, top_n: int = 20, horizon: int = DEFAULT_HORIZON, cost_bps: float = 10.0
) -> PortfolioResult:
    """horizon 営業日ごとにスコア上位 top_n 銘柄を等金額で保有する.

    リターンは features の fwd_return (翌営業日寄付 → horizon 日後の寄付) を使う.
    cost_bps は片道の売買コスト (スプレッド・スリッページ等, 0.01% 単位).
    """
    d = pd.DataFrame({"date": df["date"], "sid": df["security_id"], "s": score,
                      "r": df["fwd_return"], "b": df["bench_return"]}).dropna()
    dates = np.sort(d["date"].unique())[::horizon]
    rows, prev = [], pd.Series(dtype=float)
    for date in dates:
        day = d[d["date"] == date].nlargest(top_n, "s")
        if day.empty:
            continue
        w = pd.Series(1.0 / len(day), index=day["sid"].to_numpy())
        traded = w.sub(prev, fill_value=0).abs().sum()
        ret = float((day["r"].to_numpy() * w.to_numpy()).sum()) - traded * cost_bps / 1e4
        rows.append((date, ret, float(day["b"].iloc[0]), traded / 2))
        prev = w
    periods = pd.DataFrame(rows, columns=["date", "ret", "bench", "turnover"])
    return PortfolioResult(periods, horizon)


def evaluate_scores(
    df: pd.DataFrame, scores: dict[str, pd.Series], horizon: int = DEFAULT_HORIZON,
    top_n: int = 20, cost_bps: float = 10.0,
) -> pd.DataFrame:
    """各スコアの予測精度と簡易ポートフォリオ成績を 1 つの表にまとめる."""
    labeled = df.dropna(subset=["target"])
    rows = {}
    for name, s in scores.items():
        s = s.loc[labeled.index]
        ic = daily_ic(labeled, s)
        ic_indep = ic.iloc[::horizon]
        t = ic_indep.mean() / ic_indep.std() * np.sqrt(len(ic_indep)) if len(ic_indep) > 1 else float("nan")
        row = {
            "IC 平均": ic.mean(),
            "IC>0 の割合": (ic > 0).mean(),
            "IC t値": t,
            "上位-下位20%": quantile_spread(labeled, s),
        }
        row.update(top_n_portfolio(labeled, s, top_n, horizon, cost_bps).summary())
        rows[name] = row
    return pd.DataFrame(rows).T
