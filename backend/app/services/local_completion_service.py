from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Tuple

from ..core.config import mark_local_completion
from .local_library_service import LocalLibraryService

logger = logging.getLogger(__name__)


class LocalCompletionService:
    @staticmethod
    def _normalize_rel_path(value: str) -> str:
        normalized = str(Path(value.replace("\\", "/")).as_posix()).strip()
        if normalized == ".":
            return ""
        return normalized.lstrip("/")

    @staticmethod
    def _collect_folder_path(local_item_id: str, rel_paths: List[str], layout: str) -> List[str]:
        folders: List[str] = []
        parsed: Tuple[str, str] | None = None

        if local_item_id:
            try:
                parsed = LocalLibraryService.parse_item_id(local_item_id)
            except Exception:
                parsed = None

        if parsed and parsed[0] == "folder":
            folder_rel = LocalCompletionService._normalize_rel_path(parsed[1])
            if folder_rel:
                folders.append(folder_rel)
                return folders

        if layout == "multi_file_grouped":
            parents = {LocalCompletionService._normalize_rel_path(str(Path(path).parent)) for path in rel_paths if path}
            parents.discard("")
            if len(parents) == 1:
                folders.append(next(iter(parents)))

        return folders

    @staticmethod
    def mark_pipeline_completed(pipeline: Any) -> bool:
        rel_paths = [
            LocalCompletionService._normalize_rel_path(path)
            for path in (getattr(pipeline, "local_rel_paths", None) or [])
            if path
        ]
        rel_paths = [path for path in rel_paths if path]

        layout = getattr(pipeline, "local_media_layout", "") or ""
        local_item_id = getattr(pipeline, "local_item_id", "") or ""

        folder_paths = LocalCompletionService._collect_folder_path(local_item_id, rel_paths, layout)

        if not rel_paths and local_item_id:
            try:
                kind, rel_path = LocalLibraryService.parse_item_id(local_item_id)
                if kind == "file":
                    normalized = LocalCompletionService._normalize_rel_path(rel_path)
                    if normalized:
                        rel_paths = [normalized]
            except Exception:
                pass

        if not rel_paths and not folder_paths:
            logger.warning("Skipped marking local completion because no local paths were available")
            return False

        return mark_local_completion(
            file_paths=rel_paths,
            folder_paths=folder_paths,
            completed_at=datetime.now(timezone.utc),
        )
