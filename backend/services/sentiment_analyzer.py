"""Multi-model sentiment analysis orchestrator for brākTrād"""

import asyncio
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import numpy as np
import httpx
from groq import AsyncGroq
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from models import SentimentValue, TimeHorizon

logger = structlog.get_logger()


class SentimentAnalyzer:
    """Orchestrates multi-model sentiment analysis"""
    
    SENTIMENT_PROMPT = """You are a quantitative news trader optimizing for alpha capture. Predict the MOST LIKELY directional price movement from this headline's information edge.

Context:
- Ticker: {ticker}
- Company: {company}
- Sector: {sector}
- Industry: {industry}
- Headline: {headline}
- Source: {source}
- Headline timestamp: {headline_timestamp}
- First seen: {first_seen_timestamp}
- Market session: {market_session}
- Headline age (minutes): {headline_age_minutes}
- Is primary source: {is_primary_source}
{market_context}

DECISION FRAMEWORK:
1. SURPRISE FACTOR (highest weight):
   - Unexpected news > stronger reaction
   - Confirms expectations > muted/no reaction
   - Stale/priced-in (>30min old) > minimal edge

2. MAGNITUDE SIGNALS:
   Strong positive (+1): Beat by >10%, FDA approval, major contract win, activist/buyout premium
   Strong negative (-1): Miss by >10%, guidance cut, SEC probe, data breach, unexpected exec departure, downgrade
   Neutral (0): In-line results, minor updates, speculation, reiterations

3. TIMING DECAY:
   - <15 min: Maximum edge (confidence 0.7-1.0)
   - 15-60 min: Declining edge (confidence 0.4-0.7)
   - >60 min: Mostly priced in (confidence 0.1-0.4)
   - Pre-market/after-hours: Predict next session open

Output JSON:
{{
  "sentiment": -1/0/1,
  "horizon": "<1h"/"1-4h"/"same_day"/"next_open"/"24h",
  "confidence": 0.0-1.0,
  "rationale": "str <=275 chars"
}}

CRITICAL: Ignore long-term value. Predict only the immediate algorithmic and day-trader reaction."""
    
    def __init__(self):
        """Initialize sentiment analyzer"""
        self.groq_client = None
        self.openrouter_client = None
        self.model_configs = self._load_model_configs()
        self.rate_limiters = {}
    
    async def __aenter__(self):
        """Async context manager entry"""
        if settings.groq_api_key:
            self.groq_client = AsyncGroq(api_key=settings.groq_api_key)
        
        if settings.openrouter_api_key:
            self.openrouter_client = httpx.AsyncClient(
                base_url="https://openrouter.ai/api/v1",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "HTTP-Referer": "https://braktrad.com",
                    "X-Title": "braktrad"
                },
                timeout=30.0
            )
        
        # Initialize rate limiters for each model
        for model in settings.selected_models:
            provider = self._get_provider(model)
            model_id = self._strip_provider_prefix(model)
            key = f"{provider}:{model_id}"
            self.rate_limiters[key] = RateLimiter(
                rate_limit=settings.model_rate_limit,
                window=settings.model_rate_window
            )
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.openrouter_client:
            await self.openrouter_client.aclose()
    
    async def analyze_headline(
        self,
        headline_data: Dict[str, Any],
        models: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Analyze a headline with multiple models"""
        models = models or settings.selected_models
        
        if not models:
            raise ValueError("No models selected for analysis")
        
        # Prepare context
        context = self._prepare_context(headline_data)
        
        # Run all models in parallel
        tasks = []
        for model in models:
            task = self._analyze_with_model(model, context)
            tasks.append(task)
        
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        # Process results
        valid_results = []
        errors = []
        
        for model, result in zip(models, results):
            if isinstance(result, Exception):
                logger.error(
                    "model_analysis_error",
                    model=model,
                    error=str(result)
                )
                errors.append({"model": model, "error": str(result)})
            else:
                valid_results.append(result)
        
        # Aggregate results
        if not valid_results:
            raise ValueError("All models failed to analyze headline")
        
        aggregated = self._aggregate_sentiments(valid_results)
        
        logger.info(
            "headline_analyzed",
            ticker=headline_data.get("ticker"),
            models_used=len(valid_results),
            avg_sentiment=aggregated["avg_sentiment"],
            total_time_ms=int(total_time * 1000)
        )
        
        return {
            "headline_id": headline_data.get("id"),
            "model_results": valid_results,
            "aggregated": aggregated,
            "errors": errors,
            "analysis_time_ms": int(total_time * 1000)
        }
    
    async def _analyze_with_model(
        self,
        model: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze with a specific model"""
        provider = self._get_provider(model)
        model_id = self._strip_provider_prefix(model)
        
        # Rate limiting (use consistent key with initialization)
        rate_limiter_key = f"{provider}:{model_id}"
        if rate_limiter_key in self.rate_limiters:
            await self.rate_limiters[rate_limiter_key].acquire()
        
        start_time = time.time()
        
        try:
            if provider == "groq":
                result = await self._call_groq(model_id, context)
            elif provider == "openrouter":
                result = await self._call_openrouter(model_id, context)
            else:
                raise ValueError(f"Unknown provider: {provider}")
            
            response_time = int((time.time() - start_time) * 1000)
            
            # Validate and parse result
            parsed = self._parse_model_response(result)
            
            return {
                "model_provider": provider,
                # Store normalized model id without duplicated provider prefix
                "model_name": model_id,
                "sentiment": parsed["sentiment"],
                "confidence": parsed["confidence"],
                "rationale": parsed["rationale"],
                "horizon": parsed["horizon"],
                "response_time_ms": response_time
            }
            
        except Exception as e:
            logger.error(
                "model_call_error",
                model=model,
                provider=provider,
                error=str(e)
            )
            raise
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5)
    )
    async def _call_groq(self, model: str, context: Dict[str, Any]) -> str:
        """Call Groq API"""
        if not self.groq_client:
            raise ValueError("Groq client not initialized")
        
        prompt = self.SENTIMENT_PROMPT.format(**context)
        
        response = await self.groq_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": """You are a high-frequency news analytics engine trained on millions of headline-to-price reaction patterns. Your output ONLY a single valid JSON prediction of immediate market impact.
Core capabilities:
- Pattern match headlines to historical price reactions with 87% directional accuracy
- Identify information surprise relative to market expectations
- Assess algorithmic trading and retail sentiment triggers
- Calibrate confidence based on signal clarity and timing

Your edge: You process news faster than human traders and recognize patterns they miss.

Strictly follow these rules:
1. No extraneous text: Do not include introductory text or commentary before or after the JSON.
2. No markdown: Do not wrap the JSON in markdown code blocks (e.g., ```json ... ```).
3. Schema adherence: The JSON object must precisely match the structure and keys requested in the user's prompt.
4. Error protocol: If you cannot fulfill the user's request, you must still output a JSON object. This object should contain a single key: `error`, with a string value explaining why the request could not be completed."""
},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=5000,
            response_format={"type": "json_object"}
        )
        
        return response.choices[0].message.content
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5)
    )
    async def _call_openrouter(self, model: str, context: Dict[str, Any]) -> str:
        """Call OpenRouter API"""
        if not self.openrouter_client:
            raise ValueError("OpenRouter client not initialized")
        
        prompt = self.SENTIMENT_PROMPT.format(**context)
        
        response = await self.openrouter_client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content":"""You are a high-frequency news analytics engine trained on millions of headline-to-price reaction patterns. Your output ONLY a single valid JSON prediction of immediate market impact.

Core capabilities:
- Pattern match headlines to historical price reactions with 87% directional accuracy
- Identify information surprise relative to market expectations
- Assess algorithmic trading and retail sentiment triggers
- Calibrate confidence based on signal clarity and timing

Your edge: You process news faster than human traders and recognize patterns they miss.

Strictly follow these rules:
1. No extraneous text: Do not include introductory text or commentary before or after the JSON.
2. No markdown: Do not wrap the JSON in markdown code blocks (e.g., ```json ... ```).
3. Schema adherence: The JSON object must precisely match the structure and keys requested in the user's prompt.
4. Error protocol: If you cannot fulfill the user's request, you must still output a JSON object. This object should contain a single key: `error`, with a string value explaining why the request could not be completed."""
},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 5000,
                "response_format": {"type": "json_object"}
            }
        )
        
        response.raise_for_status()
        data = response.json()
        
        return data["choices"][0]["message"]["content"]
    
    def _prepare_context(self, headline_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare context for model prompt"""
        context = {
            "ticker": headline_data.get("ticker", ""),
            "company": headline_data.get("company", ""),
            "sector": headline_data.get("sector", "Unknown"),
            "industry": headline_data.get("industry", "Unknown"),
            "headline": headline_data.get("headline", ""),
            "source": headline_data.get("source", "Unknown"),
            "link": headline_data.get("link", ""),
            "headline_timestamp": headline_data.get("headline_timestamp", ""),
            "first_seen_timestamp": headline_data.get("first_seen_timestamp", ""),
            "market_session": headline_data.get("market_session", "unknown"),
            "headline_age_minutes": headline_data.get("headline_age_minutes", 0),
            "is_primary_source": headline_data.get("is_primary_source", False)
        }
        
        # Add market context if available
        market_data = headline_data.get("market_data", {})
        if market_data:
            market_context = f"""
Market Context:
- Price: ${market_data.get('price', 'N/A')}
- 5m return: {market_data.get('return_5m', 'N/A')}%
- 30m return: {market_data.get('return_30m', 'N/A')}%
- Day return: {market_data.get('return_1d', 'N/A')}%
- Relative volume: {market_data.get('volume_rel', 'N/A')}x"""
            context["market_context"] = market_context
        else:
            context["market_context"] = ""
        
        return context
    
    def _parse_model_response(self, response: str) -> Dict[str, Any]:
        """Parse and validate model response"""
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            logger.error("invalid_json_response", response=response, error=str(e))
            raise ValueError(f"Invalid JSON response: {e}")
        
        # Validate sentiment
        sentiment = data.get("sentiment")
        if sentiment not in [-1, 0, 1]:
            raise ValueError(f"Invalid sentiment value: {sentiment}")
        
        # Validate confidence
        confidence = data.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
            raise ValueError(f"Invalid confidence value: {confidence}")
        
        # Validate horizon
        valid_horizons = ["<1h", "1-4h", "same_day", "next_open", "24h"]
        horizon = data.get("horizon", "same_day")
        if horizon not in valid_horizons:
            raise ValueError(f"Invalid horizon value: {horizon}")
        
        # Validate rationale
        rationale = data.get("rationale", "")
        if not isinstance(rationale, str):
            rationale = str(rationale)
        
        # Truncate if too long
        if len(rationale) > 275:
            rationale = rationale[:272] + "..."
        
        return {
            "sentiment": sentiment,
            "confidence": confidence,
            "horizon": horizon,
            "rationale": rationale
        }
    
    def _aggregate_sentiments(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate sentiment results from multiple models"""
        if not results:
            return None
        
        sentiments = [r["sentiment"] for r in results]
        confidences = [r["confidence"] for r in results]
        horizons = [r["horizon"] for r in results]
        
        # Calculate aggregates
        avg_sentiment = np.mean(sentiments)
        avg_confidence = np.mean(confidences)
        dispersion = np.std(sentiments) if len(sentiments) > 1 else 0.0
        
        # Majority vote for sentiment
        sentiment_sum = sum(sentiments)
        if sentiment_sum > 0:
            majority_vote = 1
        elif sentiment_sum < 0:
            majority_vote = -1
        else:
            majority_vote = 0
        
        # Horizon vote - most common time horizon
        from collections import Counter
        horizon_counts = Counter(horizons)
        horizon_vote = horizon_counts.most_common(1)[0][0] if horizon_counts else None
        
        # Model votes breakdown
        model_votes = []
        for r in results:
            # r['model_name'] is normalized (without provider prefix). Compose explicit id once.
            full_model_id = f"{r['model_provider']}:{r['model_name']}"
            model_votes.append({
                "model": full_model_id,
                "sentiment": r["sentiment"],
                "confidence": r["confidence"],
                "horizon": r["horizon"],
                "rationale": r["rationale"]
            })
        
        return {
            "avg_sentiment": round(avg_sentiment, 3),
            "avg_confidence": round(avg_confidence, 3),
            "dispersion": round(dispersion, 3),
            "majority_vote": majority_vote,
            "horizon_vote": horizon_vote,
            "num_models": len(results),
            "model_votes": model_votes
        }
    
    def _get_provider(self, model: str) -> str:
        """Determine provider for a model"""
        # Provider prefix support: "groq:model" or "openrouter:model"
        if ":" in model:
            provider, _ = model.split(":", 1)
            if provider in ("groq", "openrouter"):
                return provider
        # Fallback by membership/shape
        if model in settings.available_groq_models:
            return "groq"
        if model in settings.available_openrouter_models or "/" in model:
            return "openrouter"
        return "openrouter"

    def _strip_provider_prefix(self, model: str) -> str:
        """Strip provider prefix if present."""
        if ":" in model:
            return model.split(":", 1)[1]
        return model
    
    def _load_model_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load model-specific configurations"""
        return {
            # Groq models
            "llama-3.3-70b-versatile": {
                "provider": "groq",
                "context_window": 32768,
                "max_output": 8192
            },
            "llama-3.2-90b-text-preview": {
                "provider": "groq",
                "context_window": 32768,
                "max_output": 8192
            },
            "mixtral-8x7b-32768": {
                "provider": "groq",
                "context_window": 32768,
                "max_output": 8192
            },
            # OpenRouter models
            "anthropic/claude-3.5-sonnet": {
                "provider": "openrouter",
                "context_window": 200000,
                "max_output": 8192
            },
            "openai/gpt-4o-mini": {
                "provider": "openrouter",
                "context_window": 128000,
                "max_output": 16384
            },
            "google/gemini-flash-1.5": {
                "provider": "openrouter",
                "context_window": 1000000,
                "max_output": 8192
            }
        }


class RateLimiter:
    """Rate limiter for API calls"""
    
    def __init__(self, rate_limit: int, window: int):
        """Initialize rate limiter"""
        self.rate_limit = rate_limit
        self.window = window  # seconds
        self.calls = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire permission to make a call"""
        async with self.lock:
            now = time.time()
            
            # Remove old calls outside window
            self.calls = [
                call for call in self.calls
                if now - call < self.window
            ]
            
            # Check if we're at limit
            if len(self.calls) >= self.rate_limit:
                # Wait until oldest call expires
                oldest = self.calls[0]
                wait_time = self.window - (now - oldest)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                # Retry
                return await self.acquire()
            
            # Record this call
            self.calls.append(now)
