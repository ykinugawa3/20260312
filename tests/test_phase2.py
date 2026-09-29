import numpy as np
import pandas as pd
import pytest

from keiba import backtest, db, importer, model, sample_data
from keiba.calibration import RaceCalibrator, market_prob, reliability_table
from keiba.cli import main
from keiba.features import build_features


@pytest.fixture(scope="module")
def features(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "k.db"
    importer.import_frames(*sample_data.generate(n_days=60, n_horses=600, seed=1), path)
    return build_features(db.load_joined(path))


def _toy_races(n_races=400, n_runners=10, seed=0):
    """真の勝率が既知の単純なレース群."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        score = rng.normal(0, 1, n_runners)
        p = np.exp(score) / np.exp(score).sum()
        winner = rng.choice(n_runners, p=p)
        for i in range(n_runners):
            rows.append({"race_id": f"R{r}", "true_p": p[i], "is_win": float(i == winner)})
    return pd.DataFrame(rows)


def test_calibrator_recovers_temperature():
    df = _toy_races()
    # 真の確率を平らにしすぎた予測 (温度 2) を較正すると a ≈ 2 に戻るはず
    flat = df["true_p"] ** 0.5
    flat = flat / flat.groupby(df["race_id"]).transform("sum")
    ones = pd.Series(1.0, index=df.index)
    cal = RaceCalibrator(use_market=False).fit(flat, ones, df["race_id"], df["is_win"])
    assert 1.4 < cal.a < 2.8
    p = cal.transform(flat, ones, df["race_id"])
    assert np.allclose(p.groupby(df["race_id"]).sum(), 1.0)


def test_calibrator_handles_missing_odds():
    df = _toy_races(n_races=5)
    odds = 0.8 / df["true_p"]
    odds.iloc[0] = np.nan
    p = RaceCalibrator(a=1.0, b=0.5).transform(df["true_p"], odds, df["race_id"])
    assert p.notna().all()
    assert np.allclose(p.groupby(df["race_id"]).sum(), 1.0)


def test_market_prob_sums_to_one():
    odds = pd.Series([2.0, 4.0, 8.0, 3.0, 3.0])
    race = pd.Series(["a", "a", "a", "b", "b"])
    assert np.allclose(market_prob(odds, race).groupby(race).sum(), 1.0)


def test_reliability_table_shape():
    df = _toy_races()
    t = reliability_table(df["true_p"], df["is_win"], bins=5)
    assert len(t) == 5 and set(t.columns) == {"pred", "actual", "n"}


def test_kelly():
    assert backtest.kelly(np.array([0.5]), np.array([3.0]))[0] == pytest.approx(0.25)
    assert backtest.kelly(np.array([0.2]), np.array([3.0]))[0] == 0.0


def _toy_preds():
    return pd.DataFrame({
        "race_id": ["r1", "r1", "r2", "r2"],
        "date": pd.to_datetime(["2024-01-01"] * 2 + ["2024-01-02"] * 2),
        "horse_number": [1, 2, 1, 2],
        "odds": [3.0, 10.0, 3.0, 10.0],
        "win_prob": [0.5, 0.05, 0.5, 0.05],
        "is_win": [1.0, 0.0, 0.0, 1.0],
    })


def test_simulate_flat_accounting():
    bets, s = backtest.simulate(_toy_preds(), backtest.Strategy(ev_threshold=1.2, flat_stake=100), bankroll=1000)
    # 期待値は 1.5 と 0.5 → 各レース 1 番だけ買う
    assert list(bets["horse_number"]) == [1, 1]
    assert s["total_stake"] == 200 and s["total_payout"] == 300
    assert s["final_bankroll"] == 1100
    assert s["roi"] == pytest.approx(1.5)


def test_simulate_kelly_respects_caps():
    strategy = backtest.Strategy(ev_threshold=1.0, kelly_fraction=1.0, max_bet_ratio=0.05, max_race_ratio=0.05)
    bets, s = backtest.simulate(_toy_preds(), strategy, bankroll=10_000)
    assert (bets["stake"] % 100 == 0).all()
    # 1 レース目の前は資金 10,000 円なので上限 500 円
    assert bets[bets["race_id"] == "r1"]["stake"].sum() <= 500


def test_simulate_no_bets():
    bets, s = backtest.simulate(_toy_preds(), backtest.Strategy(ev_threshold=5.0))
    assert bets.empty and s["n_bets"] == 0 and s["final_bankroll"] == 100_000


def test_max_drawdown():
    assert backtest.max_drawdown(pd.Series([120, 60, 90, 150]), 100) == pytest.approx(0.5)


def test_walk_forward_uses_only_past(features, monkeypatch):
    dates = sorted(features["date"].unique())
    start = pd.Timestamp(dates[-10])
    seen = []
    real_train = model.train

    def spy(df, **kw):
        seen.append(df["date"].max())
        return real_train(df, **kw)

    monkeypatch.setattr(model, "train", spy)
    preds = backtest.walk_forward_predictions(features, start, freq="MS")
    assert preds["date"].min() >= start
    assert np.allclose(preds.groupby("race_id")["win_prob"].sum(), 1.0)
    # 各区間の学習データは、その区間の予測対象より前
    periods = preds.groupby(preds["date"].dt.to_period("M"))["date"].min().tolist()
    assert len(seen) == len(periods)
    for first_pred_date, train_end in zip(periods, seen):
        assert train_end < first_pred_date


def test_model_calibrator_roundtrip(features, tmp_path):
    dates = sorted(features["date"].unique())
    m = model.train(features[features["date"] < dates[-5]])
    assert m.calibrator is not None
    path = tmp_path / "m.pkl"
    m.save(path)
    m2 = model.WinModel.load(path)
    assert (m2.calibrator.a, m2.calibrator.b) == (m.calibrator.a, m.calibrator.b)
    test = features[features["date"] >= dates[-5]]
    assert np.allclose(m2.predict(test), m.predict(test))


def test_cli_backtest_and_predict(tmp_path, capsys):
    dbp, mp = tmp_path / "k.db", tmp_path / "m.pkl"
    main(["--db", str(dbp), "sample", "--days", "50"])
    preds_csv = tmp_path / "preds.csv"
    main(["--db", str(dbp), "backtest", "--save-preds", str(preds_csv), "--flat", "100", "--ev-threshold", "1.0"])
    main(["backtest", "--load-preds", str(preds_csv), "--ev-threshold", "1.1"])
    main(["--db", str(dbp), "train", "--model", str(mp)])
    main(["--db", str(dbp), "predict", "--model", str(mp), "--bankroll", "100000",
          "--output", str(tmp_path / "p.csv")])
    out = capsys.readouterr().out
    assert "回収率" in out and "推奨額" in out
    p = pd.read_csv(tmp_path / "p.csv")
    assert {"stake", "model_prob", "market_prob"} <= set(p.columns)
    assert (p["stake"] % 100 == 0).all()
