"""Trading opportunities API router"""

from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
import structlog
import numpy as np

from models import (
    TradingOpportunity, Headline, SentimentAggregate, 
    MarketData, TimeHorizon
)
from config import settings
from database import get_db

logger = structlog.get_logger()
router = APIRouter()


async def generate_opportunities_internal(
    min_confidence: float,
    min_models: int,
    hours: int,
    db: AsyncSession
) -> dict:
    """Internal function to generate trading opportunities from recent sentiment analysis"""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    # Query headlines with strong sentiment signals
    query = select(
        Headline,
        SentimentAggregate
    ).join(
        SentimentAggregate
    ).where(
        and_(
            Headline.headline_timestamp >= cutoff,
            Headline.is_duplicate == False,
            SentimentAggregate.avg_confidence >= min_confidence,
            SentimentAggregate.num_models >= min_models,
            SentimentAggregate.majority_vote != 0  # Non-neutral
        )
    )
    
    result = await db.execute(query)
    opportunities_data = result.all()
    
    if not opportunities_data:
        return {
            "status": "no_opportunities",
            "message": "No high-confidence opportunities found"
        }
    
    # Group by ticker
    ticker_groups = {}
    for headline, sentiment in opportunities_data:
        ticker = headline.ticker
        if ticker not in ticker_groups:
            ticker_groups[ticker] = []
        ticker_groups[ticker].append((headline, sentiment))
    
    # Generate opportunities
    opportunities = []
    
    for ticker, group in ticker_groups.items():
        # Calculate aggregate metrics for ticker
        sentiments = [s.avg_sentiment for h, s in group]
        confidences = [s.avg_confidence for h, s in group]
        
        avg_sentiment = np.mean(sentiments)
        avg_confidence = np.mean(confidences)
        
        # Skip if mixed signals
        if np.std(sentiments) > 0.5:
            continue
        
        # Determine opportunity type
        if avg_sentiment > 0.3:
            opportunity_type = "long"
        elif avg_sentiment < -0.3:
            opportunity_type = "short"
        else:
            continue
        
        # Get latest market data
        market_result = await db.execute(
            select(MarketData)
            .where(MarketData.ticker == ticker)
            .order_by(MarketData.timestamp.desc())
            .limit(1)
        )
        
        market_data = market_result.scalar_one_or_none()
        
        # Calculate opportunity score
        score = calculate_opportunity_score(
            avg_sentiment,
            avg_confidence,
            len(group),
            market_data
        )
        
        # Determine time horizon
        horizon = determine_horizon(group)
        
        # Create opportunity
        opportunity = TradingOpportunity(
            ticker=ticker,
            opportunity_type=opportunity_type,
            score=score,
            confidence=avg_confidence,
            priority=int(score * 100),
            horizon=horizon,
            time_sensitivity=get_time_sensitivity(horizon),
            supporting_headlines=[h.id for h, s in group],
            sentiment_summary={
                "avg_sentiment": round(avg_sentiment, 3),
                "avg_confidence": round(avg_confidence, 3),
                "headline_count": len(group),
                "latest_headline": group[0][0].headline
            },
            status="active"
        )
        
        # Set entry/exit if market data available
        if market_data:
            set_trade_parameters(opportunity, market_data, opportunity_type)
            opportunity.market_context = {
                "price": market_data.price,
                "volume_rel": market_data.volume_rel,
                "return_1d": market_data.return_1d,
                "rsi": market_data.rsi
            }
        
        db.add(opportunity)
        opportunities.append(opportunity)
    
    await db.commit()
    
    return {
        "status": "generated",
        "count": len(opportunities),
        "opportunities": [
            format_opportunity(opp)
            for opp in sorted(opportunities, key=lambda x: x.score, reverse=True)
        ]
    }


@router.post("/generate")
async def generate_opportunities(
    min_confidence: float = Query(default=0.6, ge=0, le=1),
    min_models: int = Query(default=2, ge=1),
    hours: int = Query(default=6, le=24),
    db: AsyncSession = Depends(get_db)
):
    """Generate trading opportunities from recent sentiment analysis (API endpoint)"""
    return await generate_opportunities_internal(
        min_confidence=min_confidence,
        min_models=min_models,
        hours=hours,
        db=db
    )


@router.get("/")
async def get_opportunities(
    status: str = Query(default="active"),
    opportunity_type: Optional[str] = None,
    min_score: float = Query(default=0, ge=0, le=1),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Get trading opportunities"""
    # Build query
    query = select(TradingOpportunity).where(
        and_(
            TradingOpportunity.status == status,
            TradingOpportunity.score >= min_score
        )
    )
    
    if opportunity_type:
        query = query.where(
            TradingOpportunity.opportunity_type == opportunity_type
        )
    
    # Order by priority/score
    query = query.order_by(
        TradingOpportunity.priority.desc(),
        TradingOpportunity.score.desc()
    ).limit(limit)
    
    # Execute query
    result = await db.execute(query)
    opportunities = result.scalars().all()
    
    return {
        "opportunities": [
            format_opportunity(opp) for opp in opportunities
        ],
        "filters": {
            "status": status,
            "opportunity_type": opportunity_type,
            "min_score": min_score
        }
    }


@router.get("/{opportunity_id}")
async def get_opportunity_detail(
    opportunity_id: str,
    include_headlines: bool = Query(default=True),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information for a trading opportunity"""
    # Fetch opportunity
    result = await db.execute(
        select(TradingOpportunity).where(
            TradingOpportunity.id == opportunity_id
        )
    )
    
    opportunity = result.scalar_one_or_none()
    
    if not opportunity:
        raise HTTPException(404, "Opportunity not found")
    
    response = format_opportunity(opportunity)
    
    # Include supporting headlines if requested
    if include_headlines and opportunity.supporting_headlines:
        headlines_result = await db.execute(
            select(Headline, SentimentAggregate)
            .join(SentimentAggregate)
            .where(Headline.id.in_(opportunity.supporting_headlines))
        )
        
        headlines_data = headlines_result.all()
        
        response["headlines"] = [
            {
                "id": str(h.id),
                "headline": h.headline,
                "source": h.source,
                "timestamp": h.headline_timestamp.isoformat(),
                "sentiment": s.avg_sentiment,
                "confidence": s.avg_confidence
            }
            for h, s in headlines_data
        ]
    
    return response


@router.put("/{opportunity_id}/parameters")
async def update_opportunity_parameters(
    opportunity_id: str,
    entry_price: Optional[float] = None,
    target_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    position_size: Optional[float] = None,
    db: AsyncSession = Depends(get_db)
):
    """Update trade parameters for an opportunity"""
    # Fetch opportunity
    result = await db.execute(
        select(TradingOpportunity).where(
            TradingOpportunity.id == opportunity_id
        )
    )
    
    opportunity = result.scalar_one_or_none()
    
    if not opportunity:
        raise HTTPException(404, "Opportunity not found")
    
    # Update parameters
    if entry_price is not None:
        opportunity.entry_price = entry_price
    
    if target_price is not None:
        opportunity.target_price = target_price
    
    if stop_loss is not None:
        opportunity.stop_loss = stop_loss
    
    if position_size is not None:
        opportunity.position_size = position_size
    
    # Recalculate risk metrics
    if opportunity.entry_price and opportunity.target_price and opportunity.stop_loss:
        calculate_risk_metrics(opportunity)
    
    await db.commit()
    
    return {
        "status": "updated",
        "opportunity": format_opportunity(opportunity)
    }


@router.put("/{opportunity_id}/status")
async def update_opportunity_status(
    opportunity_id: str,
    status: str,
    db: AsyncSession = Depends(get_db)
):
    """Update status of an opportunity"""
    valid_statuses = ["active", "executed", "expired", "cancelled"]
    
    if status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_statuses}")
    
    # Fetch opportunity
    result = await db.execute(
        select(TradingOpportunity).where(
            TradingOpportunity.id == opportunity_id
        )
    )
    
    opportunity = result.scalar_one_or_none()
    
    if not opportunity:
        raise HTTPException(404, "Opportunity not found")
    
    opportunity.status = status
    await db.commit()
    
    return {
        "status": "updated",
        "opportunity_id": opportunity_id,
        "new_status": status
    }


# Helper functions

def calculate_opportunity_score(
    sentiment: float,
    confidence: float,
    headline_count: int,
    market_data: Optional[MarketData]
) -> float:
    """Calculate opportunity score (0-1)"""
    # Base score from sentiment and confidence
    base_score = abs(sentiment) * confidence
    
    # Boost for multiple confirming headlines
    headline_boost = min(0.2, headline_count * 0.05)
    
    # Market data adjustments
    market_boost = 0
    
    if market_data:
        # Momentum confirmation
        if market_data.return_1d:
            if (sentiment > 0 and market_data.return_1d > 0) or \
               (sentiment < 0 and market_data.return_1d < 0):
                market_boost += 0.1
        
        # Volume confirmation
        if market_data.volume_rel and market_data.volume_rel > 1.5:
            market_boost += 0.05
        
        # RSI extremes
        if market_data.rsi:
            if (sentiment > 0 and market_data.rsi < 30) or \
               (sentiment < 0 and market_data.rsi > 70):
                market_boost += 0.1
    
    return min(1.0, base_score + headline_boost + market_boost)


def determine_horizon(group: List[tuple]) -> str:
    """Determine time horizon from sentiment analyses"""
    # Get all horizons from sentiment data
    horizons = []
    
    for headline, sentiment in group:
        if sentiment.model_votes:
            for vote in sentiment.model_votes:
                if "horizon" in vote:
                    horizons.append(vote["horizon"])
    
    if not horizons:
        return "same_day"
    
    # Return most common horizon
    from collections import Counter
    most_common = Counter(horizons).most_common(1)[0][0]
    return most_common


def get_time_sensitivity(horizon: str) -> str:
    """Get time sensitivity label from horizon"""
    sensitivity_map = {
        "<1m": "URGENT",
        "1-5m": "HIGH",
        "5-30m": "MEDIUM",
        "same_day": "MODERATE",
        "overnight": "LOW",
        "1-3d": "LOW"
    }
    return sensitivity_map.get(horizon, "MODERATE")


def set_trade_parameters(
    opportunity: TradingOpportunity,
    market_data: MarketData,
    opportunity_type: str
):
    """Set entry, target, and stop loss prices"""
    current_price = market_data.price
    
    # Use volatility for targets if available
    volatility = market_data.volatility_1d or (current_price * 0.02)
    
    if opportunity_type == "long":
        opportunity.entry_price = current_price
        opportunity.target_price = current_price + (2 * volatility)
        opportunity.stop_loss = current_price - volatility
    else:  # short
        opportunity.entry_price = current_price
        opportunity.target_price = current_price - (2 * volatility)
        opportunity.stop_loss = current_price + volatility
    
    # Calculate risk metrics
    calculate_risk_metrics(opportunity)


def calculate_risk_metrics(opportunity: TradingOpportunity):
    """Calculate risk/reward metrics"""
    if not all([opportunity.entry_price, opportunity.target_price, opportunity.stop_loss]):
        return
    
    entry = opportunity.entry_price
    target = opportunity.target_price
    stop = opportunity.stop_loss
    
    # Risk/reward ratio
    risk = abs(entry - stop)
    reward = abs(target - entry)
    
    if risk > 0:
        opportunity.risk_reward_ratio = round(reward / risk, 2)
    
    # Position sizing (example: 1% portfolio risk)
    if opportunity.position_size:
        opportunity.max_risk_amount = opportunity.position_size * risk


def format_opportunity(opportunity: TradingOpportunity) -> dict:
    """Format opportunity for response"""
    return {
        "id": str(opportunity.id),
        "ticker": opportunity.ticker,
        "type": opportunity.opportunity_type,
        "score": round(opportunity.score, 3),
        "confidence": round(opportunity.confidence, 3),
        "priority": opportunity.priority,
        "horizon": opportunity.horizon,
        "time_sensitivity": opportunity.time_sensitivity,
        "entry_price": opportunity.entry_price,
        "target_price": opportunity.target_price,
        "stop_loss": opportunity.stop_loss,
        "position_size": opportunity.position_size,
        "risk_reward_ratio": opportunity.risk_reward_ratio,
        "sentiment_summary": opportunity.sentiment_summary,
        "market_context": opportunity.market_context,
        "status": opportunity.status,
        "created_at": opportunity.created_at.isoformat(),
        "expiry_time": opportunity.expiry_time.isoformat() if opportunity.expiry_time else None
    }
