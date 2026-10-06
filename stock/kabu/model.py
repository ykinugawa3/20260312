"""LightGBM による銘柄の順位予測モデル.

営業日ごとに銘柄を順位付けする. 目的関数は 2 種類:

- rank_regression (既定): 目的変数 (対 SPY 超過リターン) を日ごとの順位 → 正規分布の値に変換し、
  それを回帰で当てる. 日ごとの順位相関 (IC) を直接高める形になる
- lambdarank: 日ごとに 10 段階の関連度を付けて上位を重視する順位学習 (競馬版のレース内順位学習と同じ).
  仮データでは「値動きの大きい銘柄ほど最上位に入りやすい」ことを覚えてボラティリティの高い銘柄に偏り、
  IC がほぼ 0 になったため既定にはしていない

株価の予測力は弱くノイズが大きいため、浅い木・大きな葉の最小サンプル数で強く正則化し、
学習回数は固定にする (短い検証期間での早期終了は回数がばらつきやすい).
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import norm

from kabu.features import DEFAULT_HORIZON, MODEL_FEATURES

DEFAULT_MODEL_PATH = Path("models/rank_model.pkl")
OBJECTIVES = ["rank_regression", "lambdarank"]
N_LEVELS = 10
DEFAULT_ROUNDS = 300

DEFAULT_PARAMS = {
    "learning_rate": 0.02,
    "num_leaves": 7,
    "min_child_samples": 1000,
    "feature_fraction": 0.7,
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l2": 10.0,
    "verbose": -1,
    "seed": 42,
}


def gauss_rank(df: pd.DataFrame, col: str = "target") -> pd.Series:
    """日ごとの順位を標準正規分布の値に変換する (外れ値の影響を抑え、日ごとの散らばりを揃える)."""
    g = df.groupby("date")[col]
    return pd.Series(norm.ppf((g.rank() - 0.5) / g.transform("count")), index=df.index)


def relevance_labels(df: pd.DataFrame, n_levels: int = N_LEVELS) -> pd.Series:
    """日ごとに target を n_levels 段階 (0 が最下位) に分ける."""
    pct = df.groupby("date")["target"].rank(pct=True, method="first")
    return np.minimum((pct * n_levels).astype(int), n_levels - 1)


@dataclass
class RankModel:
    booster: lgb.Booster
    features: list[str]
    objective: str = "rank_regression"
    horizon: int = DEFAULT_HORIZON
    train_period: tuple[str, str] | None = None

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """順位スコア (大きいほど上位). 値そのものより日ごとの順位に意味がある."""
        return pd.Series(self.booster.predict(df[self.features]), index=df.index)

    def feature_importance(self) -> pd.Series:
        imp = self.booster.feature_importance(importance_type="gain")
        return pd.Series(imp, index=self.features).sort_values(ascending=False)

    def save(self, path: str | Path = DEFAULT_MODEL_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model_str": self.booster.model_to_string(),
                    "features": self.features,
                    "objective": self.objective,
                    "horizon": self.horizon,
                    "train_period": self.train_period,
                },
                f,
            )

    @classmethod
    def load(cls, path: str | Path = DEFAULT_MODEL_PATH) -> "RankModel":
        with open(path, "rb") as f:
            d = pickle.load(f)
        return cls(
            booster=lgb.Booster(model_str=d["model_str"]),
            features=d["features"],
            objective=d["objective"],
            horizon=d["horizon"],
            train_period=d["train_period"],
        )


def train(
    df: pd.DataFrame,
    horizon: int = DEFAULT_HORIZON,
    objective: str = "rank_regression",
    rounds: int = DEFAULT_ROUNDS,
    params: dict | None = None,
) -> RankModel:
    """目的変数が確定している行で学習する."""
    if objective not in OBJECTIVES:
        raise ValueError(f"objective は {OBJECTIVES} のどれか: {objective}")
    data = df.dropna(subset=["target"]).sort_values(["date", "security_id"]).reset_index(drop=True)
    if data.empty:
        raise ValueError("学習できるデータがありません (目的変数が確定した行がありません)")
    X = data[MODEL_FEATURES]
    if objective == "rank_regression":
        params = {**DEFAULT_PARAMS, "objective": "regression", **(params or {})}
        dataset = lgb.Dataset(X, gauss_rank(data))
    else:
        params = {**DEFAULT_PARAMS, "objective": "lambdarank", **(params or {})}
        groups = data.groupby("date", sort=False).size().to_numpy()
        dataset = lgb.Dataset(X, relevance_labels(data), group=groups)
    booster = lgb.train(params, dataset, num_boost_round=rounds)
    period = (data["date"].min().strftime("%Y-%m-%d"), data["date"].max().strftime("%Y-%m-%d"))
    return RankModel(booster, MODEL_FEATURES, objective, horizon, period)
