"""API routes for configuration management."""

from fastapi import APIRouter, HTTPException

from src.api.schemas import ConfigResponse, ConfigUpdate
from src.services.config_service import ConfigService

router = APIRouter(tags=["config"])
config_service = ConfigService()


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Get the active configuration."""
    try:
        config = config_service.load_config()
        # Redact sensitive fields
        safe_config = dict(config)
        if "ai" in safe_config:
            ai = dict(safe_config["ai"])
            if ai.get("api_key"):
                ai["api_key"] = "***"
            safe_config["ai"] = ai
        if "github_config" in safe_config:
            gh = dict(safe_config["github_config"])
            if gh.get("auth_token"):
                gh["auth_token"] = "***"
            safe_config["github_config"] = gh
        if "artifact_repository" in safe_config:
            ar = dict(safe_config["artifact_repository"])
            if ar.get("maven_password"):
                ar["maven_password"] = "***"
            if ar.get("npm_auth_token"):
                ar["npm_auth_token"] = "***"
            safe_config["artifact_repository"] = ar
        return ConfigResponse(config=safe_config)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")


@router.put("", response_model=ConfigResponse)
async def update_config(body: ConfigUpdate):
    """Update configuration (persisted to database profile)."""
    try:
        profile = config_service.update_config(body.updates, body.profile_name)
        return ConfigResponse(config=profile.config_data or {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
