"""H4-1 — bench produces all three artifacts and its table matches the raw JSON."""
import json

from cmo.bench import run_bench


def test_bench_produces_all_artifacts(tmp_path):
    run_bench(mock=True, out_dir=tmp_path, sessions=5)
    for name in ("comparison.md", "comparison.png", "track1_curve.png", "bench.json"):
        assert (tmp_path / name).exists(), name


def test_markdown_numbers_match_json(tmp_path):
    report = run_bench(mock=True, out_dir=tmp_path, sessions=5)
    md = (tmp_path / "comparison.md").read_text()
    # every approach's total from the JSON must literally appear in the table
    for key, row in report["rows"].items():
        assert f"| {row['total']} |" in md, (key, row["total"])
    saved = json.loads((tmp_path / "bench.json").read_text())
    assert saved["rows"]["baseline_mock"]["total"] == report["rows"]["baseline_mock"]["total"]


def test_bench_encodes_expected_deltas(tmp_path, mock_baseline_total):
    r = run_bench(mock=True, out_dir=tmp_path, sessions=5)["rows"]
    assert r["baseline_mock"]["total"] == mock_baseline_total
    assert r["society_mock"]["total"] >= r["baseline_mock"]["total"] + 2.0
    assert r["memory_sN"]["total"] >= r["memory_s1"]["total"] + 1.5


def test_mock_runs_labelled(tmp_path):
    run_bench(mock=True, out_dir=tmp_path, sessions=5)
    md = (tmp_path / "comparison.md").read_text()
    assert "mock" in md.lower()  # honesty: mock runs labelled, never sold as live
