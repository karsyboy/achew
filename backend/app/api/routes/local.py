import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...core.config import get_app_config, get_effective_local_root, get_local_completion_config, get_settings
from ...models.local import LocalLibraryItem
from ...services.local_library_service import LocalLibraryService, validate_local_root

logger = logging.getLogger(__name__)

router = APIRouter()


def _apply_completion_flags(items: List[LocalLibraryItem]) -> List[LocalLibraryItem]:
    completion = get_local_completion_config()
    completed_files = completion.completed_files
    completed_folders = completion.completed_folders

    for item in items:
        if item.candidate_type == "multi_file_folder_book":
            folder_completed_at = completed_folders.get(item.rel_path)
            latest_child_completion = None
            all_children_completed = len(item.individual_items) > 0

            for split_item in item.individual_items:
                split_completed_at = completed_files.get(split_item.rel_path)
                if split_completed_at:
                    split_item.completed = True
                    split_item.completed_at = split_completed_at
                    if latest_child_completion is None or split_completed_at > latest_child_completion:
                        latest_child_completion = split_completed_at
                else:
                    all_children_completed = False

            if folder_completed_at:
                item.completed = True
                item.completed_at = folder_completed_at
            elif all_children_completed and latest_child_completion:
                # If every child file has been completed individually, consider the folder complete.
                item.completed = True
                item.completed_at = latest_child_completion
        else:
            file_completed_at = completed_files.get(item.rel_path)
            if file_completed_at:
                item.completed = True
                item.completed_at = file_completed_at

    return items


@router.get("/items", response_model=List[LocalLibraryItem])
async def list_local_items(refresh: bool = Query(False, description="Force a full local library rescan")):
    """List discoverable audiobook candidates under the configured local root."""
    settings = get_settings()
    effective_root = get_effective_local_root()
    if not effective_root:
        config = get_app_config()
        candidate_root = config.local.root_path or settings.LOCAL_MEDIA_BASE
        valid, message, _ = validate_local_root(candidate_root, settings.LOCAL_MEDIA_BASE)
        raise HTTPException(status_code=400, detail=f"Local source not configured: {message}" if not valid else "Local source not configured")

    valid, message, _ = validate_local_root(effective_root, settings.LOCAL_MEDIA_BASE)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Local source not configured: {message}")

    try:
        service = LocalLibraryService(effective_root, settings.LOCAL_MEDIA_BASE)
        return _apply_completion_flags(service.get_cached_items(refresh=refresh))
    except Exception as e:
        logger.error(f"Failed to scan local items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to scan local library: {e}")
