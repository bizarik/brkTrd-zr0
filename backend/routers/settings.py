"""Settings management API router"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import structlog
import httpx
from groq import Groq

from models import UserSettings
from config import settings as app_settings
from database import get_db
from services.model_fetcher import model_fetcher

logger = structlog.get_logger()
router = APIRouter()


class SettingsUpdate(BaseModel):
    """Settings update model"""
    finviz_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    finviz_portfolio_numbers: Optional[List[int]] = None
    selected_models: Optional[List[str]] = None
    theme: Optional[str] = None


class APIKeyValidation(BaseModel):
    """API key validation request"""
    key_type: str  # finviz, groq, openrouter
    api_key: str


@router.get("/")
async def get_settings(
    user_id: str = "default",
    db: AsyncSession = Depends(get_db)
):
    """Get user settings"""
    # Fetch user settings
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    
    settings = result.scalar_one_or_none()
    
    if not settings:
        # Return default settings
        return {
            "user_id": user_id,
            "finviz_configured": bool(app_settings.finviz_api_key),
            "groq_configured": bool(app_settings.groq_api_key),
            "openrouter_configured": bool(app_settings.openrouter_api_key),
            "finviz_portfolio_numbers": app_settings.finviz_portfolio_numbers,
            "selected_models": app_settings.selected_models,
            "available_groq_models": app_settings.available_groq_models,
            "available_openrouter_models": app_settings.available_openrouter_models,
            "theme": "dark"
        }
    
    return {
        "user_id": user_id,
        "finviz_configured": bool(settings.finviz_api_key),
        "groq_configured": bool(settings.groq_api_key),
        "openrouter_configured": bool(settings.openrouter_api_key),
        "finviz_portfolio_numbers": settings.finviz_portfolio_numbers,
        "selected_models": settings.selected_models,
        "available_groq_models": app_settings.available_groq_models,
        "available_openrouter_models": app_settings.available_openrouter_models,
        "theme": settings.theme,
        "last_key_rotation": settings.last_key_rotation.isoformat() if settings.last_key_rotation else None
    }


@router.put("/")
@router.put("")  # Support both with and without trailing slash
async def update_settings(
    settings_update: SettingsUpdate,
    user_id: str = "default",
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """Update user settings"""
    # Fetch or create user settings
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    
    settings = result.scalar_one_or_none()
    old_portfolios: List[int] = []
    
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
    else:
        old_portfolios = settings.finviz_portfolio_numbers or []
    
    # Update fields (ignore masked placeholders)
    update_data = settings_update.dict(exclude_unset=True)
    masked_values = {"***configured***", "***saved***"}
    changed_key = False
    
    for field, value in update_data.items():
        if value is None:
            continue
        if field in ("finviz_api_key", "groq_api_key", "openrouter_api_key"):
            if isinstance(value, str) and value.strip() in masked_values:
                continue  # don't overwrite existing secrets with mask
            if isinstance(value, str) and value.strip() == "":
                continue  # ignore empty strings
            changed_key = True
        if field == "finviz_portfolio_numbers":
            try:
                # Accept comma-separated string or list of strings, coerce to ints
                if isinstance(value, str):
                    import json as _json
                    try:
                        parsed = _json.loads(value)
                        if isinstance(parsed, list):
                            value = parsed
                        else:
                            value = [value]
                    except Exception:
                        value = [v.strip() for v in value.split(',') if v.strip()]
                if isinstance(value, list):
                    value = [int(v) for v in value if str(v).strip() != ""]
            except Exception:
                value = []
        
        setattr(settings, field, value)
    
    # Track key rotation only when any secret actually changed
    if changed_key:
        from datetime import datetime
        settings.last_key_rotation = datetime.utcnow()
    
    await db.commit()
    
    # Update app settings if needed
    if settings.finviz_api_key:
        app_settings.finviz_api_key = settings.finviz_api_key
    if settings.groq_api_key:
        app_settings.groq_api_key = settings.groq_api_key
    if settings.openrouter_api_key:
        app_settings.openrouter_api_key = settings.openrouter_api_key
    if settings.finviz_portfolio_numbers:
        app_settings.finviz_portfolio_numbers = settings.finviz_portfolio_numbers
    if settings.selected_models:
        app_settings.selected_models = settings.selected_models

    # Trigger holdings refresh for any newly added portfolio IDs
    try:
        new_portfolios = settings.finviz_portfolio_numbers or []
        new_set = set(int(x) for x in new_portfolios)
        old_set = set(int(x) for x in (old_portfolios or []))
        added = sorted(list(new_set - old_set))
        if added:
            # Resolve API key in runtime for the refresh tasks
            if settings.finviz_api_key:
                app_settings.finviz_api_key = settings.finviz_api_key
            # Import task lazily to avoid circular import
            from .portfolio import refresh_holdings_task
            for pid in added:
                if background_tasks is not None:
                    # Pass None to ensure the task opens its own DB session
                    background_tasks.add_task(refresh_holdings_task, pid, None, app_settings.finviz_api_key)
    except Exception as e:
        logger.warning("settings_refresh_holdings_error", error=str(e))
    
    return {
        "status": "updated",
        "user_id": user_id,
        "message": "Settings updated successfully"
    }


# Alias without trailing slash to avoid 307 on PUT
@router.put("")
async def update_settings_no_slash(
    settings_update: SettingsUpdate,
    user_id: str = "default",
    db: AsyncSession = Depends(get_db)
):
    return await update_settings(
        settings_update=settings_update,
        user_id=user_id,
        db=db,
        background_tasks=None
    )


@router.post("/validate-key")
async def validate_api_key(validation: APIKeyValidation):
    """Validate an API key (tolerant of network/CDN gating).

    Policy:
    - Return invalid=False ONLY on explicit 401 Unauthorized from the provider.
    - For any other status or network/TLS error, accept and defer verification
      to first real use to avoid blocking local setups behind proxies/CDNs.
    """
    key_type = validation.key_type.lower()
    api_key = validation.api_key

    try:
        if key_type == "finviz":
            # Finviz Elite often gates via redirects/403 (Cloudflare). Treat non-401 as deferred-accept.
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                try:
                    response = await client.get(
                        "https://elite.finviz.com/portfolio.ashx",
                        params={"v": 1, "api_key": api_key}
                    )
                except Exception as e:  # Network/TLS issues → accept and defer
                    logger.warning("finviz_validation_connectivity", error=str(e))
                    return {"valid": True, "message": "Saved. Could not verify (network). Will test on first fetch."}

            if response.status_code == 401:
                return {"valid": False, "message": "Invalid Finviz API key"}
            # 200/302/403 and others → accept, verification deferred
            return {"valid": True, "message": f"Saved. Verification deferred (status {response.status_code})."}

        elif key_type == "groq":
            # Prefer direct HTTP check to avoid SDK TLS/env issues
            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    response = await client.get("https://api.groq.com/openai/v1/models", headers=headers)
                except Exception as e:
                    logger.warning("groq_validation_connectivity", error=str(e))
                    return {"valid": True, "message": "Saved. Could not verify (network). Will test on first use."}

            if response.status_code == 200:
                return {"valid": True, "message": "Groq API key is valid"}
            if response.status_code == 401:
                return {"valid": False, "message": "Invalid Groq API key"}
            return {"valid": True, "message": f"Saved. Verification deferred (status {response.status_code})."}

        elif key_type == "openrouter":
            # OpenRouter may require referer/title headers for some org policies
            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "http://localhost",
                "X-Title": "brākTrād"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    response = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
                except Exception as e:
                    logger.warning("openrouter_validation_connectivity", error=str(e))
                    return {"valid": True, "message": "Saved. Could not verify (network). Will test on first use."}

            if response.status_code == 200:
                return {"valid": True, "message": "OpenRouter API key is valid"}
            if response.status_code == 401:
                return {"valid": False, "message": "Invalid OpenRouter API key"}
            return {"valid": True, "message": f"Saved. Verification deferred (status {response.status_code})."}

        else:
            raise HTTPException(400, f"Unknown key type: {key_type}")

    except Exception as e:
        logger.error("api_key_validation_error", key_type=key_type, error=str(e))
        # Default to accept-and-defer on unexpected errors
        return {"valid": True, "message": "Saved. Verification deferred due to unexpected error."}


def _is_free_openrouter_model(pricing: dict | None) -> bool:
    """Heuristic: treat model as free if pricing exists and any listed cost is 0, or explicit free flag."""
    if not pricing:
        return False
    # Common fields: prompt, completion, request, per_second, etc.
    try:
        for v in pricing.values():
            # Values may be strings like "$0.00" or numbers
            if isinstance(v, str):
                s = v.strip().replace("$", "")
                if s == "0" or s == "0.00" or s == "0.000":
                    return True
            elif isinstance(v, (int, float)) and float(v) == 0.0:
                return True
        # Some schemas might embed nested dicts
        for v in pricing.values():
            if isinstance(v, dict) and _is_free_openrouter_model(v):
                return True
    except Exception:
        return False
    return False


@router.get("/models/available")
async def get_available_models():
    """Return available model lists dynamically fetched from provider APIs.
    
    Falls back to configured lists if API calls fail.
    """
    try:
        # Fetch models dynamically from APIs
        all_models = await model_fetcher.refresh_all_models()
        groq_models = all_models["groq"]
        openrouter_models = all_models["openrouter"]
        
        # Mark if using fallback data
        using_groq_fallback = any(model.get("fallback", False) for model in groq_models)
        using_openrouter_fallback = any(model.get("fallback", False) for model in openrouter_models)
        
        return {
            "models": {
                "groq": groq_models,
                "openrouter": openrouter_models
            },
            "groq_configured": bool(app_settings.groq_api_key),
            "openrouter_configured": bool(app_settings.openrouter_api_key),
            "using_fallback": {
                "groq": using_groq_fallback,
                "openrouter": using_openrouter_fallback
            }
        }
        
    except Exception as e:
        logger.error("failed_to_fetch_dynamic_models", error=str(e))
        
        # Complete fallback to hardcoded lists
        groq_models = [
            {"id": m, "name": m, "context_window": 32768, "fallback": True}
            for m in app_settings.available_groq_models
        ]
        openrouter_models = [
            {"id": m, "name": m, "context_window": 4096, "fallback": True}
            for m in app_settings.available_openrouter_models
        ]

        return {
            "models": {
                "groq": groq_models,
                "openrouter": openrouter_models
            },
            "groq_configured": bool(app_settings.groq_api_key),
            "openrouter_configured": bool(app_settings.openrouter_api_key),
            "using_fallback": {
                "groq": True,
                "openrouter": True
            },
            "error": "Failed to fetch models dynamically, using fallback lists"
        }


@router.post("/models/refresh")
async def refresh_models():
    """Force refresh of model lists from provider APIs"""
    try:
        # Clear cache to force fresh fetch
        model_fetcher.clear_cache()
        
        # Fetch fresh models
        all_models = await model_fetcher.refresh_all_models()
        
        groq_count = len(all_models["groq"])
        openrouter_count = len(all_models["openrouter"])
        
        return {
            "status": "refreshed",
            "counts": {
                "groq": groq_count,
                "openrouter": openrouter_count,
                "total": groq_count + openrouter_count
            },
            "message": f"Refreshed {groq_count} Groq and {openrouter_count} OpenRouter models"
        }
        
    except Exception as e:
        logger.error("failed_to_refresh_models", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to refresh models: {str(e)}")


@router.post("/models/select")
async def select_models(
    models: List[str],
    user_id: str = "default",
    db: AsyncSession = Depends(get_db)
):
    """Select models for sentiment analysis"""
    # Get current available models to validate selection
    try:
        all_models = await model_fetcher.refresh_all_models()
        groq_model_ids = [m["id"] for m in all_models["groq"]]
        openrouter_model_ids = [m["id"] for m in all_models["openrouter"]]
    except Exception:
        # Fallback to hardcoded lists if dynamic fetch fails
        groq_model_ids = app_settings.available_groq_models
        openrouter_model_ids = app_settings.available_openrouter_models
    
    # Normalize models to explicit provider prefixes if ambiguous
    normalized: List[str] = []
    for m in models:
        if ":" in m:
            normalized.append(m)
            continue
        # Heuristic: if contains '/', it's likely OpenRouter id
        if m in groq_model_ids:
            normalized.append(f"groq:{m}")
        elif m in openrouter_model_ids or "/" in m:
            normalized.append(f"openrouter:{m}")
        else:
            # Default to openrouter if unknown shape
            normalized.append(f"openrouter:{m}")
    
    # Update settings
    app_settings.selected_models = normalized
    
    # Save to database
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    
    settings = result.scalar_one_or_none()
    
    if settings:
        settings.selected_models = normalized
        await db.commit()
    
    return {
        "status": "selected",
        "models": normalized,
        "message": f"Selected {len(models)} models for analysis"
    }
