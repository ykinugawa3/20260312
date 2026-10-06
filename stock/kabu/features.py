"""特徴量と目的変数の生成.

特徴量は「その日の引け後」に分かる値だけで作る (翌営業日以降の価格は使わない).
目的変数は「翌営業日の寄付で買い、horizon 営業日後の寄付で売った」ときの
S&P 500 (SPY) に対する超過リターン. 期間中に上場廃止した銘柄は最後の終値で売れたものとする
(上場廃止の損失を検証から落とさないため).

モデルには日ごとの順位 (0〜1) に直した特徴量を渡す. 相場全体の水準の変化に左右されず、
「その日の中でどの銘柄が相対的に強いか」だけを学習させるため.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kabu.adjust import adjust_prices

BENCHMARK = "SPY"
DEFAULT_HORIZON = 20
MIN_HISTORY = 250  # 1 年分の価格が無い銘柄は対象外
MIN_PRICE = 5.0    # 低位株 (調整前終値 5 ドル未満) は対象外

RAW_FEATURES = [
    "ret_5", "ret_20", "ret_60", "ret_120", "ret_250", "mom_12_1",
    "ma_gap_20", "ma_gap_50", "ma_gap_200", "pos_52w",
    "vol_20", "vol_60", "downside_vol_60", "beta_250", "max_ret_20",
    "rsi_14", "bb_pos_20", "volume_ratio_5_60", "log_dollar_volume_60",
]
FEATURES = [f"{f}_rank" for f in RAW_FEATURES]
# セクターは表示・絞り込み用. 特徴量に入れると仮データでは過学習した (セクター効果は Phase 2 で再検討)
MODEL_FEATURES = FEATURES


def _wide(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.pivot(index="date", columns="security_id", values=col).sort_index()


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    diff = close.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    down = (-diff.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def _membership_mask(membership: pd.DataFrame | None, index: pd.DatetimeIndex, columns) -> pd.DataFrame | None:
    """各日付にその銘柄が指数に入っていたか (start_date <= 日付 < end_date)."""
    if membership is None or membership.empty:
        return None
    mask = pd.DataFrame(False, index=index, columns=columns)
    for sid, start, end in membership[["security_id", "start_date", "end_date"]].itertuples(index=False):
        if sid not in mask.columns:
            continue
        end = pd.Timestamp.max if pd.isna(end) else end
        mask.loc[(index >= start) & (index < end), sid] = True
    return mask


def build_features(
    prices: pd.DataFrame,
    actions: pd.DataFrame | None = None,
    membership: pd.DataFrame | None = None,
    horizon: int = DEFAULT_HORIZON,
    benchmark: str = BENCHMARK,
) -> pd.DataFrame:
    """日付 × 銘柄の特徴量表を返す.

    prices: kabu.db.load_prices の戻り値 (調整前日足 + ticker, sector).
    戻り値の target は最新の horizon+1 営業日分は NaN (まだ結果が出ていない).
    """
    adj = adjust_prices(prices, actions)
    adj["dollar_volume"] = adj["close"] * adj["volume"]
    bench_ids = adj.loc[adj["ticker"] == benchmark, "security_id"].unique()
    if len(bench_ids) == 0:
        raise ValueError(f"ベンチマーク {benchmark} の株価がありません (yfinance 取得時は自動で追加されます)")
    bench_id = bench_ids[0]

    close = _wide(adj, "adj_close")
    open_ = _wide(adj, "adj_open").fillna(close)
    raw_close = _wide(adj, "close")
    dvol = _wide(adj, "dollar_volume")
    logret = np.log(close / close.shift(1))
    bench_ret = logret[bench_id]

    f: dict[str, pd.DataFrame] = {}
    for n in (5, 20, 60, 120, 250):
        f[f"ret_{n}"] = close / close.shift(n) - 1
    f["mom_12_1"] = close.shift(20) / close.shift(250) - 1
    for n in (20, 50, 200):
        f[f"ma_gap_{n}"] = close / close.rolling(n, min_periods=int(n * 0.8)).mean() - 1
    hi = close.rolling(250, min_periods=200).max()
    lo = close.rolling(250, min_periods=200).min()
    f["pos_52w"] = (close - lo) / (hi - lo).replace(0, np.nan)
    f["vol_20"] = logret.rolling(20, min_periods=15).std()
    f["vol_60"] = logret.rolling(60, min_periods=45).std()
    f["downside_vol_60"] = np.sqrt((logret.clip(upper=0) ** 2).rolling(60, min_periods=45).mean())
    cov = logret.rolling(250, min_periods=120).cov(bench_ret)
    f["beta_250"] = cov.div(bench_ret.rolling(250, min_periods=120).var(), axis=0)
    f["max_ret_20"] = logret.rolling(20, min_periods=15).max()
    f["rsi_14"] = _rsi(close)
    ma20 = close.rolling(20, min_periods=15).mean()
    f["bb_pos_20"] = (close - ma20) / (2 * close.rolling(20, min_periods=15).std())
    f["volume_ratio_5_60"] = dvol.rolling(5, min_periods=3).mean() / dvol.rolling(60, min_periods=45).mean()
    f["log_dollar_volume_60"] = np.log(dvol.rolling(60, min_periods=45).mean().replace(0, np.nan))

    # 目的変数: 翌営業日寄付 → horizon 営業日後の寄付. 途中で廃止なら最後の終値で清算
    entry = open_.shift(-1)
    exit_ = open_.shift(-(1 + horizon)).fillna(close.ffill().shift(-(1 + horizon)))
    # 最新の horizon+1 日は結果未確定 (ffill で埋まった値も使わない)
    exit_.iloc[len(exit_) - (1 + horizon):] = np.nan
    fwd = exit_ / entry - 1
    fwd_bench = fwd[bench_id]

    history = close.notna().cumsum()
    eligible = close.notna() & (history >= MIN_HISTORY) & (raw_close >= MIN_PRICE)
    eligible = eligible.drop(columns=bench_id)
    mask = _membership_mask(membership, close.index, eligible.columns)
    if mask is not None:
        eligible &= mask

    stacked = eligible.stack()
    idx = stacked[stacked].index
    out = pd.DataFrame(index=idx)
    for name in RAW_FEATURES:
        out[name] = f[name].stack(future_stack=True).reindex(idx)
    out["fwd_return"] = fwd.stack(future_stack=True).reindex(idx)
    out["bench_return"] = fwd_bench.reindex(idx.get_level_values("date")).to_numpy()
    out["target"] = out["fwd_return"] - out["bench_return"]
    out["close"] = raw_close.stack(future_stack=True).reindex(idx)
    out = out.reset_index()

    info = prices.drop_duplicates("security_id")[["security_id", "ticker", "sector"]]
    out = out.merge(info, on="security_id", how="left")
    out["sector"] = out["sector"].fillna("Unknown")
    ranks = out.groupby("date")[RAW_FEATURES].rank(pct=True)
    for name in RAW_FEATURES:
        out[f"{name}_rank"] = ranks[name]
    return out.sort_values(["date", "security_id"]).reset_index(drop=True)
