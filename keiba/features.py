"""特徴量生成.

すべての履歴系特徴量は「そのレースより前の日付」の結果だけから計算する (データリーク防止)。
結果未確定の行 (出馬表) にも同じ手順で特徴量を付与できる。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CATEGORICAL_FEATURES = ["course", "surface", "track_condition", "race_class", "sex"]

NUMERIC_FEATURES = [
    # レース条件
    "distance", "num_runners", "frame_number", "horse_number", "weight_carried",
    # 馬の状態
    "age", "horse_weight", "horse_weight_diff", "days_since_last",
    # 馬の過去成績
    "n_past_races", "last_finish", "last_finish_ratio", "avg_finish_ratio_5",
    "best_finish_ratio_5", "win_rate_past", "top3_rate_past",
    "avg_time_diff_5", "last_time_diff", "avg_last3f_rank_ratio_5",
    "same_surface_finish_ratio", "same_dist_finish_ratio", "same_going_finish_ratio", "dist_change",
    # 人
    "jockey_win_rate", "jockey_top3_rate", "jockey_rides",
    "trainer_win_rate", "trainer_top3_rate", "jockey_changed",
    # レース内相対値
    "rank_in_race_avg_finish_ratio_5", "rank_in_race_avg_time_diff_5",
    "rank_in_race_jockey_win_rate",
]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# 経験の少ない騎手/調教師の勝率を全体平均へ縮める (ベイズ平均) ための事前サンプル数
_PRIOR_N = 30


def _dist_band(distance: pd.Series) -> pd.Series:
    return pd.cut(distance, [0, 1400, 1800, 2200, 9999], labels=["S", "M", "I", "L"]).astype(str)


def _add_race_level(df: pd.DataFrame) -> pd.DataFrame:
    df["finished"] = df["finish_position"].notna()
    df["num_runners"] = df.groupby("race_id")["horse_number"].transform("size")
    df["finish_ratio"] = (df["finish_position"] - 1) / (df["num_runners"] - 1).clip(lower=1)
    df["is_win"] = (df["finish_position"] == 1).astype(float).where(df["finished"])
    df["is_top3"] = (df["finish_position"] <= 3).astype(float).where(df["finished"])
    winner_time = df.groupby("race_id")["time_sec"].transform("min")
    df["time_diff"] = df["time_sec"] - winner_time
    df["last3f_rank_ratio"] = (
        (df.groupby("race_id")["last_3f"].rank(method="min") - 1)
        / (df["num_runners"] - 1).clip(lower=1)
    )
    df["dist_band"] = _dist_band(df["distance"])
    df["going"] = np.where(df["track_condition"] == "良", "dry", "wet")
    return df


def _add_horse_history(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["horse_id", "date", "race_id"]).copy()
    g = df.groupby("horse_id", sort=False)

    def past(col: str, window: int | None, fn: str) -> pd.Series:
        shifted = g[col].shift(1)
        grp = shifted.groupby(df["horse_id"], sort=False)
        roll = grp.rolling(window, min_periods=1) if window else grp.expanding(min_periods=1)
        return getattr(roll, fn)().reset_index(level=0, drop=True)

    df["n_past_races"] = g["finished"].cumsum() - df["finished"].astype(int)
    df["last_finish"] = g["finish_position"].shift(1)
    df["last_finish_ratio"] = g["finish_ratio"].shift(1)
    df["avg_finish_ratio_5"] = past("finish_ratio", 5, "mean")
    df["best_finish_ratio_5"] = past("finish_ratio", 5, "min")
    df["win_rate_past"] = past("is_win", None, "mean")
    df["top3_rate_past"] = past("is_top3", None, "mean")
    df["avg_time_diff_5"] = past("time_diff", 5, "mean")
    df["last_time_diff"] = g["time_diff"].shift(1)
    df["avg_last3f_rank_ratio_5"] = past("last3f_rank_ratio", 5, "mean")
    df["days_since_last"] = (df["date"] - g["date"].shift(1)).dt.days
    df["dist_change"] = df["distance"] - g["distance"].shift(1)
    df["jockey_changed"] = (df["jockey_id"] != g["jockey_id"].shift(1)).astype(float)
    df.loc[df["n_past_races"] == 0, "jockey_changed"] = np.nan

    # 同じ馬場 / 同じ距離帯 / 同じ馬場状態 (良・道悪) での過去平均着順比
    for key, name in (
        ("surface", "same_surface_finish_ratio"),
        ("dist_band", "same_dist_finish_ratio"),
        ("going", "same_going_finish_ratio"),
    ):
        sub_g = df.groupby(["horse_id", key], sort=False)["finish_ratio"]
        shifted = sub_g.shift(1)
        df[name] = (
            shifted.groupby([df["horse_id"], df[key]], sort=False)
            .expanding(min_periods=1).mean()
            .reset_index(level=[0, 1], drop=True)
        )
    return df


def _add_person_stats(df: pd.DataFrame, id_col: str, prefix: str) -> pd.DataFrame:
    """騎手/調教師の、その日より前までの累積成績 (同日のレースは含めない)."""
    fin = df[df["finished"]]
    daily = fin.groupby([id_col, "date"]).agg(
        rides=("is_win", "size"), wins=("is_win", "sum"), top3=("is_top3", "sum")
    ).reset_index().sort_values([id_col, "date"])
    cum = daily.groupby(id_col)[["rides", "wins", "top3"]].cumsum()
    daily[["cum_rides", "cum_wins", "cum_top3"]] = cum.to_numpy()
    daily = daily.drop(columns=["rides", "wins", "top3"])

    keys = df[[id_col, "date"]].drop_duplicates().sort_values("date")
    # その日「より前」の累積値を取る
    merged = pd.merge_asof(
        keys, daily.sort_values("date"), on="date", by=id_col,
        allow_exact_matches=False,
    ).fillna({"cum_rides": 0, "cum_wins": 0, "cum_top3": 0})

    # 全体の事前分布 (全期間で計算すると未来情報になるので一般的な値を固定で使う)
    prior_win, prior_top3 = 0.08, 0.24
    merged[f"{prefix}_win_rate"] = (merged["cum_wins"] + prior_win * _PRIOR_N) / (merged["cum_rides"] + _PRIOR_N)
    merged[f"{prefix}_top3_rate"] = (merged["cum_top3"] + prior_top3 * _PRIOR_N) / (merged["cum_rides"] + _PRIOR_N)
    merged[f"{prefix}_rides"] = merged["cum_rides"]
    cols = [id_col, "date", f"{prefix}_win_rate", f"{prefix}_top3_rate", f"{prefix}_rides"]
    return df.merge(merged[cols], on=[id_col, "date"], how="left")


def _add_in_race_ranks(df: pd.DataFrame) -> pd.DataFrame:
    specs = {
        "avg_finish_ratio_5": True,   # 小さいほど良い
        "avg_time_diff_5": True,
        "jockey_win_rate": False,     # 大きいほど良い
    }
    for col, ascending in specs.items():
        rank = df.groupby("race_id")[col].rank(ascending=ascending, method="average")
        df[f"rank_in_race_{col}"] = rank / df["num_runners"]
    return df


def build_features(raw: pd.DataFrame) -> pd.DataFrame:
    """load_joined() の結果から特徴量付きの DataFrame を作る."""
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = _add_race_level(df)
    df = _add_horse_history(df)
    df = _add_person_stats(df, "jockey_id", "jockey")
    df = _add_person_stats(df, "trainer_id", "trainer")
    df = _add_in_race_ranks(df)
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("category")
    return df.sort_values(["date", "race_id", "horse_number"]).reset_index(drop=True)
