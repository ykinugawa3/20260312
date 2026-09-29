"""レース単位の確率較正.

モデル勝率 p_model と市場確率 p_market (オッズの逆数を正規化したもの) を
条件付きロジットで組み合わせる (Benter 方式):

    p_i ∝ exp(a * log p_model_i + b * log p_market_i)

a, b は学習に使っていない期間の予測で、レース内の多項尤度を最大化して決める。
use_market=False のときは b=0 (温度スケーリングのみ) になる。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

_EPS = 1e-9


def market_prob(odds: pd.Series, race_id: pd.Series) -> pd.Series:
    implied = 1 / odds
    return implied / implied.groupby(race_id).transform("sum")


def _race_softmax(logit: np.ndarray, codes: np.ndarray, n_groups: int) -> np.ndarray:
    mx = np.full(n_groups, -np.inf)
    np.maximum.at(mx, codes, logit)
    e = np.exp(logit - mx[codes])
    denom = np.bincount(codes, weights=e, minlength=n_groups)
    return e / denom[codes]


@dataclass
class RaceCalibrator:
    a: float = 1.0
    b: float = 0.0
    use_market: bool = True

    def _logit(self, p_model: np.ndarray, p_mkt: np.ndarray | None) -> np.ndarray:
        z = self.a * np.log(np.clip(p_model, _EPS, 1))
        if self.use_market and p_mkt is not None:
            z = z + self.b * np.log(np.clip(p_mkt, _EPS, 1))
        return z

    def fit(self, p_model: pd.Series, odds: pd.Series, race_id: pd.Series, is_win: pd.Series) -> "RaceCalibrator":
        codes, uniques = pd.factorize(race_id)
        n = len(uniques)
        pm = p_model.to_numpy(float)
        pk = market_prob(odds, race_id).to_numpy(float) if self.use_market else None
        y = is_win.to_numpy(float)

        def nll(params: np.ndarray) -> float:
            self.a, self.b = params if self.use_market else (params[0], 0.0)
            p = _race_softmax(self._logit(pm, pk), codes, n)
            return -float(np.sum(y * np.log(np.clip(p, _EPS, 1)))) / n

        x0 = np.array([1.0, 1.0]) if self.use_market else np.array([1.0])
        res = minimize(nll, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-6})
        self.a, self.b = (float(res.x[0]), float(res.x[1])) if self.use_market else (float(res.x[0]), 0.0)
        return self

    def transform(self, p_model: pd.Series, odds: pd.Series, race_id: pd.Series) -> pd.Series:
        codes, uniques = pd.factorize(race_id)
        pk = None
        if self.use_market:
            # オッズ未発表の馬はモデル勝率で代用する
            pk = market_prob(odds, race_id).fillna(p_model).to_numpy(float)
        p = _race_softmax(self._logit(p_model.to_numpy(float), pk), codes, len(uniques))
        return pd.Series(p, index=p_model.index)


def reliability_table(prob: pd.Series, is_win: pd.Series, bins: int = 10) -> pd.DataFrame:
    """予測確率を分位で区切り、平均予測確率と実際の勝率を比べる表 (較正曲線用)."""
    df = pd.DataFrame({"prob": prob, "win": is_win})
    df["bin"] = pd.qcut(df["prob"], bins, duplicates="drop")
    out = df.groupby("bin", observed=True).agg(pred=("prob", "mean"), actual=("win", "mean"), n=("win", "size"))
    return out.reset_index(drop=True)
