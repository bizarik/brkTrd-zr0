from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence, Set

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, settings
from ..database import AsyncSessionLocal
from ..models import Headline
from .cache import CacheManager
from .finviz_client import FinvizClient, HeadlineDeduplicator

logger = structlog.get_logger(__name__)

try:  # Optional Prometheus metrics; safe no-op when unavailable.
    from prometheus_client import Counter, Gauge, Histogram
except Exception:  # pragma: no cover - metrics export is optional
    Counter = Gauge = Histogram = None  # type: ignore


INGEST_FETCH_COUNTER = (
    Counter(
        "braktrad_ingestion_fetch_total",
        "Total Finviz ingestion fetch operations.",
        ["status", "source"],
    )
    if Counter
    else None
)

INGEST_DURATION_HISTOGRAM = (
    Histogram(
        "braktrad_ingestion_duration_seconds",
        "Finviz ingestion duration per portfolio.",
        ["portfolio_id"],
    )
    if Histogram
    else None
)

SCHEDULER_LAST_SUCCESS_GAUGE = (
    Gauge(
        "braktrad_scheduler_last_success_timestamp",
        "UTC timestamp of the last successful ingestion run.",
    )
    if Gauge
    else None
)

DEFAULT_CONCURRENCY = 3
CACHE_INVALIDATION_PATTERNS = (
    "headlines:*",
    "analytics:summary:*",
    "returns:ticker:*",
)

__all__ = [
    "ingest_portfolios",
    "ingest_single_portfolio",
    "cleanup_expired_records",
    "invalidate_downstream_caches",
]


async def ingest_portfolios(
    portfolio_ids: list[int] | None,
    db: AsyncSession,
    *,
    api_key: str | None = None,
    settings_override: Settings | None = None,
) -> dict[str, Any]:
    """
    Orchestrate ingestion for one or more Finviz portfolios.

    Args:
        portfolio_ids: Explicit portfolio identifiers to pull; when ``None`` the
            configured portfolio list is used.
        db: An async SQLAlchemy session (used for binding / compatibility).
        api_key: Optional API key override for Finviz.
        settings_override: Optional settings instance (defaults to global settings).

    Returns:
        Aggregated ingestion metadata (counts, per-portfolio details, error tally).
    """
    settings_obj = settings_override or settings
    enabled_flag = _flag_enabled(settings_obj, "INGESTION_V2_ENABLED")
    target_portfolios = portfolio_ids or list(
        getattr(settings_obj, "finviz_portfolio_numbers", []) or []
    )

    if not enabled_flag:
        logger.info(
            "ingestion_disabled",
            reason="feature_flag",
            portfolios=target_portfolios,
        )
        return {
            "status": "disabled",
            "portfolio_ids": target_portfolios,
            "details": [],
        }

    if not target_portfolios:
        logger.warning(
            "ingestion_no_portfolios_configured",
            portfolios=target_portfolios,
        )
        return {
            "status": "skipped",
            "portfolio_ids": [],
            "details": [],
            "errors": 0,
        }

    cache_manager = _resolve_cache_manager()
    overall: dict[str, Any] = {
        "status": "pending",
        "portfolio_ids": target_portfolios,
        "details": [],
        "errors": 0,
        "persisted": 0,
    }

    async with FinvizClient(api_key=api_key or getattr(settings_obj, "finviz_api_key", None)) as client:
        semaphore = asyncio.Semaphore(DEFAULT_CONCURRENCY)

        async def worker(portfolio_id: int) -> dict[str, Any]:
            async with semaphore:
                async with AsyncSessionLocal() as session:
                    return await ingest_single_portfolio(
                        portfolio_id,
                        session,
                        client,
                        settings_obj=settings_obj,
                        cache_manager=cache_manager,
                    )

        tasks = [asyncio.create_task(worker(pid)) for pid in target_portfolios]

        for task in asyncio.as_completed(tasks):
            try:
                result = await task
                overall["details"].append(result)
                overall["persisted"] += result.get("persisted", 0)
            except Exception as exc:  # pragma: no cover - defensive logging
                overall["errors"] += 1
                logger.exception("ingestion_portfolio_failure", error=str(exc))

    overall["status"] = "completed" if overall["errors"] == 0 else "partial"

    if overall["errors"] == 0 and SCHEDULER_LAST_SUCCESS_GAUGE:
        SCHEDULER_LAST_SUCCESS_GAUGE.set(datetime.now(timezone.utc).timestamp())

    return overall


async def ingest_single_portfolio(
    portfolio_id: int,
    db: AsyncSession,
    client: FinvizClient,
    *,
    settings_obj: Settings,
    cache_manager: CacheManager | None = None,
) -> dict[str, Any]:
    """
    Fetch, deduplicate, and persist headlines for a single Finviz portfolio.

    Args:
        portfolio_id: Finviz portfolio identifier.
        db: Async SQLAlchemy session used for persistence.
        client: Shared Finviz client.
        settings_obj: Settings instance (used for dedupe thresholds / retention).
        cache_manager: Optional cache manager for lock + invalidation.

    Returns:
        Summary metrics for the ingestion pass.
    """
    start_time = time.perf_counter()
    tickers: Set[str] = set()
    lock_acquired = False
    lock_key = f"ingestion:portfolio:{portfolio_id}:lock"

    if cache_manager and getattr(cache_manager, "redis", None):
        try:
            lock_acquired = await cache_manager.redis.set(lock_key, "1", nx=True, ex=300)
        except Exception as exc:  # pragma: no cover - lock best effort
            logger.warning(
                "ingestion_lock_failed",
                portfolio_id=portfolio_id,
                error=str(exc),
            )

    if cache_manager and not lock_acquired:
        logger.warning(
            "ingestion_lock_not_acquired",
            portfolio_id=portfolio_id,
        )
        return {
            "portfolio_id": portfolio_id,
            "status": "skipped",
            "reason": "lock_not_acquired",
            "fetched": 0,
            "persisted": 0,
            "duplicates": 0,
            "duration_seconds": 0.0,
        }

    try:
        raw_headlines = await client.fetch_portfolio_headlines(portfolio_id)
    except Exception as exc:
        if INGEST_FETCH_COUNTER:
            INGEST_FETCH_COUNTER.labels(status="error", source="finviz").inc()
        logger.exception(
            "ingestion_fetch_failed",
            portfolio_id=portfolio_id,
            error=str(exc),
        )
        return {
            "portfolio_id": portfolio_id,
            "status": "error",
            "error": str(exc),
            "fetched": 0,
            "persisted": 0,
            "duplicates": 0,
            "duration_seconds": 0.0,
        }
    finally:
        if cache_manager and lock_acquired:
            with contextlib.suppress(Exception):
                await cache_manager.redis.delete(lock_key)

    if INGEST_FETCH_COUNTER:
        status_label = "success" if raw_headlines else "empty"
        INGEST_FETCH_COUNTER.labels(status=status_label, source="finviz").inc()

    if not raw_headlines:
        duration = time.perf_counter() - start_time
        if INGEST_DURATION_HISTOGRAM:
            INGEST_DURATION_HISTOGRAM.labels(portfolio_id=str(portfolio_id)).observe(duration)
        logger.info(
            "ingestion_fetch_empty",
            portfolio_id=portfolio_id,
            duration_seconds=duration,
        )
        return {
            "portfolio_id": portfolio_id,
            "status": "empty",
            "fetched": 0,
            "persisted": 0,
            "duplicates": 0,
            "duration_seconds": duration,
        }

    deduplicator = HeadlineDeduplicator()
    deduped_payload = deduplicator.deduplicate(raw_headlines)

    headline_hashes = [
        item.get("headline_hash")
        for item in deduped_payload
        if item.get("headline_hash")
    ]
    existing_stmt = select(Headline.headline_hash, Headline.id).where(
        Headline.headline_hash.in_(headline_hashes)
    )
    existing_result = await db.execute(existing_stmt)
    existing_map = {row.headline_hash: row.id for row in existing_result}

    seen_hashes: Set[str] = set()
    new_instances: list[Headline] = []
    duplicate_count = 0

    for item in deduped_payload:
        headline_hash = item.get("headline_hash")
        if not headline_hash:
            duplicate_count += 1
            continue
        if headline_hash in existing_map or headline_hash in seen_hashes:
            duplicate_count += 1
            continue

        seen_hashes.add(headline_hash)
        ticker = (item.get("ticker") or "").upper().strip()
        if ticker:
            tickers.add(ticker)

        new_instances.append(
            Headline(
                ticker=ticker or "UNKNOWN",
                company=item.get("company") or ticker or "Unknown",
                headline=item.get("headline", ""),
                normalized_headline=item.get("normalized_headline", "").strip()
                or item.get("headline", "").lower(),
                source=item.get("source") or "Unknown",
                link=item.get("link") or "",
                is_primary_source=bool(item.get("is_primary_source", False)),
                headline_timestamp=_normalize_timestamp(item.get("headline_timestamp")),
                first_seen_timestamp=_normalize_timestamp(
                    item.get("first_seen_timestamp") or item.get("headline_timestamp")
                ),
                market_session=_normalize_market_session(item.get("market_session")),
                headline_age_minutes=item.get("headline_age_minutes"),
                sector=item.get("sector"),
                industry=item.get("industry"),
                headline_hash=headline_hash,
                portfolio_id=portfolio_id,
            )
        )

    try:
        for instance in new_instances:
            db.add(instance)

        await db.commit()
    except Exception as exc:  # pragma: no cover - persistence error logging
        await db.rollback()
        logger.exception(
            "ingestion_persist_failed",
            portfolio_id=portfolio_id,
            error=str(exc),
        )
        raise
    finally:
        await invalidate_downstream_caches(cache_manager, tickers=tickers)

    duration = time.perf_counter() - start_time
    if INGEST_DURATION_HISTOGRAM:
        INGEST_DURATION_HISTOGRAM.labels(portfolio_id=str(portfolio_id)).observe(duration)

    logger.info(
        "ingestion_portfolio_complete",
        portfolio_id=portfolio_id,
        fetched=len(raw_headlines),
        persisted=len(new_instances),
        duplicates=duplicate_count,
        duration_seconds=duration,
    )

    return {
        "portfolio_id": portfolio_id,
        "status": "success",
        "fetched": len(raw_headlines),
        "persisted": len(new_instances),
        "duplicates": duplicate_count,
        "duration_seconds": duration,
        "tickers": sorted(tickers),
    }


async def cleanup_expired_records(
    db: AsyncSession,
    *,
    max_age_hours: int | None = None,
    cache_manager: CacheManager | None = None,
) -> dict[str, Any]:
    """
    Remove stale headlines older than the configured retention window.

    Args:
        db: Async SQLAlchemy session.
        max_age_hours: Optional override for retention window.
        cache_manager: Optional cache manager for invalidation.

    Returns:
        Summary containing deleted row count and affected tickers.
    """
    settings_obj = settings
    retention_hours = (
        max_age_hours
        or getattr(settings_obj, "max_headline_age_hours", None)
        or 24
    )
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

    result = await db.execute(
        select(Headline.id, Headline.ticker).where(Headline.headline_timestamp < cutoff)
    )
    rows = result.all()
    ids_to_delete = [row.id for row in rows]
    affected_tickers = {row.ticker for row in rows if row.ticker}

    if ids_to_delete:
        await db.execute(delete(Headline).where(Headline.id.in_(ids_to_delete)))
        await db.commit()
    else:
        await db.rollback()

    cache_manager = cache_manager or _resolve_cache_manager()
    await invalidate_downstream_caches(cache_manager, tickers=affected_tickers)

    logger.info(
        "ingestion_cleanup_completed",
        deleted=len(ids_to_delete),
        cutoff=cutoff.isoformat(),
    )

    return {
        "deleted": len(ids_to_delete),
        "cutoff": cutoff.isoformat(),
        "tickers": sorted(affected_tickers),
    }


async def invalidate_downstream_caches(
    cache_manager: CacheManager | None,
    *,
    tickers: Set[str] | None = None,
) -> None:
    """
    Bust cache entries influenced by headline ingestion.

    Args:
        cache_manager: Optional cache manager. When ``None`` the call is a no-op.
        tickers: Optional set of tickers to target for fine-grained invalidation.
    """
    if not cache_manager:
        logger.debug("cache_invalidation_skipped", reason="cache_manager_missing")
        return

    try:
        for pattern in CACHE_INVALIDATION_PATTERNS:
            await cache_manager.delete_pattern(pattern)

        if tickers:
            for ticker in tickers:
                ticker_key = cache_manager.cache_key("returns:ticker", ticker=ticker)
                analytics_key = cache_manager.cache_key("analytics:summary", ticker=ticker)
                await cache_manager.delete(ticker_key)
                await cache_manager.delete(analytics_key)
    except Exception as exc:  # pragma: no cover - cache best effort
        logger.warning("cache_invalidation_failed", error=str(exc))


def _flag_enabled(settings_obj: Settings, attribute: str) -> bool:
    """
    Lookup helper that tolerates different casing for feature flags.
    """
    value = getattr(settings_obj, attribute, None)
    if value is None:
        value = getattr(settings_obj, attribute.lower(), None)
    if value is None:
        return True
    return bool(value)


def _normalize_timestamp(raw_value: Any) -> datetime:
    """
    Ensure timestamps are timezone-aware UTC datetimes.
    """
    if isinstance(raw_value, datetime):
        if raw_value.tzinfo is None:
            return raw_value.replace(tzinfo=timezone.utc)
        return raw_value.astimezone(timezone.utc)

    if isinstance(raw_value, str):
        with contextlib.suppress(ValueError):
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

    return datetime.now(timezone.utc)


def _normalize_market_session(raw_value: Any) -> str:
    """
    Convert MarketSession enums to their string values.
    """
    if raw_value is None:
        return "regular"
    value = getattr(raw_value, "value", raw_value)
    return str(value)


def _resolve_cache_manager() -> CacheManager | None:
    """
    Attempt to import the shared cache manager from the FastAPI app.
    """
    with contextlib.suppress(Exception):
        from ..main import cache_manager as global_cache_manager  # type: ignore

        return global_cache_manager
    return None