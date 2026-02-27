import logging
from typing import List

from fastapi import APIRouter, HTTPException

from ...core.config import get_app_config, get_effective_local_root, get_settings
from ...models.local import LocalLibraryItem
from ...services.local_library_service import LocalLibraryService, validate_local_root

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/items", response_model=List[LocalLibraryItem])
async def list_local_items():
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
        return service.scan_items()
    except Exception as e:
        logger.error(f"Failed to scan local items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to scan local library: {e}")
