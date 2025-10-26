"""Sentiment analysis API router"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import structlog
import numpy as np

from models import Headline, SentimentAnalysis, SentimentAggregate, UserSettings
from services.sentiment_analyzer import SentimentAnalyzer
from config import settings
from database import get_db
from database import AsyncSessionLocal
from fastapi import Request

logger = structlog.get_logger()
router = APIRouter()


async def ensure_settings_loaded(db: AsyncSession):
    """Ensure settings are loaded from database into global settings"""
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == "default")
        )
        user_settings = result.scalar_one_or_none()
        if user_settings:
            if user_settings.selected_models:
                settings.selected_models = user_settings.selected_models
            if user_settings.groq_api_key:
                settings.groq_api_key = user_settings.groq_api_key
            if user_settings.openrouter_api_key:
                settings.openrouter_api_key = user_settings.openrouter_api_key
    except Exception as e:
        logger.warning("failed_to_ensure_settings_loaded", error=str(e))


@router.post("/analyze/id/{headline_id}")
async def analyze_headline_sentiment(
    headline_id: UUID,
    background_tasks: BackgroundTasks,
    models: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db)
):
    """Analyze sentiment for a specific headline"""
    # Ensure settings are loaded
    await ensure_settings_loaded(db)
    
    # Fetch headline
    result = await db.execute(
        select(Headline).where(Headline.id == headline_id)
    )
    
    headline = result.scalar_one_or_none()
    
    if not headline:
        raise HTTPException(404, "Headline not found")
    
    # Check if already analyzed
    existing = await db.execute(
        select(SentimentAggregate).where(
            SentimentAggregate.headline_id == headline_id
        )
    )
    
    if existing.scalar_one_or_none():
        return {
            "status": "already_analyzed",
            "headline_id": str(headline_id),
            "message": "Headline already has sentiment analysis"
        }
    
    # Validate models
    models = models or settings.selected_models
    
    if not models:
        raise HTTPException(400, "No models selected for analysis")
    
    # Start background analysis
    background_tasks.add_task(
        analyze_headline_task,
        headline,
        models,
        db
    )
    
    return {
        "status": "analyzing",
        "headline_id": str(headline_id),
        "models": models,
        "message": "Sentiment analysis initiated in background"
    }


async def analyze_headline_task(
    headline: Headline,
    models: List[str],
    db: AsyncSession
):
    """Background task to analyze headline sentiment.
    NOTE: Opens its own DB session to avoid using request-scoped session in background.
    """
    try:
        # Prepare headline data
        headline_data = {
            "id": headline.id,
            "ticker": headline.ticker,
            "company": headline.company,
            "headline": headline.headline,
            "source": headline.source,
            "link": headline.link,
            "headline_timestamp": headline.headline_timestamp.isoformat(),
            "first_seen_timestamp": headline.first_seen_timestamp.isoformat(),
            "market_session": headline.market_session,
            "headline_age_minutes": headline.headline_age_minutes,
            "sector": headline.sector,
            "industry": headline.industry,
            "is_primary_source": headline.is_primary_source
        }

        # Run sentiment analysis
        async with SentimentAnalyzer() as analyzer:
            result = await analyzer.analyze_headline(headline_data, models)

        # Persist results using a fresh session (request-scoped session may be closed)
        async with AsyncSessionLocal() as session:
            # Check if already analyzed (race condition protection)
            existing_aggregate = await session.execute(
                select(SentimentAggregate).where(SentimentAggregate.headline_id == headline.id)
            )
            if existing_aggregate.scalar_one_or_none():
                logger.info("sentiment_analysis_skipped", headline_id=str(headline.id), reason="already_analyzed")
                return

            # Store individual model results
            for model_result in result["model_results"]:
                sentiment_analysis = SentimentAnalysis(
                    headline_id=headline.id,
                    model_provider=model_result["model_provider"],
                    model_name=model_result["model_name"],
                    sentiment=model_result["sentiment"],
                    confidence=model_result["confidence"],
                    rationale=model_result["rationale"],
                    horizon=model_result["horizon"],
                    response_time_ms=model_result["response_time_ms"]
                )
                session.add(sentiment_analysis)

            # Store aggregate
            aggregated = result["aggregated"]
            sentiment_aggregate = SentimentAggregate(
                headline_id=headline.id,
                avg_sentiment=aggregated["avg_sentiment"],
                avg_confidence=aggregated["avg_confidence"],
                dispersion=aggregated["dispersion"],
                majority_vote=aggregated["majority_vote"],
                horizon_vote=aggregated.get("horizon_vote"),
                num_models=aggregated["num_models"],
                model_votes=aggregated["model_votes"]
            )
            session.add(sentiment_aggregate)

            await session.commit()

        logger.info(
            "sentiment_analysis_complete",
            headline_id=str(headline.id),
            models_used=len(result["model_results"]),
            avg_sentiment=aggregated["avg_sentiment"]
        )

    except Exception as e:
        logger.error(
            "sentiment_analysis_error",
            headline_id=str(headline.id),
            error=str(e),
            exc_info=True
        )


async def generate_opportunities_after_analysis(headline_count: int):
    """Background task to generate opportunities after sentiment analysis completes"""
    try:
        # Wait a bit to ensure all sentiment analyses have completed and committed
        import asyncio
        await asyncio.sleep(2 + (headline_count * 0.5))  # Scale wait time with headline count
        
        # Import here to avoid circular dependencies
        from database import AsyncSessionLocal
        from routers.opportunities import generate_opportunities_internal
        
        # Generate opportunities using a new database session
        async with AsyncSessionLocal() as db:
            result = await generate_opportunities_internal(
                min_confidence=0.6,
                min_models=2,
                hours=6,
                db=db
            )
            
            logger.info(
                "auto_generate_opportunities_complete",
                status=result.get("status"),
                count=result.get("count", 0),
                trigger="sentiment_analysis"
            )
    except Exception as e:
        logger.error(
            "auto_generate_opportunities_error",
            error=str(e),
            exc_info=True
        )


@router.post("/analyze/batch")
async def analyze_batch_sentiments(
    background_tasks: BackgroundTasks,
    headline_ids: Optional[List[str]] = None,
    hours: int = 1,
    models: Optional[List[str]] = None,
    auto_generate_opportunities: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """Analyze sentiment for multiple headlines"""
    # Get headlines to analyze
    if headline_ids:
        # Specific headlines
        result = await db.execute(
            select(Headline).where(
                and_(
                    Headline.id.in_(headline_ids),
                    ~Headline.sentiments.any(),  # No existing sentiment analysis
                    ~select(SentimentAggregate).where(SentimentAggregate.headline_id == Headline.id).exists()  # No existing aggregate
                )
            )
        )
    else:
        # Recent unanalyzed headlines
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        result = await db.execute(
            select(Headline).where(
                and_(
                    Headline.headline_timestamp >= cutoff,
                    ~Headline.sentiments.any(),
                    ~select(SentimentAggregate).where(SentimentAggregate.headline_id == Headline.id).exists(),
                    Headline.is_duplicate == False
                )
            ).limit(100)
        )
    
    headlines = result.scalars().all()
    
    if not headlines:
        return {
            "status": "no_headlines",
            "message": "No unanalyzed headlines found"
        }
    
    # Validate models
    models = models or settings.selected_models
    
    if not models:
        raise HTTPException(400, "No models selected for analysis")
    
    # Start background analysis for each headline
    for headline in headlines:
        background_tasks.add_task(
            analyze_headline_task,
            headline,
            models,
            db
        )
    
    # Schedule opportunity generation after analysis completes
    if auto_generate_opportunities and len(headlines) > 0:
        background_tasks.add_task(
            generate_opportunities_after_analysis,
            len(headlines)
        )
    
    return {
        "status": "analyzing",
        "count": len(headlines),
        "models": models,
        "message": f"Sentiment analysis initiated for {len(headlines)} headlines",
        "auto_generate_opportunities": auto_generate_opportunities
    }


@router.post("/analyze/recent")
async def analyze_recent(
    background_tasks: BackgroundTasks,
    last_n: Optional[int] = None,
    hours: Optional[int] = None,
    models: Optional[List[str]] = None,
    auto_generate_opportunities: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """On-demand endpoint to analyze either last N headlines or last N hours (unanalyzed only)."""
    if (last_n is not None) and (hours is not None):
        raise HTTPException(400, "Provide either last_n or hours, not both")

    # Ensure settings are loaded
    await ensure_settings_loaded(db)

    # Determine target set
    if last_n:
        result = await db.execute(
            select(Headline)
            .where(
                ~Headline.sentiments.any(), 
                ~select(SentimentAggregate).where(SentimentAggregate.headline_id == Headline.id).exists(),
                Headline.is_duplicate == False
            )
            .order_by(Headline.headline_timestamp.desc())
            .limit(max(1, min(last_n, 500)))
        )
    else:
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=max(1, min(hours or 1, 48)))
        result = await db.execute(
            select(Headline)
            .where(
                Headline.headline_timestamp >= cutoff,
                ~Headline.sentiments.any(),
                ~select(SentimentAggregate).where(SentimentAggregate.headline_id == Headline.id).exists(),
                Headline.is_duplicate == False
            )
            .order_by(Headline.headline_timestamp.desc())
            .limit(500)
        )

    headlines = result.scalars().all()
    if not headlines:
        return {"status": "no_headlines", "message": "No unanalyzed headlines found"}

    # Validate models
    models = models or settings.selected_models
    if not models:
        raise HTTPException(400, "No models selected for analysis")

    for headline in headlines:
        background_tasks.add_task(analyze_headline_task, headline, models, db)

    # Schedule opportunity generation after analysis completes
    if auto_generate_opportunities and len(headlines) > 0:
        background_tasks.add_task(
            generate_opportunities_after_analysis,
            len(headlines)
        )

    return {
        "status": "analyzing",
        "count": len(headlines),
        "models": models,
        "message": f"Initiated analysis for {len(headlines)} headlines",
        "auto_generate_opportunities": auto_generate_opportunities
    }


@router.post("/analyze/schedule")
async def schedule_periodic_analysis(request: Request, interval_seconds: int = 300):
    """Enable a periodic job to analyze recent headlines (best-effort)."""
    task_scheduler = getattr(request.app.state, "task_scheduler", None)
    if not task_scheduler:
        raise HTTPException(503, "Scheduler not available")

    # Add or replace a periodic sentiment task
    import asyncio

    async def periodic_task():
        from database import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            try:
                # Reuse the on-demand function with hours=1 window
                await analyze_recent(BackgroundTasks(), None, 1, None, s)  # type: ignore
            except Exception:
                pass

    # Cancel existing if any
    if "sentiment_recent" in task_scheduler.tasks:
        task_scheduler.tasks["sentiment_recent"].cancel()
        try:
            await task_scheduler.tasks["sentiment_recent"]
        except Exception:
            pass

    task_scheduler.tasks["sentiment_recent"] = asyncio.create_task(
        task_scheduler._run_periodically(periodic_task, max(60, interval_seconds))
    )

    return {"status": "scheduled", "interval_seconds": max(60, interval_seconds)}


@router.get("/models")
async def get_available_models(db: AsyncSession = Depends(get_db)):
    """Get list of available sentiment models"""
    # Ensure settings are up-to-date by reloading from database
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == "default")
        )
        user_settings = result.scalar_one_or_none()
        if user_settings and user_settings.selected_models:
            settings.selected_models = user_settings.selected_models
        if user_settings and user_settings.groq_api_key:
            settings.groq_api_key = user_settings.groq_api_key
        if user_settings and user_settings.openrouter_api_key:
            settings.openrouter_api_key = user_settings.openrouter_api_key
    except Exception as e:
        logger.warning("failed_to_reload_settings", error=str(e))
    
    return {
        "groq_models": settings.available_groq_models,
        "openrouter_models": settings.available_openrouter_models,
        "selected_models": settings.selected_models,
        "groq_configured": bool(settings.groq_api_key),
        "openrouter_configured": bool(settings.openrouter_api_key)
    }


@router.get("/aggregate/{headline_id}")
async def get_sentiment_aggregate(
    headline_id: str,
    include_details: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """Get aggregated sentiment for a headline"""
    # Fetch aggregate
    result = await db.execute(
        select(SentimentAggregate).where(
            SentimentAggregate.headline_id == headline_id
        )
    )
    
    aggregate = result.scalar_one_or_none()
    
    if not aggregate:
        raise HTTPException(404, "Sentiment analysis not found for headline")
    
    response = {
        "headline_id": headline_id,
        "avg_sentiment": aggregate.avg_sentiment,
        "avg_confidence": aggregate.avg_confidence,
        "dispersion": aggregate.dispersion,
        "majority_vote": aggregate.majority_vote,
        "num_models": aggregate.num_models
    }
    
    if include_details:
        response["model_votes"] = aggregate.model_votes
        
        # Fetch individual analyses
        analyses_result = await db.execute(
            select(SentimentAnalysis).where(
                SentimentAnalysis.headline_id == headline_id
            )
        )
        
        analyses = analyses_result.scalars().all()
        
        response["individual_analyses"] = [
            {
                "model_provider": a.model_provider,
                "model_name": a.model_name,
                "sentiment": a.sentiment,
                "confidence": a.confidence,
                "rationale": a.rationale,
                "horizon": a.horizon,
                "response_time_ms": a.response_time_ms
            }
            for a in analyses
        ]
    
    return response


@router.get("/comparison")
async def compare_model_performance(
    ticker: Optional[str] = None,
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    """Compare performance across different models"""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    
    # Build query
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    query = select(
        SentimentAnalysis.model_provider,
        SentimentAnalysis.model_name,
        func.count(SentimentAnalysis.id).label("count"),
        func.avg(SentimentAnalysis.sentiment).label("avg_sentiment"),
        func.avg(SentimentAnalysis.confidence).label("avg_confidence"),
        func.avg(SentimentAnalysis.response_time_ms).label("avg_response_time")
    ).join(
        Headline
    ).where(
        Headline.headline_timestamp >= cutoff
    )
    
    if ticker:
        query = query.where(Headline.ticker == ticker.upper())
    
    query = query.group_by(
        SentimentAnalysis.model_provider,
        SentimentAnalysis.model_name
    )
    
    # Execute query
    result = await db.execute(query)
    comparisons = result.all()
    
    # Format response
    return {
        "comparisons": [
            {
                "model": f"{c.model_provider}:{c.model_name}",
                "provider": c.model_provider,
                "name": c.model_name,
                "analysis_count": c.count,
                "avg_sentiment": round(c.avg_sentiment, 3) if c.avg_sentiment else 0,
                "avg_confidence": round(c.avg_confidence, 3) if c.avg_confidence else 0,
                "avg_response_time_ms": round(c.avg_response_time) if c.avg_response_time else 0
            }
            for c in comparisons
        ],
        "filters": {
            "ticker": ticker,
            "hours": hours
        }
    }
