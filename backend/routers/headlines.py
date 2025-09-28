"""Headlines API router"""

from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
import structlog

from models import Headline, SentimentAggregate, MarketData, UserSettings, PortfolioHolding
from services.finviz_client import FinvizClient, HeadlineDeduplicator
# from services.cache import cache_key, cached_result
from config import settings
from database import get_db

logger = structlog.get_logger()
router = APIRouter()


@router.get("/tickers")
async def get_available_tickers(
    portfolio_ids: Optional[List[int]] = Query(default=None),
    hours: int = Query(default=168, le=720),
    from_finviz_if_empty: bool = Query(default=True),
    db: AsyncSession = Depends(get_db)
):
    """Return distinct tickers and companies from recent headlines, or
    fall back to Finviz portfolios if none are present.
    """
    # Query distinct tickers from DB
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)

    query = (
        select(Headline.ticker, Headline.company)
        .where(Headline.headline_timestamp >= cutoff_time)
        .where(Headline.is_duplicate == False)
    )

    if portfolio_ids:
        query = query.where(Headline.portfolio_id.in_(portfolio_ids))

    query = query.distinct().order_by(Headline.ticker)

    result = await db.execute(query)
    rows = result.all()

    tickers = [
        {"ticker": r.ticker, "company": r.company}
        for r in rows if r.ticker
    ]

    if tickers:
        return {"tickers": tickers, "source": "headlines"}

    # Optional fallback to Finviz
    if from_finviz_if_empty and settings.finviz_api_key:
        try:
            portfolios = portfolio_ids or settings.finviz_portfolio_numbers
            if portfolios:
                from services.finviz_client import FinvizClient
                uniq = {}
                async with FinvizClient() as client:
                    for pid in portfolios:
                        try:
                            headlines = await client.fetch_portfolio_headlines(pid)
                            for h in headlines:
                                t = h.get("ticker")
                                c = h.get("company")
                                if t and t not in uniq:
                                    uniq[t] = c or t
                        except Exception as e:
                            logger.warning("finviz_tickers_fetch_error", portfolio_id=pid, error=str(e))
                tickers = [
                    {"ticker": t, "company": uniq[t]} for t in sorted(uniq.keys())
                ]
                if tickers:
                    return {"tickers": tickers, "source": "finviz"}
        except Exception as e:
            logger.error("tickers_fallback_error", error=str(e))

    return {"tickers": [], "source": "none"}

@router.post("/fetch")
async def fetch_headlines(
    background_tasks: BackgroundTasks,
    portfolio_id: Optional[int] = Query(default=None),
    sync: bool = Query(default=False),
    db: AsyncSession = Depends(get_db)
):
    """Fetch headlines from Finviz for a single portfolio (one API call).
    If sync=true, runs inline and returns counts; otherwise runs in background.
    """
    # Resolve portfolio id: explicit param or first configured
    pid: Optional[int] = portfolio_id
    if pid is None:
        if settings.finviz_portfolio_numbers:
            pid = settings.finviz_portfolio_numbers[0]
    
    if not pid:
        raise HTTPException(400, "No portfolio ID provided or configured")
    # Resolve API key from runtime or DB
    api_key = settings.finviz_api_key
    if not api_key:
        result = await db.execute(select(UserSettings).where(UserSettings.user_id == "default"))
        us = result.scalar_one_or_none()
        api_key = getattr(us, "finviz_api_key", None)
        if api_key:
            settings.finviz_api_key = api_key
    if not api_key:
        raise HTTPException(400, "Finviz API key not configured")

    if sync:
        result = await fetch_headlines_task_single(pid, db, api_key, return_result=True)
        return {
            "status": "completed",
            "portfolio_id": pid,
            **result
        }
    else:
        # Start background task (single call)
        background_tasks.add_task(fetch_headlines_task_single, pid, db, api_key)
        return {
            "status": "fetching",
            "portfolio_id": pid,
            "message": "Headlines fetch (single portfolio) initiated"
        }


async def fetch_headlines_task_single(portfolio_id: int, db: AsyncSession, api_key: str, return_result: bool = False):
    """Fetch once for a single portfolio via Finviz export. If return_result, returns counts."""
    try:
        async with FinvizClient(api_key=api_key) as client:
            try:
                headlines = await client.fetch_portfolio_headlines(portfolio_id)
                logger.info("fetched_portfolio", portfolio_id=portfolio_id, count=len(headlines))
            except Exception as e:
                logger.error("fetch_portfolio_error", portfolio_id=portfolio_id, error=str(e))
                headlines = []

            if not headlines:
                if return_result:
                    return {"fetched": 0, "stored": 0}
                return None

            # Enrich with sector/industry from holdings if available
            try:
                tickers = sorted({h.get("ticker") for h in headlines if h.get("ticker")})
                if tickers:
                    holding_rows = await db.execute(
                        select(PortfolioHolding).where(
                            (PortfolioHolding.portfolio_id == portfolio_id)
                            & (PortfolioHolding.ticker.in_(tickers))
                        )
                    )
                    rows = holding_rows.scalars().all()
                    by_ticker = {r.ticker: r for r in rows}
                    for h in headlines:
                        t = h.get("ticker")
                        r = by_ticker.get(t)
                        if r:
                            h["sector"] = r.sector
                            h["industry"] = r.industry
                            if not h.get("company") or h.get("company") == t:
                                h["company"] = r.company or t
            except Exception as e:
                logger.warning("enrich_headlines_from_holdings_error", portfolio_id=portfolio_id, error=str(e))

            # Deduplicate
            deduplicator = HeadlineDeduplicator(threshold=settings.dedupe_threshold)
            unique_headlines = deduplicator.deduplicate(headlines)

            # Persist
            stored = 0
            for data in unique_headlines:
                exists = await db.execute(
                    select(Headline).where(Headline.headline_hash == data["headline_hash"]) 
                )
                if exists.scalar_one_or_none():
                    continue
                db.add(Headline(**data))
                stored += 1
            await db.commit()
            logger.info("headlines_stored", portfolio_id=portfolio_id, stored=stored)
            if return_result:
                return {"fetched": len(headlines), "stored": stored}

    except Exception as e:
        logger.error("fetch_headlines_task_error", portfolio_id=portfolio_id, error=str(e), exc_info=True)
        if return_result:
            return {"error": str(e), "fetched": 0, "stored": 0}


@router.get("/")
async def get_headlines(
    ticker: Optional[str] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    source: Optional[str] = None,
    portfolio_id: Optional[int] = Query(default=None),
    hours: int = Query(default=24, le=168),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    include_sentiment: bool = Query(default=True),
    db: AsyncSession = Depends(get_db)
):
    """Get headlines with optional filters"""
    # Build query
    query = select(Headline)
    
    # Apply filters
    filters = []
    
    if ticker:
        filters.append(Headline.ticker == ticker.upper())
    
    if sector:
        filters.append(Headline.sector == sector)
    
    if industry:
        filters.append(Headline.industry == industry)
    
    if source:
        filters.append(Headline.source.ilike(f"%{source}%"))
    
    if portfolio_id is not None:
        filters.append(Headline.portfolio_id == portfolio_id)
    
    # Time filter
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)
    filters.append(Headline.headline_timestamp >= cutoff_time)
    
    # Exclude duplicates
    filters.append(Headline.is_duplicate == False)
    
    if filters:
        query = query.where(and_(*filters))
    
    # Order by timestamp
    query = query.order_by(Headline.headline_timestamp.desc())
    
    # Apply pagination
    query = query.limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    headlines = result.scalars().all()
    
    # Include sentiment if requested
    if include_sentiment and headlines:
        headline_ids = [h.id for h in headlines]
        
        # Fetch sentiment aggregates
        sentiment_result = await db.execute(
            select(SentimentAggregate).where(
                SentimentAggregate.headline_id.in_(headline_ids)
            )
        )
        
        sentiment_map = {
            s.headline_id: s
            for s in sentiment_result.scalars().all()
        }
        
        # Attach sentiment to headlines
        for headline in headlines:
            sentiment = sentiment_map.get(headline.id)
            if sentiment:
                headline.sentiment_aggregate = {
                    "avg_sentiment": sentiment.avg_sentiment,
                    "avg_confidence": sentiment.avg_confidence,
                    "dispersion": sentiment.dispersion,
                    "majority_vote": sentiment.majority_vote,
                    "num_models": sentiment.num_models,
                    "model_votes": sentiment.model_votes
                }
    
    # Build holdings map to override sector/industry if needed
    holdings_map = {}
    try:
        tickers = sorted({h.ticker for h in headlines if h.ticker})
        if tickers:
            holding_q = select(PortfolioHolding).where(PortfolioHolding.ticker.in_(tickers))
            # If portfolio filter provided, prefer holdings from that portfolio
            if portfolio_id is not None:
                holding_q = holding_q.where(PortfolioHolding.portfolio_id == portfolio_id)
            holding_res = await db.execute(holding_q)
            for r in holding_res.scalars().all():
                holdings_map[r.ticker] = r
    except Exception as e:
        logger.warning("holdings_override_error", error=str(e))

    # If some tickers missing from holdings, opportunistically fetch screener export once
    try:
        missing = [t for t in {h.ticker for h in headlines if h.ticker} if t not in holdings_map]
        if missing:
            # Determine portfolio to persist into: use explicit filter if provided, otherwise the only configured portfolio
            pid_for_persist = portfolio_id
            if pid_for_persist is None:
                try:
                    if settings.finviz_portfolio_numbers and len(settings.finviz_portfolio_numbers) == 1:
                        pid_for_persist = settings.finviz_portfolio_numbers[0]
                except Exception:
                    pid_for_persist = None

            # Resolve API key (from runtime settings or DB)
            api_key = settings.finviz_api_key
            if not api_key:
                result = await db.execute(select(UserSettings).where(UserSettings.user_id == "default"))
                us = result.scalar_one_or_none()
                api_key = getattr(us, "finviz_api_key", None)
                if api_key:
                    settings.finviz_api_key = api_key

            if settings.finviz_api_key:
                async with FinvizClient(api_key=settings.finviz_api_key) as client:
                    # Fetch in chunks to avoid long single call
                    CHUNK = 50
                    for i in range(0, len(missing), CHUNK):
                        chunk = missing[i:i+CHUNK]
                        items = await client.fetch_screener_export(chunk)
                        if not items:
                            continue
                        for it in items:
                            t = it.get("ticker")
                            if not t:
                                continue
                            # Update overlay map immediately
                            holdings_map[t] = type("_H", (), it)()
                            # Persist if we know which portfolio to attach to
                            if pid_for_persist is not None:
                                try:
                                    # Upsert DB row
                                    existing_q = await db.execute(
                                        select(PortfolioHolding).where(
                                            (PortfolioHolding.portfolio_id == pid_for_persist) & (PortfolioHolding.ticker == t)
                                        )
                                    )
                                    existing = existing_q.scalar_one_or_none()
                                    if existing:
                                        existing.company = it.get("company") or existing.company
                                        existing.sector = it.get("sector")
                                        existing.industry = it.get("industry")
                                        existing.exchange = it.get("exchange")
                                        existing.pe = it.get("pe")
                                        existing.beta = it.get("beta")
                                        existing.volume = it.get("volume")
                                        existing.price = it.get("price")
                                        existing.change = it.get("change")
                                    else:
                                        db.add(
                                            PortfolioHolding(
                                                portfolio_id=pid_for_persist,
                                                ticker=t,
                                                company=it.get("company") or t,
                                                sector=it.get("sector"),
                                                industry=it.get("industry"),
                                                exchange=it.get("exchange"),
                                                pe=it.get("pe"),
                                                beta=it.get("beta"),
                                                volume=it.get("volume"),
                                                price=it.get("price"),
                                                change=it.get("change"),
                                            )
                                        )
                                except Exception as e2:
                                    logger.warning("persist_screener_item_error", ticker=t, error=str(e2))
                    if pid_for_persist is not None:
                        try:
                            await db.commit()
                        except Exception:
                            pass
    except Exception as e:
        logger.warning("opportunistic_screener_fetch_error", error=str(e))

    # Format response
    return {
        "headlines": [
            {
                "id": str(h.id),
                "ticker": h.ticker,
                "company": (holdings_map.get(h.ticker).company if holdings_map.get(h.ticker) and getattr(holdings_map.get(h.ticker), "company", None) else h.company),
                "headline": h.headline,
                "source": h.source,
                "link": h.link,
                "timestamp": h.headline_timestamp.isoformat(),
                "age_minutes": h.headline_age_minutes,
                "market_session": h.market_session,
                "sector": (holdings_map.get(h.ticker).sector if holdings_map.get(h.ticker) and holdings_map.get(h.ticker).sector else h.sector),
                "industry": (holdings_map.get(h.ticker).industry if holdings_map.get(h.ticker) and holdings_map.get(h.ticker).industry else h.industry),
                "is_primary_source": h.is_primary_source,
                "sentiment": getattr(h, "sentiment_aggregate", None)
            }
            for h in headlines
        ],
        "total": len(headlines),
        "filters": {
            "ticker": ticker,
            "sector": sector,
            "industry": industry,
            "source": source,
            "hours": hours
        },
        "pagination": {
            "limit": limit,
            "offset": offset
        }
    }


@router.get("/{headline_id}")
async def get_headline_detail(
    headline_id: str,
    include_market_data: bool = Query(default=True),
    include_all_sentiments: bool = Query(default=False),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information for a specific headline"""
    # Fetch headline
    result = await db.execute(
        select(Headline).where(Headline.id == headline_id)
    )
    
    headline = result.scalar_one_or_none()
    
    if not headline:
        raise HTTPException(404, "Headline not found")
    
    response = {
        "id": str(headline.id),
        "ticker": headline.ticker,
        "company": headline.company,
        "headline": headline.headline,
        "normalized_headline": headline.normalized_headline,
        "source": headline.source,
        "link": headline.link,
        "timestamp": headline.headline_timestamp.isoformat(),
        "first_seen": headline.first_seen_timestamp.isoformat(),
        "age_minutes": headline.headline_age_minutes,
        "market_session": headline.market_session,
        "sector": headline.sector,
        "industry": headline.industry,
        "is_primary_source": headline.is_primary_source,
        "portfolio_id": headline.portfolio_id
    }
    
    # Include market data if requested
    if include_market_data:
        market_result = await db.execute(
            select(MarketData)
            .where(MarketData.headline_id == headline.id)
            .order_by(MarketData.timestamp.desc())
            .limit(1)
        )
        
        market_data = market_result.scalar_one_or_none()
        
        if market_data:
            response["market_data"] = {
                "price": market_data.price,
                "volume": market_data.volume,
                "volume_rel": market_data.volume_rel,
                "return_5m": market_data.return_5m,
                "return_30m": market_data.return_30m,
                "return_1d": market_data.return_1d,
                "volatility_1d": market_data.volatility_1d,
                "rsi": market_data.rsi,
                "timestamp": market_data.timestamp.isoformat()
            }
    
    # Include sentiment aggregate
    sentiment_result = await db.execute(
        select(SentimentAggregate).where(
            SentimentAggregate.headline_id == headline.id
        )
    )
    
    sentiment_agg = sentiment_result.scalar_one_or_none()
    
    if sentiment_agg:
        response["sentiment"] = {
            "avg_sentiment": sentiment_agg.avg_sentiment,
            "avg_confidence": sentiment_agg.avg_confidence,
            "dispersion": sentiment_agg.dispersion,
            "majority_vote": sentiment_agg.majority_vote,
            "num_models": sentiment_agg.num_models,
            "model_votes": sentiment_agg.model_votes if include_all_sentiments else None
        }
    
    # Include duplicates if any
    if headline.parent_headline_id:
        response["is_duplicate"] = True
        response["parent_id"] = str(headline.parent_headline_id)
    else:
        # Check for child duplicates
        duplicates_result = await db.execute(
            select(func.count(Headline.id)).where(
                Headline.parent_headline_id == headline.id
            )
        )
        
        duplicate_count = duplicates_result.scalar()
        
        if duplicate_count > 0:
            response["has_duplicates"] = True
            response["duplicate_count"] = duplicate_count
    
    return response


@router.delete("/{headline_id}")
async def delete_headline(
    headline_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a headline and its associated data"""
    # Fetch headline
    result = await db.execute(
        select(Headline).where(Headline.id == headline_id)
    )
    
    headline = result.scalar_one_or_none()
    
    if not headline:
        raise HTTPException(404, "Headline not found")
    
    # Delete headline (cascades to related data)
    await db.delete(headline)
    await db.commit()
    
    return {
        "status": "deleted",
        "headline_id": headline_id
    }
