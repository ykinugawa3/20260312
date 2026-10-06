"""調整前株価と分割・配当から調整後株価を計算する.

権利落ち日 d より前の価格に、次の係数を掛けていく (後方調整・配当再投資ベース):
- 分割 (split_ratio = r, 2 株に分割なら 2): 1 / r
- 配当 (1 株あたり D): 1 - D / (権利落ち前日の調整前終値)
調整後終値の変化率は「配当を再投資した場合のトータルリターン」になる。
出来高は分割の分だけ逆に調整する (株数ベースで連続にするため)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_FIELDS = ["open", "high", "low", "close"]


def _map_to_sessions(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """権利落ち日が取引日に無い場合は、その次の取引日に寄せる."""
    sessions = prices[["security_id", "date"]].sort_values("date")
    acts = actions.sort_values("date").rename(columns={"date": "action_date"})
    mapped = pd.merge_asof(
        acts,
        sessions.assign(action_date=sessions["date"]),
        on="action_date",
        by="security_id",
        direction="forward",
    ).dropna(subset=["date"])
    return mapped.groupby(["security_id", "date"], as_index=False).agg(
        split_ratio=("split_ratio", "prod"), dividend=("dividend", "sum")
    )


def adjust_prices(prices: pd.DataFrame, actions: pd.DataFrame | None = None) -> pd.DataFrame:
    """prices に adj_open/adj_high/adj_low/adj_close/adj_volume と adj_factor 列を追加して返す."""
    df = prices.sort_values(["security_id", "date"]).reset_index(drop=True)
    if actions is None or actions.empty:
        df["adj_factor"] = 1.0
        split_factor = pd.Series(1.0, index=df.index)
    else:
        events = _map_to_sessions(df, actions[["security_id", "date", "split_ratio", "dividend"]])
        df = df.merge(events, on=["security_id", "date"], how="left")
        ratio = df["split_ratio"].fillna(1.0).clip(lower=1e-9)
        prev_close = df.groupby("security_id")["close"].shift(1)
        div_factor = (1.0 - df["dividend"].fillna(0.0) / prev_close).where(prev_close > 0, 1.0)
        div_factor = div_factor.clip(lower=1e-6, upper=1.0)
        event_factor = div_factor / ratio
        split_event = 1.0 / ratio
        # 行 t の係数 = t より後のイベント係数の積 (逆順の累積積を 1 つずらす)
        df["adj_factor"] = _future_product(event_factor, df["security_id"])
        split_factor = _future_product(split_event, df["security_id"])
        df = df.drop(columns=["split_ratio", "dividend"])
    for col in PRICE_FIELDS:
        df[f"adj_{col}"] = df[col] * df["adj_factor"]
    df["adj_volume"] = df["volume"] / split_factor
    return df


def _future_product(factor: pd.Series, groups: pd.Series) -> pd.Series:
    log_f = np.log(factor.astype(float))
    rev_cum = log_f[::-1].groupby(groups[::-1]).cumsum()[::-1]
    return np.exp(rev_cum - log_f)
