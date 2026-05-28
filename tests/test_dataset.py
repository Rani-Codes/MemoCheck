from datetime import datetime, timezone
from pathlib import Path

import pytest

from memocheck.evals.dataset import filter_slice, load_held_out_ids, load_test_cases
from memocheck.evals.schema import GroundTruthExtractedMemo, TestCase


def test_load_held_out_ids_parses_ids_and_skips_comments(tmp_path: Path):
    f = tmp_path / "ids.txt"
    f.write_text(
        "# comment line\n"
        "\n"
        "memo_001\n"
        "  memo_005  \n"  # whitespace tolerated
        "# another comment\n"
        "memo_009\n"
    )

    ids = load_held_out_ids(f)

    assert ids == {"memo_001", "memo_005", "memo_009"}


def test_load_held_out_ids_empty_file_returns_empty_set(tmp_path: Path):
    f = tmp_path / "empty.txt"
    f.write_text("# just a comment\n\n# another\n")

    ids = load_held_out_ids(f)

    assert ids == set()


def _write_case(dir: Path, id: str) -> None:
    """Minimal valid TestCase JSON for fixture purposes."""
    (dir / f"{id}.json").write_text(
        '{"id":"%s","transcript":"hi","memo_recorded_at":"2026-05-04T09:30:00Z",'
        '"ground_truth":{}}' % id
    )


def test_load_test_cases_reads_all_json_files(tmp_path: Path):
    _write_case(tmp_path, "memo_001")
    _write_case(tmp_path, "memo_002")

    cases = load_test_cases(tmp_path)

    assert sorted(c.id for c in cases) == ["memo_001", "memo_002"]


def test_load_test_cases_ignores_non_json_files(tmp_path: Path):
    _write_case(tmp_path, "memo_001")
    (tmp_path / "memo_001.txt").write_text("transcript text, not JSON")
    (tmp_path / "README.md").write_text("notes")

    cases = load_test_cases(tmp_path)

    assert [c.id for c in cases] == ["memo_001"]


def test_load_test_cases_raises_on_invalid_json(tmp_path: Path):
    (tmp_path / "broken.json").write_text("{ this is not valid json")

    with pytest.raises(Exception):  # noqa: PT011 - any validation error fails loud
        load_test_cases(tmp_path)


def test_load_test_cases_returns_results_sorted_by_id(tmp_path: Path):
    """Deterministic order makes batch runs reproducible."""
    _write_case(tmp_path, "memo_003")
    _write_case(tmp_path, "memo_001")
    _write_case(tmp_path, "memo_002")

    cases = load_test_cases(tmp_path)

    assert [c.id for c in cases] == ["memo_001", "memo_002", "memo_003"]


def _case(id: str) -> TestCase:
    return TestCase(
        id=id,
        transcript="x",
        memo_recorded_at=datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc),
        ground_truth=GroundTruthExtractedMemo(),
    )


def test_filter_slice_visible_excludes_held_out():
    cases = [_case("memo_001"), _case("memo_002"), _case("memo_003")]
    held = {"memo_002"}

    result = filter_slice(cases, held, "visible")

    assert [c.id for c in result] == ["memo_001", "memo_003"]


def test_filter_slice_held_out_keeps_only_held_out():
    cases = [_case("memo_001"), _case("memo_002"), _case("memo_003")]
    held = {"memo_002", "memo_003"}

    result = filter_slice(cases, held, "held_out")

    assert [c.id for c in result] == ["memo_002", "memo_003"]


def test_filter_slice_all_keeps_everything():
    cases = [_case("memo_001"), _case("memo_002")]
    held = {"memo_002"}

    result = filter_slice(cases, held, "all")

    assert [c.id for c in result] == ["memo_001", "memo_002"]


def test_filter_slice_rejects_unknown_slice():
    with pytest.raises(ValueError):
        filter_slice([_case("memo_001")], set(), "garbage")  # type: ignore[arg-type]
