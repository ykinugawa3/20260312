import numpy as np
import pandas as pd
import pytest

from numbers4 import analysis, db, importer, sample_data
from numbers4.cli import main


def _draws(numbers: list[str], first_draw_no: int = 1) -> pd.DataFrame:
    return pd.DataFrame({
        "draw_no": range(first_draw_no, first_draw_no + len(numbers)),
        "date": pd.bdate_range("2024-01-01", periods=len(numbers)),
        "number": numbers,
    })


@pytest.fixture(scope="module")
def sample():
    return sample_data.generate(n_draws=3000, seed=1)


def test_normalize_reads_japanese_csv_formats():
    raw = pd.DataFrame({
        "回号": ["第6001回", "第6002回", "第6003回"],
        "抽せん日": ["2026年10月1日", "2026/10/02(金)", "2026-10-05"],
        "当せん番号": ["123", "0450", "9999"],
        "ストレート当せん金": ["1,013,700円", "該当なし", "885500.0"],
    })
    out = importer.normalize(raw)
    assert out["draw_no"].tolist() == [6001, 6002, 6003]
    assert out["date"].tolist() == ["2026-10-01", "2026-10-02", "2026-10-05"]
    assert out["number"].tolist() == ["0123", "0450", "9999"]
    assert out["straight_payout"].iloc[0] == 1_013_700
    assert pd.isna(out["straight_payout"].iloc[1])
    assert out["straight_payout"].iloc[2] == 885_500
    assert out["box_payout"].isna().all()


@pytest.mark.parametrize("numbers, draw_nos, message", [
    (["12345"], [1], "読めない行"),
    (["12a4"], [1], "読めない行"),
    (["1234", "5678"], [1, 1], "重複"),
])
def test_normalize_rejects_bad_rows(numbers, draw_nos, message):
    raw = pd.DataFrame({"draw_no": draw_nos, "date": "2026-10-01", "number": numbers})
    with pytest.raises(importer.ImportErrorWithDetail, match=message):
        importer.normalize(raw)


def test_normalize_requires_columns():
    with pytest.raises(importer.ImportErrorWithDetail, match="必須列"):
        importer.normalize(pd.DataFrame({"draw_no": [1], "number": ["1234"]}))


def test_import_csv_keeps_leading_zeros_and_payouts(tmp_path, sample):
    csv = tmp_path / "draws.csv"
    sample.to_csv(csv, index=False)
    path = tmp_path / "n.db"
    assert importer.import_csv(csv, path) == len(sample)
    loaded = db.load_draws(path)
    assert loaded["number"].tolist() == sample["number"].tolist()
    assert loaded["number"].str.startswith("0").any()
    np.testing.assert_array_equal(loaded["straight_payout"], sample["straight_payout"])
    np.testing.assert_array_equal(loaded["box_payout"], sample["box_payout"])


def test_import_csv_shift_jis(tmp_path):
    csv = tmp_path / "sjis.csv"
    csv.write_bytes("回号,抽せん日,当せん番号\n6001,2026/10/01,0012\n".encode("cp932"))
    path = tmp_path / "n.db"
    importer.import_csv(csv, path)
    assert db.load_draws(path)["number"].tolist() == ["0012"]


def test_reimport_replaces_same_draw(tmp_path):
    path = tmp_path / "n.db"
    importer.import_frame(_draws(["1111"]), path)
    importer.import_frame(_draws(["2222"]), path)
    assert db.load_draws(path)["number"].tolist() == ["2222"]


def test_sample_payouts_are_realistic(sample):
    assert sample["number"].str.fullmatch(r"\d{4}").all()
    assert 700_000 < sample["straight_payout"].median() < 1_200_000
    single = sample[sample["number"].map(analysis.pattern_of) == "シングル"]
    assert 25_000 < single["box_payout"].median() < 55_000


def test_pattern_counts_match_theory():
    numbers = pd.Series([f"{i:04d}" for i in range(10_000)])
    counts = numbers.map(analysis.pattern_of).value_counts()
    assert {k: counts[k] for k in analysis.PATTERNS} == {k: v[1] for k, v in analysis.PATTERNS.items()}
    # 各型の並べ替え通り数 × 組み合わせ数 = その型の個数
    boxes = numbers.map(analysis.box_key).drop_duplicates().map(analysis.pattern_of).value_counts()
    for k, (combos, total) in analysis.PATTERNS.items():
        assert boxes[k] * combos == total


def test_sum_distribution():
    dist = analysis._sum_distribution()
    assert dist.sum() == pytest.approx(1)
    assert (dist.index * dist).sum() == pytest.approx(18)
    assert dist[0] == pytest.approx(1e-4)


def test_merge_small_bins_keeps_totals():
    obs, exp = analysis._merge_small_bins(np.array([1, 2, 30, 40, 3]), np.array([1.0, 2.0, 30.0, 40.0, 3.0]))
    assert obs.sum() == 76 and exp.sum() == 76
    assert exp.min() >= analysis.MIN_EXPECTED


def test_random_sample_passes_all_tests(sample):
    result = analysis.randomness_tests(sample)
    assert (result["判定"] == "問題なし").all(), result
    assert "偏りは見られません" in analysis.summarize_tests(result)


def test_detects_biased_digits():
    rng = np.random.default_rng(0)
    # 千の位に 0〜4 が出やすい (6:4) 抽せん機
    first = np.where(rng.random(3000) < 0.6, rng.integers(0, 5, 3000), rng.integers(5, 10, 3000))
    rest = rng.integers(0, 1000, 3000)
    draws = _draws([f"{a}{b:03d}" for a, b in zip(first, rest)])
    result = analysis.randomness_tests(draws).set_index(["検定", "内容"])
    assert result.loc[("数字の出現回数", "千の位"), "判定"] == "偏りの疑い"
    assert result.loc[("数字の出現回数", "一の位"), "判定"] == "問題なし"


def test_detects_dependence_on_previous_draw():
    rng = np.random.default_rng(0)
    numbers = [f"{rng.integers(0, 10_000):04d}"]
    for _ in range(2999):
        n = f"{rng.integers(0, 10_000):04d}"
        if rng.random() < 0.3:  # 一の位が前回と同じになりやすい
            n = n[:3] + numbers[-1][3]
        numbers.append(n)
    result = analysis.randomness_tests(_draws(numbers)).set_index(["検定", "内容"])
    assert result.loc[("前回との独立性", "一の位"), "判定"] == "偏りの疑い"
    assert result.loc[("前回との独立性", "千の位"), "判定"] == "問題なし"


def test_independence_skips_missing_draws():
    # 回号が飛んでいる所 (3 → 10) は「前回」として扱わない
    draws = pd.concat([_draws(["1111", "2222", "3333"]), _draws(["4444", "5555"], first_draw_no=10)])
    assert analysis.carry_rate(draws) == (0.0, 3)
    tests = analysis.randomness_tests(draws)
    assert (tests[tests["検定"] == "前回との独立性"]["回数"] == 3).all()


def test_small_data_is_not_judged():
    result = analysis.randomness_tests(_draws(["1234", "5678", "9012"]))
    assert (result["判定"] == "データ不足").all()
    assert "データが少なすぎ" in analysis.summarize_tests(result)


def test_position_counts_and_gaps():
    draws = _draws(["1234", "1999", "5234"])
    counts = analysis.position_counts(draws)
    assert counts.loc[1, "千の位"] == 2 and counts.loc[5, "千の位"] == 1
    assert counts.to_numpy().sum() == 12
    gaps = analysis.current_gaps(draws)
    assert gaps.loc[5, "千の位"] == 0
    assert gaps.loc[1, "千の位"] == 1
    assert gaps.loc[9, "一の位"] == 1
    assert gaps.loc[2, "百の位"] == 0
    assert pd.isna(gaps.loc[0, "千の位"])


def test_hot_cold_uses_recent_window():
    draws = _draws(["0000"] * 10 + ["9999"] * 3)
    hc = analysis.hot_cold(draws, last=3, k=2).set_index("桁")
    assert hc.loc["千の位", "ホット"][0] == (9, 3)
    assert hc.loc["千の位", "コールド"][0] == (0, 0)


def test_carry_rate_near_theory(sample):
    rate, n = analysis.carry_rate(sample)
    assert n == len(sample) - 1
    assert abs(rate - analysis.CARRY_PROB) < 0.03


def test_lookup():
    draws = _draws(["1234", "4321", "1234", "5678"])
    r = analysis.lookup(draws, "1234")
    assert r["pattern"] == "シングル" and r["box_combinations"] == 24
    assert r["straight_hits"]["draw_no"].tolist() == [1, 3]
    assert r["box_hits"]["number"].tolist() == ["4321"]
    assert r["draws_since_straight"] == 1
    assert analysis.lookup(draws, "77")["number"] == "0077"
    with pytest.raises(ValueError):
        analysis.lookup(draws, "12a4")


def test_cli_end_to_end(tmp_path, capsys):
    path = str(tmp_path / "n.db")
    main(["--db", path, "sample", "--draws", "800", "--csv", str(tmp_path / "s.csv")])
    main(["--db", path, "import", str(tmp_path / "s.csv")])
    main(["--db", path, "check"])
    out = capsys.readouterr().out
    assert "偏りは見られません" in out
    main(["--db", path, "stats", "--last", "30"])
    out = capsys.readouterr().out
    assert "ホット / コールド (直近 30 回" in out and analysis.DISCLAIMER in out
    main(["--db", path, "lookup", "1111"])
    assert "ゾロ目は買えません" in capsys.readouterr().out


def test_cli_without_data(tmp_path):
    with pytest.raises(SystemExit, match="データがありません"):
        main(["--db", str(tmp_path / "empty.db"), "check"])
