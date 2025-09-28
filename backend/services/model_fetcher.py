"""Dynamic model fetching service for various AI providers"""

import asyncio
from typing import List, Dict, Any, Optional
import httpx
import structlog
from groq import Groq
from config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import AsyncSessionLocal

logger = structlog.get_logger()


class ModelFetcher:
    """Service to dynamically fetch available models from AI providers"""
    
    def __init__(self):
        self._groq_models_cache: Optional[List[Dict[str, Any]]] = None
        self._openrouter_models_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_ttl = 3600  # 1 hour cache
        self._last_groq_fetch = 0
        self._last_openrouter_fetch = 0
    
    async def _load_api_keys_from_db(self) -> tuple[Optional[str], Optional[str]]:
        """Load API keys from database"""
        try:
            async with AsyncSessionLocal() as db:
                # Import here to avoid circular import
                from models import UserSettings
                
                result = await db.execute(
                    select(UserSettings).where(UserSettings.user_id == "default")
                )
                user_settings = result.scalar_one_or_none()
                
                if user_settings:
                    return user_settings.groq_api_key, user_settings.openrouter_api_key
                
                return None, None
                
        except Exception as e:
            logger.error("failed_to_load_api_keys_from_db", error=str(e))
            return None, None
    
    async def get_groq_models(self, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch available models from Groq API"""
        import time
        
        # Use cache if still valid
        if (self._groq_models_cache and 
            time.time() - self._last_groq_fetch < self._cache_ttl):
            return self._groq_models_cache
        
        # Use provided API key, database key, or settings key (in that order)
        groq_key = api_key
        if not groq_key:
            db_groq_key, _ = await self._load_api_keys_from_db()
            groq_key = db_groq_key or settings.groq_api_key
        
        if not groq_key:
            logger.warning("no_groq_api_key", message="No Groq API key available")
            return self._get_fallback_groq_models()
        
        try:
            # Initialize Groq client
            client = Groq(api_key=groq_key)
            
            # Fetch models from Groq API
            models_response = client.models.list()
            
            # Transform to our format
            groq_models = []
            for model in models_response.data:
                groq_models.append({
                    "id": model.id,
                    "name": model.id,  # Groq doesn't provide display names
                    "context_window": getattr(model, 'context_window', 32768),
                    "created": getattr(model, 'created', None),
                    "owned_by": getattr(model, 'owned_by', 'groq')
                })
            
            # Cache the results
            self._groq_models_cache = groq_models
            self._last_groq_fetch = time.time()
            
            logger.info("fetched_groq_models", count=len(groq_models))
            return groq_models
            
        except Exception as e:
            logger.error("failed_to_fetch_groq_models", error=str(e))
            return self._get_fallback_groq_models()
    
    async def get_openrouter_models(self, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch available models from OpenRouter API"""
        import time
        
        # Use cache if still valid
        if (self._openrouter_models_cache and 
            time.time() - self._last_openrouter_fetch < self._cache_ttl):
            return self._openrouter_models_cache
        
        # Use provided API key, database key, or settings key (in that order)
        openrouter_key = api_key
        if not openrouter_key:
            _, db_openrouter_key = await self._load_api_keys_from_db()
            openrouter_key = db_openrouter_key or settings.openrouter_api_key
        
        if not openrouter_key:
            logger.warning("no_openrouter_api_key", message="No OpenRouter API key available")
            return self._get_fallback_openrouter_models()
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "HTTP-Referer": "https://braktrad.com",
                        "X-Title": "braktrad"
                    }
                )
                response.raise_for_status()
                
                data = response.json()
                models = data.get("data", [])
                
                # Transform to our format
                openrouter_models = []
                for model in models:
                    openrouter_models.append({
                        "id": model.get("id", ""),
                        "name": model.get("name", model.get("id", "")),
                        "context_window": model.get("context_length", 4096),
                        "pricing": model.get("pricing", {}),
                        "top_provider": model.get("top_provider", {}),
                        "per_request_limits": model.get("per_request_limits")
                    })
                
                # Cache the results
                self._openrouter_models_cache = openrouter_models
                self._last_openrouter_fetch = time.time()
                
                logger.info("fetched_openrouter_models", count=len(openrouter_models))
                return openrouter_models
                
        except Exception as e:
            logger.error("failed_to_fetch_openrouter_models", error=str(e))
            return self._get_fallback_openrouter_models()
    
    def _get_fallback_groq_models(self) -> List[Dict[str, Any]]:
        """Return fallback Groq models if API fetch fails"""
        fallback_models = [
            "llama-3.3-70b-versatile",
            "llama-3.2-90b-text-preview", 
            "llama-3.2-11b-text-preview",
            "llama-3.2-3b-preview",
            "llama-3.2-1b-preview",
            "llama-3.1-70b-instant",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
            "gemma-7b-it"
        ]
        
        return [
            {
                "id": model_id,
                "name": model_id,
                "context_window": 32768,
                "fallback": True
            }
            for model_id in fallback_models
        ]
    
    def _get_fallback_openrouter_models(self) -> List[Dict[str, Any]]:
        """Return fallback OpenRouter models if API fetch fails"""
        # Use the verified list from config as fallback
        return [
            {
                "id": model_id,
                "name": model_id,
                "context_window": 4096,
                "fallback": True
            }
            for model_id in settings.available_openrouter_models[:20]  # Limit to first 20 for fallback
        ]
    
    async def refresh_all_models(self) -> Dict[str, List[Dict[str, Any]]]:
        """Refresh models from all providers"""
        groq_models, openrouter_models = await asyncio.gather(
            self.get_groq_models(),
            self.get_openrouter_models(),
            return_exceptions=True
        )
        
        # Handle exceptions
        if isinstance(groq_models, Exception):
            logger.error("groq_models_fetch_failed", error=str(groq_models))
            groq_models = self._get_fallback_groq_models()
        
        if isinstance(openrouter_models, Exception):
            logger.error("openrouter_models_fetch_failed", error=str(openrouter_models))
            openrouter_models = self._get_fallback_openrouter_models()
        
        return {
            "groq": groq_models,
            "openrouter": openrouter_models
        }
    
    def clear_cache(self):
        """Clear the model cache to force refresh"""
        self._groq_models_cache = None
        self._openrouter_models_cache = None
        self._last_groq_fetch = 0
        self._last_openrouter_fetch = 0


# Global instance
model_fetcher = ModelFetcher()
