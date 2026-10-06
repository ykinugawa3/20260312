import numpy as np
import pandas as pd
import pytest

from kabu import db, importer, sources
from kabu.adjust import adjust_prices


def _prices(closes, sid=1, start="2024-01-02"):
    dates = pd.bdate_range(start, periods=len(closes))
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"security_id": sid, "date": dates, "open": c, "high": c, "low": c, "close": c, "volume": 1000.0})


def test_split_adjustment_makes_series_continuous():
    p = _prices([100, 102, 51, 52])  # 3 日目に 2 分割
    acts = pd.DataFrame({"security_id": [1], "date": [p["date"][2]], "split_ratio": [2.0], "dividend": [0.0]})
    adj = adjust_prices(p, acts)
    assert adj["adj_close"].tolist() == pytest.approx([50, 51, 51, 52])
    assert adj["adj_volume"].tolist() == pytest.approx([2000, 2000, 1000, 1000])


def test_dividend_adjustment_gives_total_return():
    p = _prices([100, 100, 98, 99])  # 3 日目に 2 ドル配当落ち
    acts = pd.DataFrame({"security_id": [1], "date": [p["date"][2]], "split_ratio": [1.0], "dividend": [2.0]})
    adj = adjust_prices(p, acts)
    # 配当込みでは 2 日目→3 日目のリターンは 0
    assert adj["adj_close"][2] / adj["adj_close"][1] == pytest.approx(1.0)
    assert adj["adj_close"][3] == pytest.approx(99)


def test_action_on_non_trading_day_moves_to_next_session():
    p = _prices([100, 50, 51], start="2024-01-05")  # 金曜, 月曜, 火曜
    acts = pd.DataFrame({"security_id": [1], "date": [pd.Timestamp("2024-01-06")],  # 土曜
                         "split_ratio": [2.0], "dividend": [0.0]})
    adj = adjust_prices(p, acts)
    assert adj["adj_close"].tolist() == pytest.approx([50, 50, 51])


def test_unadjust_yfinance_round_trip():
    """yfinance の分割調整済みの値を調整前に戻し、自前の調整で元に戻ること."""
    idx = pd.bdate_range("2024-06-03", periods=5, tz="America/New_York")
    split_adj_close = [50.0, 51.0, 52.0, 52.5, 53.0]
    yf_frame = pd.DataFrame({
        "Open": split_adj_close, "High": split_adj_close, "Low": split_adj_close, "Close": split_adj_close,
        "Adj Close": split_adj_close, "Volume": [2000.0, 2000, 1000, 1000, 1000],
        "Dividends": [0, 0, 0, 0.25, 0], "Stock Splits": [0, 0, 2.0, 0, 0],
    }, index=idx)
    prices, actions = sources.unadjust_yfinance("ABC", yf_frame)
    assert prices["close"].tolist() == pytest.approx([100, 102, 52, 52.5, 53])
    assert prices["volume"].tolist() == pytest.approx([1000, 1000, 1000, 1000, 1000])
    assert prices["date"].iloc[0] == "2024-06-03"
    assert actions["split_ratio"].tolist() == [2.0, 1.0]
    assert actions["dividend"].tolist() == pytest.approx([0.0, 0.25])

    p = prices.assign(security_id=1, date=pd.to_datetime(prices["date"]))
    a = actions.assign(security_id=1, date=pd.to_datetime(actions["date"]), dividend=0.0)
    assert adjust_prices(p, a)["adj_close"].tolist() == pytest.approx(split_adj_close)


def test_parse_sp500_table():
    table = pd.DataFrame({
        "Symbol": ["AAPL", "BRK.B"], "Security": ["Apple Inc.", "Berkshire Hathaway"],
        "GICS Sector": ["Information Technology", "Financials"], "Date added": ["1982-11-30", "bad"],
    })
    sec, mem = sources.parse_sp500_table(table)
    assert sec["ticker"].tolist() == ["AAPL", "BRK.B"]
    assert mem["start_date"].tolist() == ["1982-11-30", "1957-03-04"]
    assert sources.to_yahoo_symbol("BRK.B") == "BRK-B"
    assert sources.from_yahoo_symbol("BRK-B") == "BRK.B"


def _ticker_prices(closes, ticker="AAA"):
    dates = pd.bdate_range("2024-01-02", periods=len(closes)).strftime("%Y-%m-%d")
    return pd.DataFrame({"ticker": ticker, "date": dates, "open": closes, "high": closes,
                         "low": closes, "close": closes, "volume": 100})


def test_import_is_idempotent(tmp_path):
    path = tmp_path / "k.db"
    prices = _ticker_prices([10.0, 11, 12])
    importer.import_frames(None, prices, path)
    importer.import_frames(None, prices.assign(close=[10.0, 11, 13], high=[10.0, 11, 13]), path)
    loaded = db.load_prices(path)
    assert len(loaded) == 3
    assert loaded["close"].tolist() == [10, 11, 13]  # 同じ日付は上書き


def test_validation_flags_jump_without_split():
    prices = _ticker_prices([100.0, 101, 50, 51])
    warns = importer.validate_prices(prices)
    assert any("分割の記録が無い" in w for w in warns)
    actions = pd.DataFrame({"ticker": ["AAA"], "date": [prices["date"][2]], "split_ratio": [2.0], "dividend": [0.0]})
    assert not any("分割の記録が無い" in w for w in importer.validate_prices(prices, actions))


def test_validation_reports_missing_sessions_and_bad_rows():
    prices = _ticker_prices([10.0, 11, 12, 13]).drop(index=1)
    prices.loc[3, "close"] = -1
    sessions = pd.bdate_range("2024-01-02", periods=4)
    warns = importer.validate_prices(prices, sessions=sessions)
    assert any("0 以下" in w for w in warns)
    assert any("データが無い日" in w for w in warns)
    with pytest.raises(ValueError):
        importer.import_frames(None, prices.drop(columns=["close"]), ":memory:")


def test_import_csv_with_actions_in_price_file(tmp_path):
    prices = _ticker_prices([100.0, 50, 51]).assign(split_ratio=[None, 2.0, None], dividend=None)
    csv = tmp_path / "prices.csv"
    prices.to_csv(csv, index=False)
    report = importer.import_csv(csv, tmp_path / "k.db")
    assert report.actions == 1
    assert db.load_actions(tmp_path / "k.db")["split_ratio"].tolist() == [2.0]
