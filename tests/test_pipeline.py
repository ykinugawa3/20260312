import numpy as np
import pandas as pd
import pytest

from keiba import db, importer, model, sample_data
from keiba.cli import main
from keiba.features import FEATURES, build_features


@pytest.fixture(scope="module")
def sample():
    return sample_data.generate(n_days=40, n_horses=500, seed=0)


@pytest.fixture(scope="module")
def joined(sample, tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "k.db"
    importer.import_frames(*sample, path)
    return db.load_joined(path)


@pytest.fixture(scope="module")
def features(joined):
    return build_features(joined)


def test_frame_number():
    assert [sample_data._frame_number(n, 8) for n in range(1, 9)] == list(range(1, 9))
    assert [sample_data._frame_number(n, 10) for n in range(1, 11)] == [1, 2, 3, 4, 5, 6, 7, 7, 8, 8]
    assert [sample_data._frame_number(n, 16) for n in range(1, 17)] == [i // 2 + 1 for i in range(16)]


def test_last_day_is_unfinished(joined):
    last = joined[joined["date"] == joined["date"].max()]
    assert last["finish_position"].isna().all()
    assert joined[joined["date"] < joined["date"].max()]["finish_position"].notna().all()


def test_features_have_no_future_leakage(joined, features):
    """ある日付以降の結果を書き換えても、それ以前の日付と当日の特徴量は変わらないこと."""
    dates = sorted(joined["date"].unique())
    cutoff = dates[len(dates) // 2]
    tampered = joined.copy()
    future = tampered["date"] >= cutoff
    rng = np.random.default_rng(1)
    tampered.loc[future, "finish_position"] = rng.permutation(tampered.loc[future, "finish_position"].to_numpy())
    tampered.loc[future, "time_sec"] += rng.normal(0, 5, future.sum())
    tampered.loc[future, "last_3f"] += rng.normal(0, 2, future.sum())

    f2 = build_features(tampered)
    key = ["race_id", "horse_number"]
    mask = features["date"] <= cutoff
    a = features[mask].sort_values(key).reset_index(drop=True)[FEATURES]
    b = f2[f2["date"] <= cutoff].sort_values(key).reset_index(drop=True)[FEATURES]
    pd.testing.assert_frame_equal(a, b)


def test_horse_history_uses_previous_race(features):
    horse = features.groupby("horse_id").filter(lambda g: len(g) >= 3)["horse_id"].iloc[0]
    h = features[features["horse_id"] == horse].sort_values("date")
    assert pd.isna(h["last_finish"].iloc[0])
    assert h["n_past_races"].iloc[0] == 0
    assert h["last_finish"].iloc[1] == h["finish_position"].iloc[0]
    assert h["n_past_races"].iloc[2] == 2


def test_train_predict_evaluate(features, tmp_path):
    dates = sorted(features["date"].unique())
    train_df, test_df = model.split_by_date(features, dates[-8])
    m = model.train(train_df)

    pred = m.predict(test_df)
    sums = pred.groupby(test_df["race_id"]).sum()
    assert np.allclose(sums, 1.0)

    path = tmp_path / "m.pkl"
    m.save(path)
    m2 = model.WinModel.load(path)
    assert np.allclose(m2.predict(test_df), pred)

    r = model.evaluate(m, test_df)
    assert r["n_races"] > 0
    assert 0.5 < r["auc_model"] <= 1.0

    out = model.predict_races(m, test_df)
    first = out.groupby("race_id").head(1)
    assert (first["mark"] == "◎").all()


def test_import_rejects_missing_columns(tmp_path):
    races = pd.DataFrame({"race_id": ["1"], "date": ["2024-01-01"]})
    entries = pd.DataFrame({"race_id": ["1"], "horse_id": ["h"], "horse_number": [1]})
    with pytest.raises(importer.ImportErrorWithDetail, match="必須列"):
        importer.import_frames(races, entries, tmp_path / "x.db")


def test_import_rejects_unknown_race(sample, tmp_path):
    races, entries = sample
    with pytest.raises(importer.ImportErrorWithDetail, match="race_id"):
        importer.import_frames(races.iloc[1:], entries, tmp_path / "x.db")


def test_cli_end_to_end(tmp_path, capsys):
    dbp, mp, csv_dir = tmp_path / "k.db", tmp_path / "m.pkl", tmp_path / "csv"
    main(["--db", str(dbp), "sample", "--days", "30", "--csv-dir", str(csv_dir)])
    # CSV からの再取込 (上書き) も通ること
    main(["--db", str(dbp), "import", str(csv_dir / "races.csv"), str(csv_dir / "entries.csv")])
    main(["--db", str(dbp), "train", "--model", str(mp)])
    main(["--db", str(dbp), "predict", "--model", str(mp), "--output", str(tmp_path / "p.csv")])
    out = capsys.readouterr().out
    assert "◎" in out
    pred = pd.read_csv(tmp_path / "p.csv")
    assert pred["finish_position"].isna().all()
    assert np.allclose(pred.groupby("race_id")["win_prob"].sum(), 1.0)
