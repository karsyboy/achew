from pathlib import Path

from app.models.local import LocalAudioFileInfo, LocalLibraryItem
from app.services.local_library_service import LocalLibraryService, validate_local_root


def _touch(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")


def _make_library_item(rel_path: str) -> LocalLibraryItem:
    filename = Path(rel_path).name
    return LocalLibraryItem(
        id=LocalLibraryService.build_item_id("file", rel_path),
        name=Path(rel_path).stem,
        rel_path=rel_path,
        candidate_type="single_file_book",
        processing_mode="single_file",
        file_count=1,
        duration=123.0,
        files=[
            LocalAudioFileInfo(
                rel_path=rel_path,
                filename=filename,
                duration=123.0,
                size=456,
            )
        ],
        can_split=False,
        individual_items=[],
    )


def test_validate_local_root_accepts_path_within_media_base(tmp_path):
    media_base = tmp_path / "media"
    root = media_base / "books"
    root.mkdir(parents=True)

    valid, message, resolved = validate_local_root(str(root), str(media_base))

    assert valid is True
    assert resolved == root.resolve()
    assert "Valid" in message


def test_validate_local_root_rejects_path_outside_media_base(tmp_path):
    media_base = tmp_path / "media"
    outside_root = tmp_path / "outside"
    media_base.mkdir(parents=True)
    outside_root.mkdir(parents=True)

    valid, message, resolved = validate_local_root(str(outside_root), str(media_base))

    assert valid is False
    assert resolved is None
    assert "inside sandbox base" in message


def test_scan_items_groups_folder_candidates_and_ignores_sidecars(tmp_path, monkeypatch):
    media_base = tmp_path / "media"
    root = media_base / "library"

    # Grouped folder candidate
    _touch(root / "Book A" / "01. Intro.m4a")
    _touch(root / "Book A" / "02. Chapter.m4a")
    _touch(root / "Book A" / "01. Intro.metadata.json")

    # Standalone candidate
    _touch(root / "Standalone Book.m4b")
    _touch(root / "Standalone Book.metadata.json")

    # Nested grouped folder candidate
    _touch(root / "Series" / "Book B" / "01.m4a")
    _touch(root / "Series" / "Book B" / "02.m4a")

    monkeypatch.setattr(
        LocalLibraryService,
        "get_audio_duration",
        lambda self, path: float(len(path.name)),
    )

    service = LocalLibraryService(str(root), str(media_base))
    items = service.scan_items()

    grouped = [item for item in items if item.candidate_type == "multi_file_folder_book"]
    singles = [item for item in items if item.candidate_type == "single_file_book"]

    assert len(grouped) == 2
    assert len(singles) == 1

    book_a = next(item for item in grouped if item.rel_path == "Book A")
    assert book_a.processing_mode == "multi_file_grouped"
    assert book_a.can_split is True
    assert [f.filename for f in book_a.files] == ["01. Intro.m4a", "02. Chapter.m4a"]
    assert [split.rel_path for split in book_a.individual_items] == [
        "Book A/01. Intro.m4a",
        "Book A/02. Chapter.m4a",
    ]

    standalone = singles[0]
    assert standalone.rel_path == "Standalone Book.m4b"
    assert standalone.file_count == 1


def test_resolve_candidate_respects_individual_layout_hint(tmp_path, monkeypatch):
    media_base = tmp_path / "media"
    root = media_base / "library"
    file_path = root / "Book C" / "01.m4a"
    _touch(file_path)

    monkeypatch.setattr(LocalLibraryService, "get_audio_duration", lambda self, path: 123.0)

    service = LocalLibraryService(str(root), str(media_base))
    item_id = service.build_item_id("file", "Book C/01.m4a")

    resolved = service.resolve_candidate(item_id, layout_hint="multi_file_individual")

    assert resolved.media_layout == "multi_file_individual"
    assert resolved.rel_paths == ["Book C/01.m4a"]
    assert resolved.total_duration == 123.0


def test_get_cached_items_scans_once_until_refresh(tmp_path, monkeypatch):
    media_base = tmp_path / "media"
    root = media_base / "library"
    root.mkdir(parents=True)

    LocalLibraryService.clear_scan_cache()
    calls = {"count": 0}

    def fake_scan_items(self):
        calls["count"] += 1
        return [_make_library_item(f"Book {calls['count']}.m4b")]

    monkeypatch.setattr(LocalLibraryService, "scan_items", fake_scan_items)

    service = LocalLibraryService(str(root), str(media_base))

    first = service.get_cached_items()
    second = service.get_cached_items()
    refreshed = service.get_cached_items(refresh=True)

    assert calls["count"] == 2
    assert [item.rel_path for item in first] == ["Book 1.m4b"]
    assert [item.rel_path for item in second] == ["Book 1.m4b"]
    assert [item.rel_path for item in refreshed] == ["Book 2.m4b"]

    LocalLibraryService.clear_scan_cache()


def test_get_cached_items_returns_deep_copies(tmp_path, monkeypatch):
    media_base = tmp_path / "media"
    root = media_base / "library"
    root.mkdir(parents=True)

    LocalLibraryService.clear_scan_cache()
    monkeypatch.setattr(LocalLibraryService, "scan_items", lambda self: [_make_library_item("Book A.m4b")])

    service = LocalLibraryService(str(root), str(media_base))

    first = service.get_cached_items()
    first[0].completed = True
    first[0].files[0].filename = "mutated.m4b"

    second = service.get_cached_items()

    assert second[0].completed is False
    assert second[0].files[0].filename == "Book A.m4b"

    LocalLibraryService.clear_scan_cache()


def test_validate_audio_file_accepts_audio_stream_and_duration(tmp_path, monkeypatch):
    media_base = tmp_path / "media"
    root = media_base / "library"
    file_path = root / "Book D.m4b"
    _touch(file_path)

    service = LocalLibraryService(str(root), str(media_base))

    monkeypatch.setattr(
        LocalLibraryService,
        "_ffprobe_validation_json",
        lambda self, path: {
            "format": {"duration": "321.5"},
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
        },
    )

    valid, message, duration = service.validate_audio_file(file_path)
    assert valid is True
    assert message == ""
    assert duration == 321.5


def test_validate_audio_file_rejects_when_audio_stream_missing(tmp_path, monkeypatch):
    media_base = tmp_path / "media"
    root = media_base / "library"
    file_path = root / "Book E.m4a"
    _touch(file_path)

    service = LocalLibraryService(str(root), str(media_base))

    monkeypatch.setattr(
        LocalLibraryService,
        "_ffprobe_validation_json",
        lambda self, path: {
            "format": {"duration": "120.0"},
            "streams": [{"codec_type": "video", "codec_name": "mjpeg"}],
        },
    )

    valid, message, duration = service.validate_audio_file(file_path)
    assert valid is False
    assert "No audio stream" in message
    assert duration == 0.0


def test_validate_audio_file_uses_duration_fallback(tmp_path, monkeypatch):
    media_base = tmp_path / "media"
    root = media_base / "library"
    file_path = root / "Book F.m4b"
    _touch(file_path)

    service = LocalLibraryService(str(root), str(media_base))

    monkeypatch.setattr(
        LocalLibraryService,
        "_ffprobe_validation_json",
        lambda self, path: {
            "format": {"duration": "0"},
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        },
    )
    monkeypatch.setattr(LocalLibraryService, "get_audio_duration", lambda self, path: 88.25)

    valid, message, duration = service.validate_audio_file(file_path)
    assert valid is True
    assert message == ""
    assert duration == 88.25
