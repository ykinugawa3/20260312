"""取り込み (CSV / 仮データ / 外部ソース共通) とデータチェック.

どの入手先のデータも、ticker で銘柄を識別する次の形に揃えてから import_frames に渡す:
- securities: ticker, name, sector, listed_date, delisted_date
- prices:     ticker, date, open, high, low, close, volume  (調整前の値)
- actions:    ticker, date, split_ratio, dividend           (任意)
- membership: ticker, start_date, end_date                  (任意. 指数の構成銘柄履歴)
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from kabu import db

REQUIRED_PRICE_COLUMNS = ["ticker", "date", "close"]
JUMP_THRESHOLD = 0.5  # 分割の記録が無いのに 1 日で 50% 以上動いたら警告


@dataclass
class ImportReport:
    securities: int = 0
    prices: int = 0
    actions: int = 0
    membership: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"銘柄 {self.securities} / 日足 {self.prices} 行 / 分割・配当 {self.actions} 件 / 指数構成 {self.membership} 件"
        ]
        lines += [f"  警告: {w}" for w in self.warnings]
        return "\n".join(lines)


def _normalize_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df:
            df[c] = pd.to_datetime(df[c]).dt.strftime("%Y-%m-%d").where(df[c].notna(), None)
    return df


def validate_prices(prices: pd.DataFrame, actions: pd.DataFrame | None = None, sessions=None) -> list[str]:
    """取り込み前のチェック. 問題の説明を返す (空なら問題なし).

    sessions に取引日の一覧を渡すと、各銘柄の取引期間内で抜けている日も調べる.
    """
    warnings = []
    missing = [c for c in REQUIRED_PRICE_COLUMNS if c not in prices]
    if missing:
        return [f"必須列がありません: {missing}"]
    p = prices.copy()
    p["date"] = pd.to_datetime(p["date"])
    dup = p.duplicated(["ticker", "date"]).sum()
    if dup:
        warnings.append(f"同じ銘柄・日付の行が {dup} 件重複しています (後の行を採用)")
    bad = (p["close"] <= 0) | p["close"].isna()
    if bad.any():
        warnings.append(f"終値が 0 以下または空欄の行が {int(bad.sum())} 件あります (取り込みません)")
    if {"open", "high", "low"} <= set(p.columns):
        hi_ok = p["high"] >= p[["open", "close"]].max(axis=1) * (1 - 1e-6)
        lo_ok = p["low"] <= p[["open", "close"]].min(axis=1) * (1 + 1e-6)
        n = int((~(hi_ok & lo_ok) & p[["open", "high", "low"]].notna().all(axis=1)).sum())
        if n:
            warnings.append(f"高値・安値と始値・終値の関係がおかしい行が {n} 件あります")
    if "volume" in p:
        n = int((p["volume"] == 0).sum())
        if n:
            warnings.append(f"出来高 0 の行が {n} 件あります")

    p = p[~bad].sort_values(["ticker", "date"])
    ret = p.groupby("ticker")["close"].pct_change()
    jumps = p[ret.abs() > JUMP_THRESHOLD][["ticker", "date"]]
    if actions is not None and not actions.empty:
        split_keys = set(
            zip(actions.loc[actions["split_ratio"] != 1, "ticker"], pd.to_datetime(actions.loc[actions["split_ratio"] != 1, "date"]))
        )
        jumps = jumps[[k not in split_keys for k in zip(jumps["ticker"], jumps["date"])]]
    for t, d in jumps.head(10).itertuples(index=False):
        warnings.append(f"{t} {d:%Y-%m-%d}: 分割の記録が無いのに終値が {JUMP_THRESHOLD:.0%} 以上変化しています")
    if len(jumps) > 10:
        warnings.append(f"(ほか {len(jumps) - 10} 件の急変動)")

    if sessions is not None:
        sessions = pd.DatetimeIndex(sessions)
        gaps = []
        for t, g in p.groupby("ticker")["date"]:
            expected = sessions[(sessions >= g.min()) & (sessions <= g.max())]
            n = len(expected.difference(pd.DatetimeIndex(g)))
            if n:
                gaps.append((t, n))
        for t, n in gaps[:10]:
            warnings.append(f"{t}: 取引日なのにデータが無い日が {n} 日あります")
        if len(gaps) > 10:
            warnings.append(f"(ほか {len(gaps) - 10} 銘柄で欠損あり)")
    return warnings


def import_frames(
    securities: pd.DataFrame | None,
    prices: pd.DataFrame,
    path: str | Path = db.DEFAULT_DB_PATH,
    actions: pd.DataFrame | None = None,
    membership: pd.DataFrame | None = None,
    index_name: str = "SP500",
    sessions=None,
) -> ImportReport:
    report = ImportReport(warnings=validate_prices(prices, actions, sessions))
    if any(w.startswith("必須列") for w in report.warnings):
        raise ValueError(report.warnings[0])

    prices = _normalize_dates(prices, ["date"])
    prices = prices[prices["close"].notna() & (prices["close"] > 0)].drop_duplicates(["ticker", "date"], keep="last")
    prices = prices.reindex(columns=["ticker", *db.PRICE_COLUMNS])

    tickers = pd.DataFrame({"ticker": sorted(set(prices["ticker"]))})
    if securities is not None:
        securities = _normalize_dates(securities, ["listed_date", "delisted_date"])
        tickers = securities.merge(tickers, on="ticker", how="outer")

    with closing(db.connect(path)) as conn:
        ids = db.upsert_securities(conn, tickers)
        report.securities = len(tickers)
        report.prices = db.upsert_prices(conn, prices.assign(security_id=prices["ticker"].map(ids)))
        if actions is not None and not actions.empty:
            acts = _normalize_dates(actions, ["date"]).reindex(columns=["ticker", *db.ACTION_COLUMNS])
            acts["split_ratio"] = acts["split_ratio"].fillna(1.0)
            acts["dividend"] = acts["dividend"].fillna(0.0)
            acts = acts[acts["ticker"].isin(ids)]
            report.actions = db.upsert_actions(conn, acts.assign(security_id=acts["ticker"].map(ids)))
        if membership is not None and not membership.empty:
            mem = _normalize_dates(membership, ["start_date", "end_date"])
            mem = mem[mem["ticker"].isin(ids)]
            report.membership = db.replace_membership(conn, index_name, mem.assign(security_id=mem["ticker"].map(ids)))
        conn.commit()
    return report


def import_csv(
    prices_csv: str | Path,
    path: str | Path = db.DEFAULT_DB_PATH,
    securities_csv: str | Path | None = None,
    actions_csv: str | Path | None = None,
    membership_csv: str | Path | None = None,
    index_name: str = "SP500",
) -> ImportReport:
    """CSV 取り込み. 株価 CSV に split_ratio / dividend 列があれば分割・配当としても取り込む."""
    prices = pd.read_csv(prices_csv)
    actions = pd.read_csv(actions_csv) if actions_csv else None
    if actions is None and {"split_ratio", "dividend"} & set(prices.columns):
        a = prices.reindex(columns=["ticker", "date", "split_ratio", "dividend"])
        a["split_ratio"] = a["split_ratio"].fillna(1.0)
        a["dividend"] = a["dividend"].fillna(0.0)
        actions = a[(a["split_ratio"] != 1) | (a["dividend"] != 0)]
    securities = pd.read_csv(securities_csv) if securities_csv else None
    membership = pd.read_csv(membership_csv) if membership_csv else None
    return import_frames(securities, prices, path, actions, membership, index_name)


def nyse_sessions(start, end):
    """NYSE の取引日一覧 (exchange_calendars が無ければ None)."""
    try:
        import exchange_calendars as xcals
    except ImportError:
        return None
    cal = xcals.get_calendar("XNYS")
    start = max(pd.Timestamp(start), cal.first_session)
    end = min(pd.Timestamp(end), cal.last_session)
    return cal.sessions_in_range(start, end)


def export_csv(frames: dict[str, pd.DataFrame], out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in frames.items():
        p = out / f"{name}.csv"
        df.to_csv(p, index=False)
        paths.append(p)
    return paths

