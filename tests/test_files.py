"""Tests for the shared file output of the command-line tools."""

from slot_reel_designer.files import save


def test_reports_created_updated_and_unchanged(tmp_path):
    path = tmp_path / "out.txt"
    assert save("one\n", path) == "created"
    assert save("one\n", path) == "unchanged"
    assert save("two\n", path) == "updated"
    assert path.read_text() == "two\n"


def test_creates_missing_directories(tmp_path):
    path = tmp_path / "a" / "b" / "out.md"
    assert save("text", path) == "created"
    assert path.read_text() == "text"
