"""動作確認用の合成米国株データ生成器.

実データ (yfinance など) が無い環境でもパイプライン全体を試せるよう、
次の性質を持つ日足を作る:

- リターン = ベータ × 市場 + セクター要因 + 銘柄固有要因
- 銘柄ごとの「隠れた期待リターン (ドリフト)」がゆっくり変化する (半減期 約 1 年).
  過去リターンにドリフトが表れるので、モメンタムに弱い予測力が生まれる
- 直近 1 週間の銘柄固有の値動きは少し戻る (短期反転)
- ボラティリティの高い銘柄ほどドリフトがやや低い (低ボラ効果)
- 株式分割・配当・上場廃止 (株価が大きく下落した銘柄) ・新規上場がある
- 時価総額上位を年 4 回入れ替える仮の指数 "SP500" の構成銘柄履歴がある

予測力は現実の株式市場に近い弱さ (単純なファクターの日次 IC が 0.03〜0.06 程度) になるよう設定してある。
**ここで出るバックテスト成績は仮データの設定次第であり、実データでの成績を意味しない。**
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SECTORS = [
    "Information Technology", "Health Care", "Financials", "Consumer Discretionary",
    "Communication Services", "Industrials", "Consumer Staples", "Energy",
    "Utilities", "Real Estate", "Materials",
]
BENCHMARK = "SPY"
INDEX_NAME = "SP500"

MARKET_VOL = 0.011          # 市場の日次ボラティリティ
MARKET_DRIFT = 0.0003       # 市場の日次期待リターン (年率 約 7.5%)
SECTOR_VOL = 0.006
DRIFT_SD = 0.10 / 252       # 隠れたドリフトの散らばり (年率 10%)
DRIFT_RHO = 0.5 ** (1 / 252)  # ドリフトの持続性 (半減期 1 年)
REVERSAL = 0.04             # 直近 5 日の固有リターンが翌日に戻る割合 (1 日あたり)
LOW_VOL_PENALTY = 0.05 / 252  # 固有ボラが 1 標準偏差高いと年率 5% 低い
DELIST_DRAWDOWN = 0.85      # 高値から 85% 下落したら上場廃止
SPLIT_PRICE = 400.0         # この株価を超えたら一定確率で分割
DIVIDEND_YIELD_MAX = 0.04


def generate(
    n_stocks: int = 150,
    n_days: int = 1500,
    index_size: int = 100,
    end: str = "2026-09-30",
    new_listings: int = 20,
    seed: int = 0,
) -> dict[str, pd.DataFrame]:
    """securities / prices / actions / membership の DataFrame を返す (ticker で銘柄を識別)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=n_days)
    total = n_stocks + new_listings

    tickers = [f"S{i:03d}" for i in range(total)]
    sector_idx = rng.integers(0, len(SECTORS), total)
    beta = rng.normal(1.0, 0.25, total).clip(0.3, 2.0)
    idio_vol = rng.lognormal(np.log(0.017), 0.35, total)
    vol_z = (np.log(idio_vol) - np.log(0.017)) / 0.35
    price = rng.lognormal(np.log(60), 0.8, total)
    shares = rng.lognormal(np.log(3e8), 1.0, total)
    div_yield = rng.uniform(0, DIVIDEND_YIELD_MAX, total) * (rng.random(total) < 0.7)
    drift = rng.normal(0, DRIFT_SD, total)
    listed_at = np.zeros(total, dtype=int)
    listed_at[n_stocks:] = rng.integers(60, n_days - 60, new_listings)

    alive = listed_at == 0
    delisted_at = np.full(total, -1)
    peak = price.copy()
    recent_idio = np.zeros((5, total))
    spy = 300.0

    price_rows, action_rows, spy_rows = [], [], []
    for t, date in enumerate(dates):
        newly = listed_at == t
        alive |= newly & (t > 0)
        m = rng.normal(MARKET_DRIFT, MARKET_VOL)
        sector_ret = rng.normal(0, SECTOR_VOL, len(SECTORS))
        drift = DRIFT_RHO * drift + np.sqrt(1 - DRIFT_RHO ** 2) * rng.normal(0, DRIFT_SD, total)
        idio = rng.normal(0, idio_vol)
        expected = drift - LOW_VOL_PENALTY * vol_z - REVERSAL * recent_idio.sum(axis=0)
        ret = beta * m + sector_ret[sector_idx] + expected + idio
        recent_idio = np.roll(recent_idio, 1, axis=0)
        recent_idio[0] = idio

        # 分割・配当は当日の寄付前に起きる (権利落ち)
        split = alive & (price > SPLIT_PRICE) & (rng.random(total) < 0.02)
        ratio = np.where(split, rng.choice([2.0, 3.0, 4.0], total), 1.0)
        pays = alive & (div_yield > 0) & (t % 63 == 21)
        dividend = np.where(pays, price * div_yield / 4, 0.0)
        base = (price - dividend) / ratio  # 権利落ち後の前日終値相当
        peak = peak * base / price
        shares = shares * ratio
        price = base * np.exp(ret)
        peak = np.maximum(peak, price)

        # 寄付は前日終値から当日リターンの一部だけ動いた位置
        open_ = base * np.exp(ret * rng.uniform(0.2, 0.6, total) + rng.normal(0, 0.003, total))
        hi = np.maximum(open_, price) * np.exp(np.abs(rng.normal(0, 0.006, total)))
        lo = np.minimum(open_, price) * np.exp(-np.abs(rng.normal(0, 0.006, total)))
        volume = shares * rng.lognormal(np.log(0.006), 0.4, total) * (1 + 20 * np.abs(idio))

        for i in np.flatnonzero(alive):
            price_rows.append((tickers[i], date, open_[i], hi[i], lo[i], price[i], round(volume[i])))
            if split[i] or dividend[i] > 0:
                action_rows.append((tickers[i], date, ratio[i], dividend[i]))

        # SPY は上場中の銘柄の平均リターンで動かす (銘柄全体の平均的な超過リターンが 0 付近になる)
        spy_ret = float(np.mean(np.exp(ret[alive]) - 1)) if alive.any() else m
        spy_open = spy * np.exp(0.4 * spy_ret)
        spy = spy * (1 + spy_ret)
        spy_rows.append((BENCHMARK, date, spy_open, max(spy, spy_open) * 1.003, min(spy, spy_open) * 0.997, spy, 8e7))

        dead = alive & (price < peak * (1 - DELIST_DRAWDOWN))
        delisted_at[dead] = t
        alive &= ~dead

    securities = pd.DataFrame({
        "ticker": tickers,
        "name": [f"Sample Corp {i:03d}" for i in range(total)],
        "sector": [SECTORS[s] for s in sector_idx],
        "listed_date": [dates[max(t, 0)].strftime("%Y-%m-%d") for t in listed_at],
        "delisted_date": [dates[t].strftime("%Y-%m-%d") if t >= 0 else None for t in delisted_at],
    })
    securities = pd.concat([securities, pd.DataFrame([{
        "ticker": BENCHMARK, "name": "Sample S&P 500 ETF", "sector": "ETF",
        "listed_date": dates[0].strftime("%Y-%m-%d"), "delisted_date": None,
    }])], ignore_index=True)

    cols = ["ticker", "date", "open", "high", "low", "close", "volume"]
    prices = pd.DataFrame(price_rows + spy_rows, columns=cols)
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
    actions = pd.DataFrame(action_rows, columns=["ticker", "date", "split_ratio", "dividend"])
    actions["date"] = actions["date"].dt.strftime("%Y-%m-%d")
    membership = _index_membership(prices[prices["ticker"] != BENCHMARK], dates, index_size)
    return {"securities": securities, "prices": prices, "actions": actions, "membership": membership}


def _index_membership(prices: pd.DataFrame, dates: pd.DatetimeIndex, size: int) -> pd.DataFrame:
    """四半期ごとに時価総額 (終値 × 出来高の代用) 上位 size 銘柄を採用する。廃止銘柄は廃止日に除外."""
    px = prices.assign(date=pd.to_datetime(prices["date"]))
    px["dollar_volume"] = px["close"] * px["volume"]
    rebalance = dates[::63]
    last_date = px.groupby("ticker")["date"].max()
    periods: dict[str, list[list]] = {}
    current: set[str] = set()
    for i, d in enumerate(rebalance):
        window = px[(px["date"] <= d) & (px["date"] > d - pd.Timedelta(days=90))]
        size_proxy = window.groupby("ticker")["dollar_volume"].mean()
        alive_now = last_date[last_date >= d].index
        top = set(size_proxy[size_proxy.index.isin(alive_now)].nlargest(size).index)
        for t in current - top:
            periods[t][-1][1] = d
        for t in top - current:
            periods.setdefault(t, []).append([d, None])
        current = top
    rows = []
    for t, spans in periods.items():
        for start, end in spans:
            if end is None and last_date[t] < dates[-1]:
                end = last_date[t] + pd.Timedelta(days=1)
            rows.append((t, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d") if end is not None else None))
    return pd.DataFrame(rows, columns=["ticker", "start_date", "end_date"])
