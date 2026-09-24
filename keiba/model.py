"""LightGBM による単勝勝率予測モデル.

二値分類 (1 着か否か) で学習し、推論時にレース内で確率の合計が 1 になるよう正規化する。
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import log_loss, roc_auc_score

from keiba.features import CATEGORICAL_FEATURES, FEATURES

DEFAULT_MODEL_PATH = Path("models/win_model.pkl")

DEFAULT_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.03,
    "num_leaves": 31,
    "min_child_samples": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "seed": 42,
}


@dataclass
class WinModel:
    booster: lgb.Booster
    features: list[str]
    categories: dict[str, list] = field(default_factory=dict)
    train_period: tuple[str, str] | None = None

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.features].copy()
        for col, cats in self.categories.items():
            X[col] = pd.Categorical(X[col].astype(object), categories=cats)
        return X

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """レース内で正規化した勝率を返す."""
        raw = self.booster.predict(self._prepare(df))
        s = pd.Series(raw, index=df.index)
        return s / s.groupby(df["race_id"]).transform("sum")

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
                    "categories": self.categories,
                    "train_period": self.train_period,
                },
                f,
            )

    @classmethod
    def load(cls, path: str | Path = DEFAULT_MODEL_PATH) -> "WinModel":
        with open(path, "rb") as f:
            d = pickle.load(f)
        return cls(
            booster=lgb.Booster(model_str=d["model_str"]),
            features=d["features"],
            categories=d["categories"],
            train_period=d["train_period"],
        )


def split_by_date(df: pd.DataFrame, test_start: str | pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    test_start = pd.Timestamp(test_start)
    return df[df["date"] < test_start], df[df["date"] >= test_start]


def train(
    df: pd.DataFrame,
    params: dict | None = None,
    num_boost_round: int = 2000,
    valid_fraction: float = 0.15,
) -> WinModel:
    """確定済みレースで学習する. 期間の末尾 valid_fraction を early stopping 用に使う."""
    df = df[df["finished"]].sort_values("date")
    params = {**DEFAULT_PARAMS, **(params or {})}
    dates = df["date"].drop_duplicates().sort_values()
    valid_start = dates.iloc[int(len(dates) * (1 - valid_fraction))]
    tr, va = split_by_date(df, valid_start)

    categories = {c: sorted(df[c].dropna().astype(str).unique().tolist()) for c in CATEGORICAL_FEATURES}
    model = WinModel(booster=None, features=list(FEATURES), categories=categories)  # type: ignore[arg-type]

    dtrain = lgb.Dataset(model._prepare(tr), tr["is_win"])
    dvalid = lgb.Dataset(model._prepare(va), va["is_win"], reference=dtrain)
    booster = lgb.train(
        params, dtrain, num_boost_round=num_boost_round, valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    # 最適ラウンド数で全期間を再学習
    dall = lgb.Dataset(model._prepare(df), df["is_win"])
    model.booster = lgb.train(params, dall, num_boost_round=booster.best_iteration or num_boost_round)
    model.train_period = (f"{df['date'].min():%Y-%m-%d}", f"{df['date'].max():%Y-%m-%d}")
    return model


def evaluate(model: WinModel, df: pd.DataFrame) -> dict:
    """確定済みレースで予測精度と単純な単勝戦略の回収率を評価する."""
    df = df[df["finished"]].copy()
    df["pred"] = model.predict(df)
    y = df["is_win"].to_numpy()

    # 市場 (オッズ) が示す確率. 比較用のベースライン
    implied = 1 / df["odds"]
    df["market_prob"] = implied / implied.groupby(df["race_id"]).transform("sum")

    top_pick = df.loc[df.groupby("race_id")["pred"].idxmax()]
    favorite = df.loc[df.groupby("race_id")["market_prob"].idxmax()]
    df["ev"] = df["pred"] * df["odds"]
    value_bets = df[df["ev"] > 1.2]

    def roi(bets: pd.DataFrame) -> float:
        if bets.empty:
            return float("nan")
        return float((bets["is_win"] * bets["odds"]).sum() / len(bets))

    return {
        "n_races": int(df["race_id"].nunique()),
        "n_entries": int(len(df)),
        "logloss_model": float(log_loss(y, df["pred"].clip(1e-6, 1 - 1e-6))),
        "logloss_market": float(log_loss(y, df["market_prob"].clip(1e-6, 1 - 1e-6))),
        "auc_model": float(roc_auc_score(y, df["pred"])),
        "auc_market": float(roc_auc_score(y, df["market_prob"])),
        "top_pick_hit_rate": float(top_pick["is_win"].mean()),
        "top_pick_roi": roi(top_pick),
        "favorite_hit_rate": float(favorite["is_win"].mean()),
        "favorite_roi": roi(favorite),
        "ev_over_1.2_bets": int(len(value_bets)),
        "ev_over_1.2_roi": roi(value_bets),
    }


def mark_symbols(pred: pd.Series, race_id: pd.Series) -> pd.Series:
    """レース内の予測順位に応じた印 (◎○▲△)."""
    rank = pred.groupby(race_id).rank(ascending=False, method="first")
    symbols = {1: "◎", 2: "○", 3: "▲", 4: "△", 5: "△"}
    return rank.map(symbols).fillna("")


def predict_races(model: WinModel, df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["win_prob"] = model.predict(out)
    out["expected_value"] = out["win_prob"] * out["odds"]
    out["mark"] = mark_symbols(out["win_prob"], out["race_id"])
    out["pred_rank"] = out.groupby("race_id")["win_prob"].rank(ascending=False, method="first").astype(int)
    return out.sort_values(["date", "race_id", "pred_rank"])

