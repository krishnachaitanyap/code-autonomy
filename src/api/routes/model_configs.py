"""
Model configuration API routes — manage LLM model configs for per-session selection.
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
    ModelConfigListResponse,
)
from src.data.database import get_session, init_db
from src.data.models import ModelConfig

logger = logging.getLogger(__name__)
router = APIRouter()


def _model_to_response(m: ModelConfig) -> ModelConfigResponse:
    return ModelConfigResponse(
        id=m.id,
        label=m.label,
        provider=m.provider,
        model=m.model,
        api_key_set=bool(m.api_key),
        base_url=m.base_url or "",
        extra_config=m.extra_config or {},
        is_default=m.is_default,
        is_system=m.is_system if hasattr(m, 'is_system') else False,
        created_at=str(m.created_at) if m.created_at else None,
        updated_at=str(m.updated_at) if m.updated_at else None,
    )


def _build_system_config() -> dict | None:
    """Build system model fields from config.ini. Returns None if no AI config."""
    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
        ai = config.get("ai", {})
        if not ai:
            return None
        provider = (ai.get("provider") or "openai").lower()
        model = ai.get("model", "")
        api_key = ai.get("api_key", "")
        if not model and not api_key:
            return None

        label_map = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "gemini": "Google Gemini",
            "azure": "Azure OpenAI",
            "bedrock": "AWS Bedrock",
            "cdao": "AWS Bedrock (CDAO)",
        }
        label = f"{label_map.get(provider, provider)} — {model}" if model else label_map.get(provider, provider)

        # Capture all [ai] config fields (except provider/model/api_key/base_url which are top-level)
        skip_keys = {"provider", "model", "api_key", "api_key_env", "base_url"}
        extra_config: dict = {}
        for key, val in ai.items():
            if key in skip_keys:
                continue
            if isinstance(val, bool):
                extra_config[key] = val
            elif isinstance(val, (int, float)):
                extra_config[key] = val
            elif isinstance(val, str) and val.strip():
                extra_config[key] = val.strip()

        return {
            "label": label,
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "base_url": ai.get("base_url", ""),
            "extra_config": extra_config,
        }
    except Exception as exc:
        logger.debug("_build_system_config failed: %s", exc)
        return None


def _ensure_system_model() -> None:
    """Ensure a system model exists that reflects config.ini. Creates or updates as needed."""
    sys_cfg = _build_system_config()
    if not sys_cfg:
        return

    try:
        with get_session() as db:
            # Look for existing system model
            existing = db.query(ModelConfig).filter(ModelConfig.is_system == True).first()
            if existing:
                # Update it to reflect current config.ini
                existing.label = sys_cfg["label"]
                existing.provider = sys_cfg["provider"]
                existing.model = sys_cfg["model"]
                existing.api_key = sys_cfg["api_key"]
                existing.base_url = sys_cfg["base_url"]
                existing.extra_config = sys_cfg["extra_config"]
                db.flush()
                return

            # No system model — check if there's a non-system default that matches config.ini (legacy seed)
            legacy = db.query(ModelConfig).filter(
                ModelConfig.is_default == True,
                ModelConfig.provider == sys_cfg["provider"],
                ModelConfig.model == sys_cfg["model"],
            ).first()
            if legacy:
                # Upgrade legacy seed to system model
                legacy.is_system = True
                legacy.label = sys_cfg["label"]
                legacy.api_key = sys_cfg["api_key"]
                legacy.base_url = sys_cfg["base_url"]
                legacy.extra_config = sys_cfg["extra_config"]
                db.flush()
                logger.info("Upgraded legacy model to system model: %s", sys_cfg["label"])
                return

            # Create new system model
            from src.data.models import _uuid
            m = ModelConfig(
                id=_uuid(),
                label=sys_cfg["label"],
                provider=sys_cfg["provider"],
                model=sys_cfg["model"],
                api_key=sys_cfg["api_key"],
                base_url=sys_cfg["base_url"],
                extra_config=sys_cfg["extra_config"],
                is_default=True,
                is_system=True,
            )
            db.add(m)
            db.flush()
            logger.info("Created system model from config.ini: %s", sys_cfg["label"])
    except Exception as exc:
        logger.debug("_ensure_system_model failed: %s", exc)


@router.get("", response_model=ModelConfigListResponse)
async def list_models():
    """List all configured models. Ensures system model from config.ini exists."""
    init_db()
    _ensure_system_model()
    with get_session() as db:
        all_models = db.query(ModelConfig).order_by(ModelConfig.created_at).all()
        return ModelConfigListResponse(
            models=[_model_to_response(m) for m in all_models],
            total=len(all_models),
        )


@router.post("", response_model=ModelConfigResponse, status_code=201)
async def create_model(data: ModelConfigCreate):
    """Add a new model configuration."""
    init_db()
    from src.data.models import _uuid
    m = ModelConfig(
        id=_uuid(),
        label=data.label,
        provider=data.provider,
        model=data.model,
        api_key=data.api_key,
        base_url=data.base_url,
        extra_config=data.extra_config,
        is_default=data.is_default,
    )
    with get_session() as db:
        # If setting as default, clear other defaults
        if data.is_default:
            db.query(ModelConfig).filter(ModelConfig.is_default == True).update({"is_default": False})
        db.add(m)
        db.flush()
        db.refresh(m)
        return _model_to_response(m)


@router.put("/{model_id}", response_model=ModelConfigResponse)
async def update_model(model_id: str, data: ModelConfigUpdate):
    """Update an existing model configuration."""
    init_db()
    with get_session() as db:
        m = db.get(ModelConfig, model_id)
        if not m:
            raise HTTPException(status_code=404, detail="Model config not found")
        if m.is_system:
            raise HTTPException(status_code=403, detail="System model (from config.ini) cannot be edited")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(m, field, value)
        if data.is_default:
            db.query(ModelConfig).filter(ModelConfig.id != model_id, ModelConfig.is_default == True).update({"is_default": False})
        db.flush()
        db.refresh(m)
        return _model_to_response(m)


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: str):
    """Delete a model configuration."""
    init_db()
    with get_session() as db:
        m = db.get(ModelConfig, model_id)
        if not m:
            raise HTTPException(status_code=404, detail="Model config not found")
        if m.is_system:
            raise HTTPException(status_code=403, detail="System model (from config.ini) cannot be deleted")
        db.delete(m)
        db.flush()


@router.post("/{model_id}/test")
async def test_model(model_id: str):
    """Test connectivity to a configured model by sending a minimal prompt."""
    init_db()
    with get_session() as db:
        m = db.get(ModelConfig, model_id)
        if not m:
            raise HTTPException(status_code=404, detail="Model config not found")

        # Build ai config dict matching what llm_client.chat_completion expects
        ai_cfg: dict = {
            "provider": m.provider,
            "model": m.model,
        }
        if m.api_key:
            ai_cfg["api_key"] = m.api_key
        if m.base_url:
            ai_cfg["base_url"] = m.base_url
        # Spread extra_config (bedrock: aws_account_number, aws_region, etc.)
        if m.extra_config:
            ai_cfg.update(m.extra_config)

    # Send a minimal ping
    import time
    start = time.time()
    try:
        from src.llm_client import chat_completion
        content, _msg = chat_completion(
            messages=[{"role": "user", "content": "Respond with exactly: ok"}],
            config=ai_cfg,
            temperature=0.0,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "status": "ok",
            "model_id": model_id,
            "response": content.strip()[:200],
            "latency_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning("Model test failed for %s: %s", model_id, exc)
        return {
            "status": "error",
            "model_id": model_id,
            "error": str(exc)[:500],
            "latency_ms": elapsed_ms,
        }


@router.post("/test-inline")
async def test_model_inline(data: ModelConfigCreate):
    """Test connectivity with unsaved model config (from the form)."""
    ai_cfg: dict = {
        "provider": data.provider,
        "model": data.model,
    }
    if data.api_key:
        ai_cfg["api_key"] = data.api_key
    if data.base_url:
        ai_cfg["base_url"] = data.base_url
    if data.extra_config:
        ai_cfg.update(data.extra_config)

    import time
    start = time.time()
    try:
        from src.llm_client import chat_completion
        content, _msg = chat_completion(
            messages=[{"role": "user", "content": "Respond with exactly: ok"}],
            config=ai_cfg,
            temperature=0.0,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "status": "ok",
            "response": content.strip()[:200],
            "latency_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning("Inline model test failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc)[:500],
            "latency_ms": elapsed_ms,
        }


@router.put("/{model_id}/default", response_model=ModelConfigResponse)
async def set_default_model(model_id: str):
    """Set a model as the default."""
    init_db()
    with get_session() as db:
        m = db.get(ModelConfig, model_id)
        if not m:
            raise HTTPException(status_code=404, detail="Model config not found")
        db.query(ModelConfig).filter(ModelConfig.is_default == True).update({"is_default": False})
        m.is_default = True
        db.flush()
        db.refresh(m)
        return _model_to_response(m)
