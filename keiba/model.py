"""LightGBM による単勝勝率予測モデル.

二値分類 (1 着か否か) で学習し、推論時にレース内で確率の合計が 1 になるよう正規化する。
学習期間の末尾を較正用に取り分け、RaceCalibrator で市場確率と組み合わせた較正済み勝率も出す。
"""

from __future__ import annotations

import pickle
from dataclasses import asdict, dataclass, field
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import log_loss, roc_auc_score

from keiba.calibration import RaceCalibrator, market_prob
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
    calibrator: RaceCalibrator | None = None

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.features].copy()
        for col, cats in self.categories.items():
            values = X[col].astype(object)
            # 学習時に無かった値 (新しい競馬場など) は欠損として扱う
            X[col] = pd.Categorical(values.where(values.isin(cats)), categories=cats)
        return X

    def predict_raw(self, df: pd.DataFrame) -> pd.Series:
        """モデル単体の勝率 (レース内で合計 1 に正規化)."""
        raw = self.booster.predict(self._prepare(df))
        s = pd.Series(raw, index=df.index)
        return s / s.groupby(df["race_id"]).transform("sum")

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """較正済みの勝率. 較正器が無ければ predict_raw と同じ."""
        raw = self.predict_raw(df)
        if self.calibrator is None:
            return raw
        return self.calibrator.transform(raw, df["odds"], df["race_id"])

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
                    "calibrator": asdict(self.calibrator) if self.calibrator else None,
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
            calibrator=RaceCalibrator(**d["calibrator"]) if d.get("calibrator") else None,
        )


def split_by_date(df: pd.DataFrame, test_start: str | pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    test_start = pd.Timestamp(test_start)
    return df[df["date"] < test_start], df[df["date"] >= test_start]


def _date_at_fraction(df: pd.DataFrame, fraction: float) -> pd.Timestamp:
    dates = df["date"].drop_duplicates().sort_values()
    return dates.iloc[min(int(len(dates) * fraction), len(dates) - 1)]


def _fit_booster(df: pd.DataFrame, params: dict, num_boost_round: int, valid_fraction: float | None) -> WinModel:
    """valid_fraction があれば末尾で early stopping して最適ラウンド数を決め、全体で再学習する."""
    categories = {c: sorted(df[c].dropna().astype(str).unique().tolist()) for c in CATEGORICAL_FEATURES}
    model = WinModel(booster=None, features=list(FEATURES), categories=categories)  # type: ignore[arg-type]
    if valid_fraction:
        tr, va = split_by_date(df, _date_at_fraction(df, 1 - valid_fraction))
        dtrain = lgb.Dataset(model._prepare(tr), tr["is_win"])
        dvalid = lgb.Dataset(model._prepare(va), va["is_win"], reference=dtrain)
        es = lgb.train(
            params, dtrain, num_boost_round=num_boost_round, valid_sets=[dvalid],
            callbacks=[lgb.early_stopping(100, verbose=False)],
        )
        num_boost_round = es.best_iteration or num_boost_round
    dall = lgb.Dataset(model._prepare(df), df["is_win"])
    model.booster = lgb.train(params, dall, num_boost_round=num_boost_round)
    model.train_period = (f"{df['date'].min():%Y-%m-%d}", f"{df['date'].max():%Y-%m-%d}")
    return model


def train(
    df: pd.DataFrame,
    params: dict | None = None,
    num_boost_round: int = 2000,
    valid_fraction: float = 0.15,
    calib_fraction: float = 0.2,
    use_market: bool = True,
) -> WinModel:
    """確定済みレースで学習する.

    calib_fraction > 0 のとき、期間末尾をいったん学習から外して較正器を当て、
    その後に全期間で学習し直したモデルへ較正器を付ける。
    """
    df = df[df["finished"]].sort_values("date")
    params = {**DEFAULT_PARAMS, **(params or {})}
    if not calib_fraction:
        return _fit_booster(df, params, num_boost_round, valid_fraction)

    base_df, calib_df = split_by_date(df, _date_at_fraction(df, 1 - calib_fraction))
    base = _fit_booster(base_df, params, num_boost_round, valid_fraction)
    calibrator = RaceCalibrator(use_market=use_market).fit(
        base.predict_raw(calib_df), calib_df["odds"], calib_df["race_id"], calib_df["is_win"]
    )
    final = _fit_booster(df, params, base.booster.current_iteration(), valid_fraction=None)
    final.calibrator = calibrator
    return final


def roi(bets: pd.DataFrame) -> float:
    """1 点同額買いの単勝回収率."""
    if bets.empty:
        return float("nan")
    return float((bets["is_win"] * bets["odds"]).sum() / len(bets))


def evaluate(model: WinModel, df: pd.DataFrame) -> dict:
    """確定済みレースで予測精度と単純な単勝戦略の回収率を評価する."""
    df = df[df["finished"]].copy()
    df["raw"] = model.predict_raw(df)
    df["pred"] = model.predict(df)
    df["market_prob"] = market_prob(df["odds"], df["race_id"])
    y = df["is_win"].to_numpy()

    def ll(col: str) -> float:
        return float(log_loss(y, df[col].clip(1e-6, 1 - 1e-6)))

    top_pick = df.loc[df.groupby("race_id")["pred"].idxmax()]
    favorite = df.loc[df.groupby("race_id")["market_prob"].idxmax()]

    return {
        "n_races": int(df["race_id"].nunique()),
        "n_entries": int(len(df)),
        "logloss_raw": ll("raw"),
        "logloss_model": ll("pred"),
        "logloss_market": ll("market_prob"),
        "auc_raw": float(roc_auc_score(y, df["raw"])),
        "auc_model": float(roc_auc_score(y, df["pred"])),
        "auc_market": float(roc_auc_score(y, df["market_prob"])),
        "top_pick_hit_rate": float(top_pick["is_win"].mean()),
        "top_pick_roi": roi(top_pick),
        "favorite_hit_rate": float(favorite["is_win"].mean()),
        "favorite_roi": roi(favorite),
        "calibrator": model.calibrator,
    }


def mark_symbols(pred: pd.Series, race_id: pd.Series) -> pd.Series:
    """レース内の予測順位に応じた印 (◎○▲△)."""
    rank = pred.groupby(race_id).rank(ascending=False, method="first")
    symbols = {1: "◎", 2: "○", 3: "▲", 4: "△", 5: "△"}
    return rank.map(symbols).fillna("")


def predict_races(model: WinModel, df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["model_prob"] = model.predict_raw(out)
    out["win_prob"] = model.predict(out)
    out["market_prob"] = market_prob(out["odds"], out["race_id"])
    out["expected_value"] = out["win_prob"] * out["odds"]
    out["mark"] = mark_symbols(out["win_prob"], out["race_id"])
    out["pred_rank"] = out.groupby("race_id")["win_prob"].rank(ascending=False, method="first").astype(int)
    return out.sort_values(["date", "race_id", "pred_rank"])
