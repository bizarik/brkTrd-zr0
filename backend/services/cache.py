"""Cache management service"""

import json
import hashlib
from typing import Any, Optional
from datetime import timedelta
import redis.asyncio as redis
import structlog

logger = structlog.get_logger()


class CacheManager:
    """Manage Redis cache operations"""
    
    def __init__(self, redis_client: Optional[redis.Redis]):
        """Initialize cache manager"""
        self.redis = redis_client  # May be None if Redis is not available
    
    def cache_key(self, prefix: str, **kwargs) -> str:
        """Generate cache key from prefix and parameters"""
        # Sort kwargs for consistent keys
        sorted_params = sorted(kwargs.items())
        param_str = json.dumps(sorted_params)
        
        # Hash long keys
        if len(param_str) > 100:
            param_hash = hashlib.md5(param_str.encode()).hexdigest()
            return f"{prefix}:{param_hash}"
        
        return f"{prefix}:{param_str}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.redis:
            return None

        try:
            value = await self.redis.get(key)
            
            if value:
                return json.loads(value)
            
            return None
        
        except Exception as e:
            logger.error("cache_get_error", key=key, error=str(e))
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache with optional TTL"""
        if not self.redis:
            return False

        try:
            serialized = json.dumps(value, default=str)
            
            if ttl:
                await self.redis.setex(key, ttl, serialized)
            else:
                await self.redis.set(key, serialized)
            
            return True
        
        except Exception as e:
            logger.error("cache_set_error", key=key, error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.redis:
            return False

        try:
            await self.redis.delete(key)
            return True
        
        except Exception as e:
            logger.error("cache_delete_error", key=key, error=str(e))
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self.redis:
            return 0

        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                await self.redis.delete(*keys)
            
            return len(keys)
        
        except Exception as e:
            logger.error("cache_delete_pattern_error", pattern=pattern, error=str(e))
            return 0
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        if not self.redis:
            return False

        try:
            return await self.redis.exists(key) > 0
        
        except Exception as e:
            logger.error("cache_exists_error", key=key, error=str(e))
            return False
    
    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment counter in cache"""
        if not self.redis:
            return None

        try:
            return await self.redis.incrby(key, amount)
        
        except Exception as e:
            logger.error("cache_increment_error", key=key, error=str(e))
            return None
    
    async def get_or_set(
        self,
        key: str,
        factory,
        ttl: Optional[int] = None
    ) -> Any:
        """Get from cache or compute and set"""
        if not self.redis:
            # No cache available, just compute value
            if asyncio.iscoroutinefunction(factory):
                return await factory()
            return factory()

        # Try to get from cache
        value = await self.get(key)
        
        if value is not None:
            logger.debug("cache_hit", key=key)
            return value
        
        # Compute value
        logger.debug("cache_miss", key=key)
        
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()
        
        # Store in cache
        await self.set(key, value, ttl)
        
        return value


# Decorators for caching
import functools
import asyncio


def cached_result(
    prefix: str,
    ttl: Optional[int] = None,
    key_params: Optional[list] = None
):
    """Decorator to cache function results"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get cache manager from somewhere (e.g., app state)
            from main import cache_manager
            
            if not cache_manager:
                # No cache available, just run function
                return await func(*args, **kwargs)
            
            # Build cache key
            cache_params = {}
            
            if key_params:
                # Use specified parameters for key
                for param in key_params:
                    if param in kwargs:
                        cache_params[param] = kwargs[param]
            else:
                # Use all kwargs
                cache_params = kwargs
            
            key = cache_manager.cache_key(prefix, **cache_params)
            
            # Get or compute
            return await cache_manager.get_or_set(
                key,
                lambda: func(*args, **kwargs),
                ttl
            )
        
        return wrapper
    return decorator
