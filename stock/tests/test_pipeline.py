import numpy as np
import pandas as pd
import pytest

from kabu import db, evaluate, importer, model, sample_data
from kabu.cli import main
from kabu.features import FEATURES, RAW_FEATURES, build_features

HORIZON = 20


@pytest.fixture(scope="module")
def frames():
    return sample_data.generate(n_stocks=80, n_days=900, index_size=50, new_listings=10, seed=1)


@pytest.fixture(scope="module")
def db_path(frames, tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "k.db"
    importer.import_frames(frames["securities"], frames["prices"], path, frames["actions"], frames["membership"])
    return path


@pytest.fixture(scope="module")
def loaded(db_path):
    return db.load_prices(db_path), db.load_actions(db_path), db.load_membership(db_path)


@pytest.fixture(scope="module")
def feats(loaded):
    return build_features(*loaded, horizon=HORIZON)


def test_sample_has_splits_delistings_and_listings(frames):
    sec = frames["securities"]
    assert (frames["actions"]["split_ratio"] > 1).any()
    assert (frames["actions"]["dividend"] > 0).any()
    assert sec["delisted_date"].notna().any()
    assert (sec["listed_date"] > sec["listed_date"].min()).any()


def test_features_have_no_future_leakage(loaded, feats):
    """ある日付より後の株価を書き換えても、その日以前の特徴量は変わらないこと."""
    prices, actions, membership = loaded
    cut = feats["date"].unique()[len(feats["date"].unique()) // 2]
    changed = prices.copy()
    later = changed["date"] > cut
    changed.loc[later, ["open", "high", "low", "close"]] *= np.random.default_rng(0).uniform(0.5, 1.5, (later.sum(), 1))
    f2 = build_features(changed, actions, membership, horizon=HORIZON)
    a = feats[feats["date"] <= cut].set_index(["date", "security_id"])[RAW_FEATURES + FEATURES]
    b = f2[f2["date"] <= cut].set_index(["date", "security_id"])[RAW_FEATURES + FEATURES]
    pd.testing.assert_frame_equal(a, b)


def test_target_is_next_open_to_open_excess_return(loaded, feats):
    prices, actions, _ = loaded
    from kabu.adjust import adjust_prices

    adj = adjust_prices(prices, actions)
    row = feats.dropna(subset=["target"]).iloc[1000]
    s = adj[adj["security_id"] == row["security_id"]].set_index("date")
    spy = adj[adj["ticker"] == "SPY"].set_index("date")
    dates = spy.index
    i = dates.get_loc(row["date"])
    entry, exit_ = dates[i + 1], dates[i + 1 + HORIZON]
    expect = s.loc[exit_, "adj_open"] / s.loc[entry, "adj_open"] - 1
    expect -= spy.loc[exit_, "adj_open"] / spy.loc[entry, "adj_open"] - 1
    assert row["target"] == pytest.approx(expect)


def test_last_days_have_no_target(feats):
    dates = np.sort(feats["date"].unique())
    assert feats[feats["date"].isin(dates[-(HORIZON + 1):])]["target"].isna().all()
    assert feats[feats["date"] == dates[-(HORIZON + 2)]]["target"].notna().any()


def test_delisted_stock_keeps_its_loss(frames, db_path, feats):
    """上場廃止の直前の日にも目的変数があり、大きなマイナスになっていること (生存者バイアス対策)."""
    sec = db.load_securities(db_path)
    dead = sec[sec["delisted_date"].notna() & (sec["ticker"] != "SPY")]
    rows = feats[feats["security_id"].isin(dead["security_id"])].dropna(subset=["target"])
    if rows.empty:
        pytest.skip("指数に入ったまま廃止された銘柄が無い")
    last = rows.sort_values("date").groupby("security_id").tail(1)
    assert (last["target"] < 0).mean() > 0.5


def test_universe_is_point_in_time_membership(loaded, feats):
    _, _, membership = loaded
    m = feats[["date", "security_id"]].merge(membership, on="security_id")
    inside = (m["date"] >= m["start_date"]) & (m["end_date"].isna() | (m["date"] < m["end_date"]))
    assert inside.groupby([m["date"], m["security_id"]]).any().all()
    assert feats.groupby("date").size().max() <= 50


def test_model_beats_random_and_saves(feats, tmp_path):
    dates = np.sort(feats["date"].unique())
    split = dates[int(len(dates) * 0.6)]
    train_df = feats[feats["date"] < split - pd.Timedelta(days=40)]
    test_df = feats[feats["date"] >= split].dropna(subset=["target"])
    m = model.train(train_df, horizon=HORIZON, rounds=100)
    ic = evaluate.daily_ic(test_df, m.predict(test_df))
    assert ic.mean() > 0
    m.save(tmp_path / "m.pkl")
    m2 = model.RankModel.load(tmp_path / "m.pkl")
    pd.testing.assert_series_equal(m.predict(test_df), m2.predict(test_df))

    lr = model.train(train_df, horizon=HORIZON, objective="lambdarank", rounds=20)
    assert lr.predict(test_df).notna().all()


def test_gauss_rank_is_standardized_per_day():
    df = pd.DataFrame({"date": ["a"] * 4 + ["b"] * 4, "target": [1, 2, 3, 4, 40, 30, 20, 10]})
    g = model.gauss_rank(df)
    assert g[:4].tolist() == pytest.approx(g[4:][::-1].tolist())
    assert g[:4].sum() == pytest.approx(0)


def test_top_n_portfolio_costs_and_turnover():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    df = pd.DataFrame({
        "date": np.repeat(dates, 3), "security_id": [1, 2, 3] * 4,
        "fwd_return": [0.1, 0.0, -0.1] * 4, "bench_return": 0.02, "target": 0.0,
    })
    score = pd.Series([3, 2, 1, 3, 2, 1, 1, 2, 3, 1, 2, 3], dtype=float)
    res = evaluate.top_n_portfolio(df, score, top_n=1, horizon=2, cost_bps=100)
    p = res.periods
    assert p["date"].tolist() == [dates[0], dates[2]]
    assert p["ret"].tolist() == pytest.approx([0.1 - 0.01, -0.1 - 0.02])  # 初回は買いのみ, 2 回目は売り+買い
    assert p["turnover"].tolist() == pytest.approx([0.5, 1.0])


def test_cli_end_to_end(tmp_path, capsys):
    path = str(tmp_path / "c.db")
    mpath = str(tmp_path / "m.pkl")
    assert main(["--db", path, "sample", "--stocks", "60", "--days", "700", "--index-size", "40"]) == 0
    assert main(["--db", path, "evaluate", "--test-start", "2026-01-01", "--rounds", "50"]) == 0
    out = capsys.readouterr().out
    assert "IC 平均" in out and "モメンタム" in out
    assert main(["--db", path, "train", "--model", mpath, "--rounds", "50"]) == 0
    csv = tmp_path / "pred.csv"
    assert main(["--db", path, "predict", "--model", mpath, "--top-n", "5", "--output", str(csv)]) == 0
    pred = pd.read_csv(csv)
    assert len(pred) <= 40 and pred["順位"].tolist() == sorted(pred["順位"])
    assert main(["--db", path, "check"]) == 0
