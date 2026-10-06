"""外部データの取得 (Phase 1: yfinance と Wikipedia の S&P 500 構成銘柄一覧).

yfinance は非公式のツールで、突然使えなくなることや、上場廃止した銘柄を取れないことがある.
**現在の構成銘柄だけで過去を検証すると生存者バイアスで成績が過大評価される** ため、
Phase 1 では動作確認・開発用とし、本格的な検証は上場廃止銘柄を含む有料データで行う (Phase 2).

yfinance の Close・Volume・Dividends は分割調整済みの値なので、
分割の記録 (Stock Splits) を使って調整前の値に戻してから保存する (kabu.db の方針).
"""

from __future__ import annotations

import io
import urllib.request

import numpy as np
import pandas as pd

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "kabu/0.1 (personal research tool)"
BENCHMARK = "SPY"


def to_yahoo_symbol(ticker: str) -> str:
    """BRK.B → BRK-B (Yahoo の表記)."""
    return ticker.replace(".", "-")


def from_yahoo_symbol(symbol: str) -> str:
    return symbol.replace("-", ".")


def unadjust_yfinance(ticker: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """yfinance の 1 銘柄分 (auto_adjust=False, actions=True) を調整前の prices / actions に変換する."""
    df = df.dropna(subset=["Close"]).sort_index()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"]), pd.DataFrame(
            columns=["ticker", "date", "split_ratio", "dividend"]
        )
    splits = df.get("Stock Splits", pd.Series(0.0, index=df.index)).fillna(0.0)
    ratio = splits.where(splits > 0, 1.0).astype(float)
    # 行 t の係数 = t より後の分割比率の積
    log_r = np.log(ratio)
    future = np.exp(log_r[::-1].cumsum()[::-1] - log_r)
    dates = pd.DatetimeIndex(df.index).tz_localize(None).strftime("%Y-%m-%d")
    prices = pd.DataFrame({
        "ticker": ticker,
        "date": dates,
        "open": df["Open"].to_numpy() * future.to_numpy(),
        "high": df["High"].to_numpy() * future.to_numpy(),
        "low": df["Low"].to_numpy() * future.to_numpy(),
        "close": df["Close"].to_numpy() * future.to_numpy(),
        "volume": df["Volume"].to_numpy() / future.to_numpy(),
    })
    dividends = df.get("Dividends", pd.Series(0.0, index=df.index)).fillna(0.0)
    actions = pd.DataFrame({
        "ticker": ticker,
        "date": dates,
        "split_ratio": ratio.to_numpy(),
        "dividend": dividends.to_numpy() * future.to_numpy(),
    })
    actions = actions[(actions["split_ratio"] != 1) | (actions["dividend"] != 0)]
    return prices, actions.reset_index(drop=True)


def fetch_yfinance(
    tickers: list[str], start: str, end: str | None = None, include_benchmark: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """yfinance から日足と分割・配当を取得する. (prices, actions, 取得に失敗した ticker) を返す."""
    import yfinance as yf

    tickers = list(dict.fromkeys([*tickers, BENCHMARK] if include_benchmark else tickers))
    symbols = [to_yahoo_symbol(t) for t in tickers]
    raw = yf.download(
        symbols, start=start, end=end, auto_adjust=False, actions=True,
        group_by="ticker", progress=False, threads=True,
    )
    all_prices, all_actions, failed = [], [], []
    for ticker, symbol in zip(tickers, symbols):
        try:
            frame = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            failed.append(ticker)
            continue
        p, a = unadjust_yfinance(ticker, frame)
        if p.empty:
            failed.append(ticker)
            continue
        all_prices.append(p)
        all_actions.append(a)
    prices = pd.concat(all_prices, ignore_index=True) if all_prices else pd.DataFrame()
    actions = pd.concat(all_actions, ignore_index=True) if all_actions else pd.DataFrame()
    return prices, actions, failed


def parse_sp500_table(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wikipedia の構成銘柄表を securities / membership に変換する (現在の構成銘柄のみ)."""
    securities = pd.DataFrame({
        "ticker": table["Symbol"].astype(str).str.strip(),
        "name": table["Security"],
        "sector": table["GICS Sector"],
    })
    added = pd.to_datetime(table.get("Date added"), errors="coerce")
    membership = pd.DataFrame({
        "ticker": securities["ticker"],
        "start_date": added.fillna(pd.Timestamp("1957-03-04")).dt.strftime("%Y-%m-%d"),
        "end_date": None,
    })
    return securities, membership


def fetch_sp500_list() -> tuple[pd.DataFrame, pd.DataFrame]:
    req = urllib.request.Request(SP500_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")
    table = pd.read_html(io.StringIO(html))[0]
    return parse_sp500_table(table)
