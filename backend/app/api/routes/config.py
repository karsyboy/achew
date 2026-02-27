from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...core.config import (
    get_app_config,
    get_effective_local_root,
    save_abs_config,
    save_local_config,
    save_source_config,
    save_llm_provider_config,
    get_user_preferences,
    update_user_preferences,
    refresh_app_config,
    ABSConfig,
    LocalConfig,
    SourceConfig,
    LLMProviderConfig,
    get_settings,
)
from ...models.enums import Step
from ...app import get_app_state
from ...services.llm_providers.registry import (
    get_all_provider_states,
    validate_provider_config,
    save_provider_config,
    set_provider_enabled,
    get_provider_models,
)
from ...services.llm_providers.base import ProviderInfo, ModelInfo
from ...services.local_library_service import LocalLibraryService, validate_local_root
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class ABSConfigRequest(BaseModel):
    url: str
    api_key: str


class ABSConfigResponse(BaseModel):
    url: str
    api_key: str  # Will be masked
    validated: bool
    last_validated: Optional[str] = None


class ASRServiceOption(BaseModel):
    service_id: str
    name: str
    desc: str
    uses_gpu: bool
    supports_bias_words: bool
    priority: int
    variants: list


class ASRPreferenceRequest(BaseModel):
    service_id: str
    variant_id: str = ""
    language: str = ""


class ASRPreferencesResponse(BaseModel):
    available_services: list[ASRServiceOption]
    current_service: str
    current_variant: str
    current_language: str
    book_language: Optional[str] = None


async def validate_abs_connection(abs_url: str, abs_api_key: str) -> Dict[str, Any]:
    """Validate ABS connection by hitting the authorize endpoint"""
    try:
        # Ensure URL ends with /
        if not abs_url.endswith("/"):
            abs_url += "/"

        # Try to hit the authorize endpoint to validate API key
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{abs_url}api/authorize",
                headers={"Authorization": f"Bearer {abs_api_key}"},
            )

            if response.status_code == 200:
                return {"valid": True, "message": "ABS authorization successful"}
            elif response.status_code == 401:
                return {"valid": False, "message": "Invalid API key - check your key"}
            elif response.status_code == 404:
                return {"valid": False, "message": "ABS server found but API endpoint not accessible"}
            else:
                return {"valid": False, "message": f"ABS returned status {response.status_code}"}

    except httpx.TimeoutException:
        return {"valid": False, "message": "Connection timeout - check URL and network"}
    except httpx.ConnectError:
        return {"valid": False, "message": "Cannot connect to ABS server - check URL"}
    except Exception as e:
        return {"valid": False, "message": f"Connection error: {str(e)}"}


async def validate_openai_key(api_key: str) -> Dict[str, Any]:
    """Validate OpenAI API key by listing models"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            if response.status_code == 200:
                return {"valid": True, "message": "OpenAI API key valid"}
            elif response.status_code == 401:
                return {"valid": False, "message": "Invalid OpenAI API key"}
            else:
                return {"valid": False, "message": f"OpenAI API returned status {response.status_code}"}

    except httpx.TimeoutException:
        return {"valid": False, "message": "OpenAI API timeout"}
    except Exception as e:
        return {"valid": False, "message": f"OpenAI API error: {str(e)}"}


def validate_local_config_path(root_path: str) -> Dict[str, Any]:
    settings = get_settings()
    valid, message, resolved = validate_local_root(root_path, settings.LOCAL_MEDIA_BASE)
    return {
        "valid": valid,
        "message": message,
        "resolved_path": str(resolved) if resolved else "",
        "sandbox_base": settings.LOCAL_MEDIA_BASE,
    }


class SourceModeRequest(BaseModel):
    mode: str


class SourceModeResponse(BaseModel):
    mode: str


class LocalConfigRequest(BaseModel):
    root_path: str


class LocalConfigResponse(BaseModel):
    root_path: str
    validated: bool
    last_validated: Optional[str] = None
    sandbox_base: str


class SourceSetupRequest(BaseModel):
    action: str  # "verify_and_save" or "cancel"
    mode: str = ""


class SourceSetupResponse(BaseModel):
    success: bool
    message: str
    errors: Dict[str, str] = {}


class LocalSetupRequest(BaseModel):
    action: str  # "verify_and_save" or "cancel"
    root_path: str = ""


class LocalSetupResponse(BaseModel):
    success: bool
    message: str
    errors: Dict[str, str] = {}


class LocalDirectoryOption(BaseModel):
    name: str
    path: str


class LocalBrowseResponse(BaseModel):
    current_path: str
    sandbox_base: str
    parent_path: Optional[str] = None
    directories: List[LocalDirectoryOption] = []


@router.get("/config/source", response_model=SourceModeResponse)
async def get_source_mode_config():
    config = get_app_config()
    return SourceModeResponse(mode=config.source.mode)


@router.post("/config/source")
async def set_source_mode_config(request: SourceModeRequest):
    if request.mode not in {"abs", "local", "unset"}:
        raise HTTPException(status_code=400, detail="Source mode must be one of: abs, local, unset")

    source_config = SourceConfig(mode=request.mode)
    if not save_source_config(source_config):
        raise HTTPException(status_code=500, detail="Failed to save source mode")

    refresh_app_config()
    return {"message": "Source mode updated successfully", "mode": request.mode}


@router.post("/config/source/setup", response_model=SourceSetupResponse)
async def handle_source_setup(request: SourceSetupRequest):
    try:
        app_state = get_app_state()

        if request.action == "cancel":
            if app_state.step == Step.SOURCE_SETUP:
                app_state.step = None
                await app_state.broadcast_step_change(Step.IDLE)
            return SourceSetupResponse(success=True, message="Source setup cancelled")

        if request.action != "verify_and_save":
            return SourceSetupResponse(success=False, message=f"Unknown action: {request.action}")

        if request.mode not in {"abs", "local"}:
            return SourceSetupResponse(success=False, message="Invalid source mode", errors={"mode": "Required"})

        if not save_source_config(SourceConfig(mode=request.mode)):
            return SourceSetupResponse(success=False, message="Failed to save source mode")

        refresh_app_config()
        config = get_app_config()

        if request.mode == "abs":
            if config.abs.url and config.abs.api_key:
                app_state.step = Step.LLM_SETUP
                await app_state.broadcast_step_change(Step.LLM_SETUP)
            else:
                app_state.step = Step.ABS_SETUP
                await app_state.broadcast_step_change(Step.ABS_SETUP)
        else:
            settings = get_settings()
            local_check = validate_local_config_path(settings.LOCAL_MEDIA_BASE)
            if not local_check["valid"]:
                return SourceSetupResponse(
                    success=False,
                    message=f"Local source unavailable: {local_check['message']}",
                    errors={"local": local_check["message"]},
                )

            local_config = LocalConfig(
                root_path=local_check["resolved_path"] or settings.LOCAL_MEDIA_BASE,
                validated=True,
                last_validated=datetime.now(timezone.utc),
            )
            if not save_local_config(local_config):
                return SourceSetupResponse(success=False, message="Failed to save local configuration")

            LocalLibraryService.clear_scan_cache()
            refresh_app_config()
            app_state.step = Step.LLM_SETUP
            await app_state.broadcast_step_change(Step.LLM_SETUP)

        return SourceSetupResponse(success=True, message="Source mode saved")

    except Exception as e:
        logger.error(f"Error in source setup: {e}", exc_info=True)
        return SourceSetupResponse(success=False, message="Internal server error")


@router.get("/config/local", response_model=LocalConfigResponse)
async def get_local_config():
    config = get_app_config()
    settings = get_settings()
    effective_root = get_effective_local_root()
    return LocalConfigResponse(
        root_path=effective_root or config.local.root_path or settings.LOCAL_MEDIA_BASE,
        validated=bool(effective_root),
        last_validated=config.local.last_validated.isoformat() if config.local.last_validated else None,
        sandbox_base=settings.LOCAL_MEDIA_BASE,
    )


@router.post("/config/local")
async def update_local_config(request: LocalConfigRequest):
    validation = validate_local_config_path(request.root_path)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Local path validation failed",
                "validation": validation,
            },
        )

    local_config = LocalConfig(
        root_path=validation["resolved_path"] or request.root_path,
        validated=True,
        last_validated=datetime.now(timezone.utc),
    )
    if not save_local_config(local_config):
        raise HTTPException(status_code=500, detail="Failed to save local configuration")

    LocalLibraryService.clear_scan_cache()
    refresh_app_config()
    return {"message": "Local configuration saved successfully", "resolved_path": validation["resolved_path"]}


@router.post("/config/local/validate")
async def validate_local_config(request: LocalConfigRequest):
    return validate_local_config_path(request.root_path)


@router.get("/config/local/browse", response_model=LocalBrowseResponse)
async def browse_local_directories(path: Optional[str] = Query(default=None)):
    settings = get_settings()

    base_path = Path(settings.LOCAL_MEDIA_BASE).expanduser().resolve(strict=False)
    if not base_path.exists() or not base_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Configured media base does not exist or is not a directory: {base_path}",
        )

    try:
        if path:
            candidate = Path(path).expanduser()
            target = (base_path / candidate).resolve(strict=False) if not candidate.is_absolute() else candidate.resolve(strict=False)
        else:
            target = base_path

        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=400, detail=f"Directory does not exist: {target}")

        base_real = base_path.resolve(strict=True)
        target_real = target.resolve(strict=True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid directory path: {e}")

    if target_real != base_real and base_real not in target_real.parents:
        raise HTTPException(status_code=400, detail=f"Path must be inside sandbox base: {base_real}")

    directories = []
    try:
        for child in target_real.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                directories.append(LocalDirectoryOption(name=child.name, path=str(child.resolve(strict=True))))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list directories: {e}")

    directories.sort(key=lambda option: option.name.lower())
    parent_path = str(target_real.parent) if target_real != base_real else None

    return LocalBrowseResponse(
        current_path=str(target_real),
        sandbox_base=str(base_real),
        parent_path=parent_path,
        directories=directories,
    )


@router.post("/config/local/setup", response_model=LocalSetupResponse)
async def handle_local_setup(request: LocalSetupRequest):
    try:
        app_state = get_app_state()

        if request.action == "cancel":
            if app_state.step == Step.LOCAL_SETUP:
                app_state.step = None
                await app_state.broadcast_step_change(Step.IDLE)
            return LocalSetupResponse(success=True, message="Local setup cancelled")

        if request.action != "verify_and_save":
            return LocalSetupResponse(success=False, message=f"Unknown action: {request.action}")

        validation = validate_local_config_path(request.root_path)
        if not validation["valid"]:
            return LocalSetupResponse(success=False, message="Validation failed", errors={"local": validation["message"]})

        config = get_app_config()
        was_previously_configured = bool(config.local.root_path and config.local.validated)

        local_config = LocalConfig(
            root_path=validation["resolved_path"] or request.root_path,
            validated=True,
            last_validated=datetime.now(timezone.utc),
        )
        if not save_local_config(local_config):
            return LocalSetupResponse(success=False, message="Failed to save local configuration")

        if config.source.mode != "local":
            save_source_config(SourceConfig(mode="local"))

        refresh_app_config()

        if was_previously_configured:
            app_state.step = None
            await app_state.broadcast_step_change(Step.IDLE)
        else:
            app_state.step = Step.LLM_SETUP
            await app_state.broadcast_step_change(Step.LLM_SETUP)

        return LocalSetupResponse(success=True, message="Local configuration saved successfully")

    except Exception as e:
        logger.error(f"Error in local setup: {e}", exc_info=True)
        return LocalSetupResponse(success=False, message="Internal server error")


@router.get("/config/abs", response_model=ABSConfigResponse)
async def get_abs_config():
    """Get ABS configuration"""
    config = get_app_config()
    return ABSConfigResponse(
        url=config.abs.url,
        api_key="***" if config.abs.api_key else "",
        validated=config.abs.validated,
        last_validated=config.abs.last_validated.isoformat() if config.abs.last_validated else None,
    )


@router.post("/config/abs")
async def update_abs_config(request: ABSConfigRequest):
    """Update ABS configuration"""
    # Validate connection
    validation_result = await validate_abs_connection(request.url, request.api_key)

    if not validation_result["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "ABS connection validation failed",
                "validation": validation_result,
            },
        )

    # Save configuration
    abs_config = ABSConfig(
        url=request.url,
        api_key=request.api_key,
        validated=True,
        last_validated=datetime.now(timezone.utc),
    )

    if not save_abs_config(abs_config):
        raise HTTPException(status_code=500, detail="Failed to save ABS configuration")

    # Refresh global config cache
    refresh_app_config()

    return {"message": "ABS configuration saved successfully"}


@router.post("/config/abs/validate")
async def validate_abs_config(request: ABSConfigRequest):
    """Validate ABS configuration without saving"""
    return await validate_abs_connection(request.url, request.api_key)


class LLMSetupRequest(BaseModel):
    action: str  # "verify_and_save" or "cancel"
    openai_api_key: str = ""


class LLMSetupResponse(BaseModel):
    success: bool
    message: str
    errors: Dict[str, str] = {}


@router.post("/config/llm/setup", response_model=LLMSetupResponse)
async def handle_llm_setup(request: LLMSetupRequest):
    """Handle LLM setup completion - verify and save or cancel"""
    try:
        if request.action == "cancel":
            # Cancel LLM setup and restore previous step
            app_state = get_app_state()

            if app_state.step == Step.LLM_SETUP:
                # Go to idle
                app_state.step = None
                await app_state.broadcast_step_change(Step.IDLE)

            return LLMSetupResponse(success=True, message="LLM setup cancelled")

        elif request.action == "verify_and_save":
            errors = {}
            should_save_openai = False

            # Validate OpenAI key if provided (non-empty string means user entered a new key)
            if request.openai_api_key.strip():
                openai_validation = await validate_openai_key(request.openai_api_key)
                if not openai_validation["valid"]:
                    errors["openai"] = openai_validation["message"]
                else:
                    should_save_openai = True

            # If there are validation errors, return them
            if errors:
                return LLMSetupResponse(
                    success=False, message="Validation failed for one or more providers", errors=errors
                )

            # All validations passed, save the configuration if new key was provided
            if should_save_openai:
                openai_config = LLMProviderConfig(
                    api_key=request.openai_api_key,
                    validated=True,
                    last_validated=datetime.now(timezone.utc),
                    enabled=True,
                )

                if not save_llm_provider_config("openai", openai_config):
                    return LLMSetupResponse(success=False, message="Failed to save OpenAI configuration")

            # Refresh global config cache
            refresh_app_config()

            # Complete the LLM setup
            app_state = get_app_state()

            if app_state.step == Step.LLM_SETUP:
                # Go to idle
                app_state.step = None
                await app_state.broadcast_step_change(Step.IDLE)

            return LLMSetupResponse(success=True, message="LLM configuration saved successfully")

        else:
            return LLMSetupResponse(success=False, message=f"Unknown action: {request.action}")

    except Exception as e:
        logger.error(f"Error in LLM setup: {e}")
        return LLMSetupResponse(success=False, message="Internal server error")


class ABSSetupRequest(BaseModel):
    action: str  # "verify_and_save" or "cancel"
    url: str = ""
    api_key: str = ""


class ABSSetupResponse(BaseModel):
    success: bool
    message: str
    errors: Dict[str, str] = {}


@router.post("/config/abs/setup", response_model=ABSSetupResponse)
async def handle_abs_setup(request: ABSSetupRequest):
    """Handle ABS setup completion - verify and save or cancel"""
    try:
        if request.action == "cancel":
            # Cancel ABS setup and restore previous step
            app_state = get_app_state()

            if app_state.step == Step.ABS_SETUP:
                # Go to idle
                app_state.step = None
                await app_state.broadcast_step_change(Step.IDLE)

            return ABSSetupResponse(success=True, message="ABS setup cancelled")

        elif request.action == "verify_and_save":
            errors = {}
            should_save_abs = False

            # Get current config to check for existing values
            current_config = get_app_config()

            # IMPORTANT: Check if this was previously configured BEFORE making any changes
            was_previously_configured = bool(
                current_config.abs.url and current_config.abs.api_key and current_config.abs.validated
            )

            # Determine what values to use for validation and saving
            url_provided = request.url.strip()
            api_key_is_placeholder = request.api_key.startswith("••••")

            # For validation, use existing API key if placeholder is sent
            validation_url = url_provided
            validation_api_key = current_config.abs.api_key if api_key_is_placeholder else request.api_key

            # For saving, use new values or keep existing ones
            save_url = url_provided if url_provided else current_config.abs.url
            save_api_key = current_config.abs.api_key if api_key_is_placeholder else request.api_key

            # Validate if we have both URL and API key (either provided or from existing config)
            if validation_url and validation_api_key:
                validation_result = await validate_abs_connection(validation_url, validation_api_key)

                if not validation_result["valid"]:
                    errors["abs"] = validation_result["message"]
                else:
                    should_save_abs = True
            elif not validation_url or not validation_api_key:
                # Missing either URL or API key (and no existing config to fall back on)
                errors["abs"] = "Both server URL and API key are required"

            # If there are validation errors, return them
            if errors:
                return ABSSetupResponse(success=False, message="Validation failed", errors=errors)

            # Save configuration if validation passed
            if should_save_abs:
                abs_config = ABSConfig(
                    url=save_url,
                    api_key=save_api_key,
                    validated=True,
                    last_validated=datetime.now(timezone.utc),
                )

                if not save_abs_config(abs_config):
                    return ABSSetupResponse(success=False, message="Failed to save ABS configuration")

                # ABS setup implies ABS mode.
                if not save_source_config(SourceConfig(mode="abs")):
                    return ABSSetupResponse(success=False, message="Failed to save source mode")

                # Refresh global config cache
                refresh_app_config()

            # Complete the ABS setup
            app_state = get_app_state()

            # Use the previously determined flag to decide next step
            if was_previously_configured:
                # This was a configuration update, go to idle
                app_state.step = None
                await app_state.broadcast_step_change(Step.IDLE)
            else:
                # This was initial setup, proceed to LLM setup
                app_state.step = Step.LLM_SETUP
                await app_state.broadcast_step_change(Step.LLM_SETUP)

            return ABSSetupResponse(success=True, message="ABS configuration saved successfully")

        else:
            return ABSSetupResponse(success=False, message=f"Unknown action: {request.action}")

    except Exception as e:
        logger.error(f"Error in ABS setup: {e}")
        return ABSSetupResponse(success=False, message="Internal server error")


@router.get("/config/status")
async def get_config_status():
    """Get configuration status (for checking if setup is needed)"""
    config = get_app_config()
    source_mode = config.source.mode
    abs_configured = bool(config.abs.url and config.abs.api_key)
    settings = get_settings()
    effective_root = get_effective_local_root()
    local_root_for_validation = effective_root or config.local.root_path
    local_validation = validate_local_config_path(local_root_for_validation) if local_root_for_validation else {
        "valid": False,
        "message": "Not configured",
        "resolved_path": "",
        "sandbox_base": settings.LOCAL_MEDIA_BASE,
    }
    local_configured = local_validation["valid"]
    openai_configured = bool(config.llm.openai.api_key)

    # Quick validation if configured
    validation_status = None
    if abs_configured or openai_configured:
        abs_validation = {"valid": False, "message": "Not configured"}
        openai_validation = {"valid": True, "message": "Not configured (optional)"}

        if abs_configured:
            abs_validation = await validate_abs_connection(config.abs.url, config.abs.api_key)

        if openai_configured:
            openai_validation = await validate_openai_key(config.llm.openai.api_key)

        validation_status = {
            "abs": abs_validation,
            "openai": openai_validation,
            "all_valid": abs_validation.get("valid", False),
        }

    return {
        "is_configured": source_mode in {"abs", "local"},
        "source_mode": source_mode,
        "needs_source_setup": source_mode == "unset",
        "abs_configured": abs_configured,
        "local_configured": local_configured,
        "local_validation": local_validation,
        "openai_configured": openai_configured,
        "needs_setup": (source_mode == "abs" and not abs_configured) or (source_mode == "local" and not local_configured),
        "validation": validation_status,
    }


@router.get("/asr/preferences", response_model=ASRPreferencesResponse)
async def get_asr_preferences():
    """Get available ASR services and current preferences"""
    try:
        from ...services.asr_service_options import get_available_services, get_preferred_service

        # Get available services
        services = get_available_services()
        available_services = []

        for service in services:
            variants = []
            for variant in service.variants:
                variants.append(
                    {
                        "model_id": variant.model_id,
                        "name": variant.name,
                        "desc": variant.desc,
                        "path": variant.path,
                        "languages": variant.languages,
                    }
                )

            available_services.append(
                ASRServiceOption(
                    service_id=service.service_id,
                    name=service.name,
                    desc=service.desc,
                    uses_gpu=service.uses_gpu,
                    supports_bias_words=service.supports_bias_words,
                    priority=service.priority,
                    variants=variants,
                )
            )

        # Get current preference
        preferred = get_preferred_service()
        preferences = get_user_preferences()

        book_language = None
        app_state = get_app_state()
        if app_state.pipeline and app_state.pipeline.book:
            book_language = app_state.pipeline.book.media.metadata.language

        return ASRPreferencesResponse(
            available_services=available_services,
            current_service=preferred.service_id if preferred else "",
            current_variant=preferences.preferred_asr_variant,
            current_language=preferences.preferred_asr_language,
            book_language=book_language,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get ASR preferences: {str(e)}")


@router.post("/asr/preferences")
async def set_asr_preferences(request: ASRPreferenceRequest):
    """Set ASR service preferences"""
    try:
        from ...services.asr_service_options import set_preferred_service

        set_preferred_service(request.service_id, request.variant_id, request.language)
        return {"message": "ASR preferences saved successfully"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save ASR preferences: {str(e)}")


# New LLM Provider endpoints
class LLMProvidersResponse(BaseModel):
    providers: List[ProviderInfo]


class LLMModelsResponse(BaseModel):
    models: List[ModelInfo]


class LLMProviderConfigRequest(BaseModel):
    provider_id: str
    config: Dict[str, Any]


class LLMProviderValidationRequest(BaseModel):
    provider_id: str
    config: Dict[str, Any]


class LLMProviderValidationResponse(BaseModel):
    valid: bool
    message: str


class LLMProviderEnableRequest(BaseModel):
    enabled: bool


class LLMProviderResponse(BaseModel):
    success: bool
    message: str
    provider_state: Optional[Dict[str, Any]] = None


@router.get("/llm/providers", response_model=LLMProvidersResponse)
async def get_llm_providers():
    """Get all available LLM providers with current state"""
    try:
        providers = await get_all_provider_states()
        return LLMProvidersResponse(providers=providers)

    except Exception as e:
        logger.error(f"Failed to get LLM providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/providers/{provider_id}/models", response_model=LLMModelsResponse)
async def get_llm_provider_models(provider_id: str):
    """Get available models for a specific provider"""
    try:
        config = get_app_config()

        # Get provider config based on provider type
        provider_config = {}
        if provider_id == "openai":
            if not config.llm.openai.api_key:
                raise HTTPException(status_code=400, detail="OpenAI provider not configured")
            provider_config = {"api_key": config.llm.openai.api_key}
        elif provider_id == "claude":
            if not config.llm.claude.api_key:
                raise HTTPException(status_code=400, detail="Claude provider not configured")
            provider_config = {"api_key": config.llm.claude.api_key}
        elif provider_id == "gemini":
            if not config.llm.gemini.api_key:
                raise HTTPException(status_code=400, detail="Gemini provider not configured")
            provider_config = {"api_key": config.llm.gemini.api_key}
        elif provider_id == "openrouter":
            if not config.llm.openrouter.api_key:
                raise HTTPException(status_code=400, detail="OpenRouter provider not configured")
            provider_config = {"api_key": config.llm.openrouter.api_key}
        elif provider_id == "ollama":
            provider_config = {"host": config.llm.ollama.host or "http://localhost:11434"}
        elif provider_id == "lm_studio":
            provider_config = {"host": config.llm.lm_studio.host or "http://localhost:1234"}

        models = await get_provider_models(provider_id, **provider_config)
        return LLMModelsResponse(models=models)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get models for provider {provider_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/providers/{provider_id}/validate", response_model=LLMProviderValidationResponse)
async def validate_llm_provider(provider_id: str, request: LLMProviderValidationRequest):
    """Validate a specific provider configuration"""
    try:
        valid, message = await validate_provider_config(provider_id, **request.config)
        return LLMProviderValidationResponse(valid=valid, message=message)

    except Exception as e:
        logger.error(f"Failed to validate provider {provider_id}: {e}")
        return LLMProviderValidationResponse(valid=False, message=str(e))


@router.post("/llm/providers/{provider_id}/config")
async def update_llm_provider_config(provider_id: str, request: LLMProviderConfigRequest):
    """Update configuration for a specific provider"""
    try:
        success, message = await save_provider_config(provider_id, **request.config)

        if not success:
            raise HTTPException(status_code=400, detail=message)

        # Refresh global config cache
        refresh_app_config()

        # Get updated provider state
        providers = await get_all_provider_states()
        provider_state = next((p for p in providers if p.id == provider_id), None)

        return {
            "message": message,
            "provider_state": provider_state.model_dump() if provider_state else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update provider {provider_id} config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/providers/{provider_id}/enable", response_model=LLMProviderResponse)
async def set_llm_provider_enabled(provider_id: str, request: LLMProviderEnableRequest):
    """Enable or disable a specific provider"""
    try:
        success = await set_provider_enabled(provider_id, request.enabled)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to update provider enabled state")

        # Refresh global config cache
        refresh_app_config()

        # Get updated provider state
        providers = await get_all_provider_states()
        provider_state = next((p for p in providers if p.id == provider_id), None)

        status = "enabled" if request.enabled else "disabled"
        return LLMProviderResponse(
            success=True,
            message=f"Provider {provider_id} {status} successfully",
            provider_state=provider_state.model_dump() if provider_state else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set enabled state for provider {provider_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/providers/{provider_id}/cancel", response_model=LLMProviderResponse)
async def cancel_llm_provider_changes(provider_id: str):
    """Revert unsaved changes for a specific provider"""
    try:
        # For now, this just returns the current saved state
        # In a more complex implementation, this would revert any in-memory changes
        providers = await get_all_provider_states()
        provider_state = next((p for p in providers if p.id == provider_id), None)

        if not provider_state:
            raise HTTPException(status_code=404, detail="Provider not found")

        # Reset config_changed flag
        config = get_app_config()
        if provider_id == "openai":
            config.llm.openai.config_changed = False
            save_llm_provider_config("openai", config.llm.openai)
        elif provider_id == "claude":
            config.llm.claude.config_changed = False
            save_llm_provider_config("claude", config.llm.claude)
        elif provider_id == "gemini":
            config.llm.gemini.config_changed = False
            save_llm_provider_config("gemini", config.llm.gemini)
        elif provider_id == "openrouter":
            config.llm.openrouter.config_changed = False
            save_llm_provider_config("openrouter", config.llm.openrouter)
        elif provider_id == "ollama":
            config.llm.ollama.config_changed = False
            save_llm_provider_config("ollama", config.llm.ollama)
        elif provider_id == "lm_studio":
            config.llm.lm_studio.config_changed = False
            save_llm_provider_config("lm_studio", config.llm.lm_studio)

        # Refresh global config cache
        refresh_app_config()

        # Get updated provider state
        providers = await get_all_provider_states()
        provider_state = next((p for p in providers if p.id == provider_id), None)

        return LLMProviderResponse(
            success=True,
            message=f"Changes cancelled for provider {provider_id}",
            provider_state=provider_state.model_dump() if provider_state else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel changes for provider {provider_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/providers/{provider_id}/config")
async def get_llm_provider_config(provider_id: str):
    """Get saved configuration for a specific provider"""
    try:
        from ...services.llm_providers.registry import get_registry

        registry = get_registry()

        # Get the provider class and load its saved config
        provider_class = registry.get_provider_class(provider_id)
        if not provider_class:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

        # Create instance and load saved config
        provider = provider_class(lambda *args: None)
        config = await provider.load_saved_config()

        return {"success": True, "config": config}
    except Exception as e:
        logger.error(f"Failed to get provider config: {e}")
        raise HTTPException(status_code=400, detail=str(e))


class EditorSettingsRequest(BaseModel):
    tab_navigation: Optional[bool] = None
    hide_transcriptions: Optional[bool] = None
    show_formatted_time: Optional[bool] = None


@router.get("/config/editor-settings")
async def get_editor_settings():
    """Get current editor settings"""
    try:
        preferences = get_user_preferences()
        return preferences.editor_settings.model_dump()
    except Exception as e:
        logger.error(f"Failed to get editor settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/config/editor-settings")
async def update_editor_settings(request: EditorSettingsRequest):
    """Update editor settings (partial update)"""
    try:
        current_prefs = get_user_preferences()

        update_data = request.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(current_prefs.editor_settings, field):
                setattr(current_prefs.editor_settings, field, value)

        if not update_user_preferences(current_prefs):
            raise HTTPException(status_code=500, detail="Failed to save editor settings")

        refresh_app_config()

        return {
            "message": "Editor settings updated successfully",
            "editor_settings": current_prefs.editor_settings.model_dump(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update editor settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
