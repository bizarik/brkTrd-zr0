"""API routes for historical returns and sentiment comparisons"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Headline, SentimentReturns, SentimentAggregate, MarketData
from ..services.market_data import calculate_returns

router = APIRouter(prefix="/api/returns", tags=["returns"])


@router.get("/historical/{ticker}")
async def get_historical_returns(
    ticker: str,
    days: int = Query(default=30, le=365),
    db: AsyncSession = Depends(get_db)
):
    """Get historical returns data for a ticker"""
    # TODO: Implement historical returns endpoint
    # This will be implemented when we add actual trading returns tracking
    pass


@router.get("/sentiment/{headline_id}")
async def get_sentiment_returns(
    headline_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get returns data for a specific headline's sentiment analysis"""
    # Query the sentiment returns
    result = await db.execute(
        select(SentimentReturns)
        .where(SentimentReturns.headline_id == headline_id)
    )
    returns = result.scalar_one_or_none()
    
    if not returns:
        raise HTTPException(status_code=404, detail="Sentiment returns not found")
    
    # Get the headline details
    headline_result = await db.execute(
        select(Headline).where(Headline.id == headline_id)
    )
    headline = headline_result.scalar_one_or_none()
    
    if not headline:
        raise HTTPException(status_code=404, detail="Headline not found")
    
    return {
        "headline": {
            "id": headline.id,
            "ticker": headline.ticker,
            "headline": headline.headline,
            "timestamp": headline.headline_timestamp.isoformat()
        },
        "sentiment": {
            "value": returns.sentiment_value,
            "confidence": returns.sentiment_confidence
        },
        "returns": {
            "3h": {
                "return": returns.return_3h,
                "price": returns.price_3h,
                "timestamp": returns.timestamp_3h.isoformat() if returns.timestamp_3h else None
            },
            "24h": {
                "return": returns.return_24h,
                "price": returns.price_24h,
                "timestamp": returns.timestamp_24h.isoformat() if returns.timestamp_24h else None
            },
            "next_day": {
                "return": returns.return_next_day,
                "price": returns.price_next_day,
                "timestamp": returns.timestamp_next_day.isoformat() if returns.timestamp_next_day else None
            },
            "2d": {
                "return": returns.return_2d,
                "price": returns.price_2d,
                "timestamp": returns.timestamp_2d.isoformat() if returns.timestamp_2d else None
            },
            "3d": {
                "return": returns.return_3d,
                "price": returns.price_3d,
                "timestamp": returns.timestamp_3d.isoformat() if returns.timestamp_3d else None
            },
            "prev_1d": {
                "return": returns.return_prev_1d,
                "price": returns.price_prev_1d,
                "timestamp": returns.timestamp_prev_1d.isoformat() if returns.timestamp_prev_1d else None
            },
            "prev_2d": {
                "return": returns.return_prev_2d,
                "price": returns.price_prev_2d,
                "timestamp": returns.timestamp_prev_2d.isoformat() if returns.timestamp_prev_2d else None
            }
        }
    }


@router.get("/sentiment/ticker/{ticker}")
async def get_ticker_sentiment_returns(
    ticker: str,
    days: int = Query(default=30, le=365),
    min_confidence: float = Query(default=0.6, ge=0, le=1),
    db: AsyncSession = Depends(get_db)
):
    """Get sentiment returns comparison data for a ticker"""
    cutoff_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    
    # Query sentiment returns for the ticker
    result = await db.execute(
        select(SentimentReturns, Headline)
        .join(Headline, SentimentReturns.headline_id == Headline.id)
        .where(
            and_(
                Headline.ticker == ticker.upper(),
                Headline.headline_timestamp >= cutoff_date,
                SentimentReturns.sentiment_confidence >= min_confidence
            )
        )
        .order_by(desc(Headline.headline_timestamp))
    )
    
    returns = result.all()
    
    return {
        "ticker": ticker.upper(),
        "sentiment_returns": [
            {
                "headline_id": str(r.SentimentReturns.headline_id),
                "headline": r.Headline.headline,
                "timestamp": r.Headline.headline_timestamp.isoformat(),
                "sentiment": {
                    "value": r.SentimentReturns.sentiment_value,
                    "confidence": r.SentimentReturns.sentiment_confidence
                },
                "returns": {
                    "3h": r.SentimentReturns.return_3h,
                    "24h": r.SentimentReturns.return_24h,
                    "next_day": r.SentimentReturns.return_next_day,
                    "2d": r.SentimentReturns.return_2d,
                    "3d": r.SentimentReturns.return_3d,
                    "prev_1d": r.SentimentReturns.return_prev_1d,
                    "prev_2d": r.SentimentReturns.return_prev_2d
                }
            }
            for r in returns
        ]
    }


@router.post("/calculate/{headline_id}")
async def calculate_sentiment_returns(
    headline_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Calculate and store returns for a headline's sentiment analysis"""
    # Get the headline and its sentiment
    result = await db.execute(
        select(Headline, SentimentAggregate)
        .join(SentimentAggregate, SentimentAggregate.headline_id == Headline.id)
        .where(Headline.id == headline_id)
    )
    data = result.first()
    
    if not data:
        raise HTTPException(status_code=404, detail="Headline or sentiment not found")
    
    headline, sentiment = data
    
    # Get market data for the calculation periods
    market_data_result = await db.execute(
        select(MarketData)
        .where(
            and_(
                MarketData.ticker == headline.ticker,
                MarketData.timestamp >= headline.headline_timestamp
            )
        )
        .order_by(MarketData.timestamp)
    )
    market_data = market_data_result.scalars().all()
    
    if not market_data:
        raise HTTPException(status_code=404, detail="No market data found")
    
    # Calculate returns
    returns = await calculate_returns(
        headline=headline,
        sentiment=sentiment,
        market_data=market_data,
        db=db
    )
    
    return {
        "headline_id": str(headline_id),
        "ticker": headline.ticker,
        "calculated_returns": returns
    }
