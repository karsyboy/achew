from types import SimpleNamespace

from app.services.local_completion_service import LocalCompletionService
from app.services.local_library_service import LocalLibraryService


def test_mark_pipeline_completed_single_file_marks_file(monkeypatch):
    captured = {}

    def _fake_mark_local_completion(*, file_paths=None, folder_paths=None, completed_at=None):
        captured["file_paths"] = file_paths
        captured["folder_paths"] = folder_paths
        captured["completed_at"] = completed_at
        return True

    monkeypatch.setattr("app.services.local_completion_service.mark_local_completion", _fake_mark_local_completion)

    pipeline = SimpleNamespace(
        local_rel_paths=["Standalone/Book 1.m4b"],
        local_media_layout="single_file",
        local_item_id=LocalLibraryService.build_item_id("file", "Standalone/Book 1.m4b"),
    )

    assert LocalCompletionService.mark_pipeline_completed(pipeline) is True
    assert captured["file_paths"] == ["Standalone/Book 1.m4b"]
    assert captured["folder_paths"] == []
    assert captured["completed_at"] is not None


def test_mark_pipeline_completed_grouped_folder_marks_files_and_folder(monkeypatch):
    captured = {}

    def _fake_mark_local_completion(*, file_paths=None, folder_paths=None, completed_at=None):
        captured["file_paths"] = file_paths
        captured["folder_paths"] = folder_paths
        captured["completed_at"] = completed_at
        return True

    monkeypatch.setattr("app.services.local_completion_service.mark_local_completion", _fake_mark_local_completion)

    pipeline = SimpleNamespace(
        local_rel_paths=["Series/Book A/01.m4a", "Series/Book A/02.m4a"],
        local_media_layout="multi_file_grouped",
        local_item_id=LocalLibraryService.build_item_id("folder", "Series/Book A"),
    )

    assert LocalCompletionService.mark_pipeline_completed(pipeline) is True
    assert captured["file_paths"] == ["Series/Book A/01.m4a", "Series/Book A/02.m4a"]
    assert captured["folder_paths"] == ["Series/Book A"]
    assert captured["completed_at"] is not None

