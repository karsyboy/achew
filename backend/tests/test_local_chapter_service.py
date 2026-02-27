from pathlib import Path
from app.services.local_chapter_service import LocalChapterService


def test_validate_grouped_boundary_mapping_accepts_valid_alignment():
    valid, error = LocalChapterService.validate_grouped_boundary_mapping(
        [0.0, 120.0, 240.0],
        [0.0, 120.1, 239.8],
        tolerance=0.5,
    )

    assert valid is True
    assert error == ""


def test_validate_grouped_boundary_mapping_rejects_count_mismatch():
    valid, error = LocalChapterService.validate_grouped_boundary_mapping(
        [0.0, 120.0],
        [0.0, 120.0, 240.0],
    )

    assert valid is False
    assert "requires" in error


def test_validate_grouped_boundary_mapping_rejects_timestamp_mismatch():
    valid, error = LocalChapterService.validate_grouped_boundary_mapping(
        [0.0, 130.0],
        [0.0, 120.0],
        tolerance=0.5,
    )

    assert valid is False
    assert "file boundaries" in error


def test_build_ffmetadata_normalizes_first_chapter_to_zero():
    metadata = LocalChapterService._build_ffmetadata(
        [(5.0, "Chapter 1"), (25.0, "Chapter 2")],
        duration=60.0,
    )

    assert ";FFMETADATA1" in metadata
    assert "START=0" in metadata
    assert "END=25000" in metadata
    assert "title=Chapter 1" in metadata
    assert "title=Chapter 2" in metadata


def test_output_muxer_uses_mp4_for_m4b_family():
    assert LocalChapterService._output_muxer(Path("book.m4b")) == "mp4"
    assert LocalChapterService._output_muxer(Path("book.m4a")) == "mp4"
    assert LocalChapterService._output_muxer(Path("book.mp4")) == "mp4"


def test_output_muxer_none_for_non_mp4_family():
    assert LocalChapterService._output_muxer(Path("book.mp3")) is None
