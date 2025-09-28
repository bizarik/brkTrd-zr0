"""Market data and returns calculation service"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Headline, SentimentAggregate, MarketData, SentimentReturns


def is_market_hours(dt: datetime) -> bool:
    """Check if a datetime is during market hours (9:30 AM - 4:00 PM ET)"""
    # Convert to US/Eastern
    hour = dt.hour
    minute = dt.minute
    
    # Check if time is between 9:30 AM and 4:00 PM ET
    if hour < 9 or hour > 16:
        return False
    if hour == 9 and minute < 30:
        return False
    return True


def get_next_market_close(dt: datetime) -> datetime:
    """Get the next market close time (4:00 PM ET)"""
    close = dt.replace(hour=16, minute=0, second=0, microsecond=0)
    if dt >= close:
        close += timedelta(days=1)
    return close


def get_next_market_open(dt: datetime) -> datetime:
    """Get the next market open time (9:30 AM ET)"""
    open_time = dt.replace(hour=9, minute=30, second=0, microsecond=0)
    if dt >= open_time:
        open_time += timedelta(days=1)
    return open_time


def calculate_return(start_price: float, end_price: float) -> float:
    """Calculate percentage return between two prices"""
    if not start_price or not end_price:
        return None
    return ((end_price - start_price) / start_price) * 100


def find_closest_price(target_time: datetime, market_data: List[MarketData], 
                      max_diff_minutes: int = 15) -> Optional[Dict[str, Any]]:
    """Find the closest price data point to a target time"""
    if not market_data:
        return None
        
    closest = None
    min_diff = timedelta(minutes=max_diff_minutes)
    
    for data in market_data:
        diff = abs(data.timestamp - target_time)
        if diff < min_diff:
            min_diff = diff
            closest = data
            
    if closest:
        return {
            "price": closest.price,
            "timestamp": closest.timestamp
        }
    return None


async def calculate_returns(
    headline: Headline,
    sentiment: SentimentAggregate,
    market_data: List[MarketData],
    db: AsyncSession
) -> Dict[str, Any]:
    """Calculate returns for different timeframes"""
    
    # Get the sentiment timestamp (when analysis was done)
    sentiment_time = sentiment.created_at
    
    # Find the price at sentiment time
    sentiment_price_data = find_closest_price(sentiment_time, market_data)
    if not sentiment_price_data:
        return None
        
    # Initialize returns object
    returns = SentimentReturns(
        headline_id=headline.id,
        sentiment_value=sentiment.majority_vote,
        sentiment_confidence=sentiment.avg_confidence,
        price_at_sentiment=sentiment_price_data["price"],
        timestamp_at_sentiment=sentiment_price_data["timestamp"]
    )
    
    # Calculate 3-hour return (or end of day)
    target_3h = min(
        sentiment_time + timedelta(hours=3),
        get_next_market_close(sentiment_time)
    )
    price_3h = find_closest_price(target_3h, market_data)
    if price_3h:
        returns.price_3h = price_3h["price"]
        returns.timestamp_3h = price_3h["timestamp"]
        returns.return_3h = calculate_return(
            returns.price_at_sentiment, returns.price_3h
        )
    
    # Calculate 24-hour return (trading hours only)
    target_24h = sentiment_time + timedelta(hours=24)
    price_24h = find_closest_price(target_24h, market_data)
    if price_24h:
        returns.price_24h = price_24h["price"]
        returns.timestamp_24h = price_24h["timestamp"]
        returns.return_24h = calculate_return(
            returns.price_at_sentiment, returns.price_24h
        )
    
    # Calculate next trading day close
    next_close = get_next_market_close(sentiment_time)
    price_next_day = find_closest_price(next_close, market_data)
    if price_next_day:
        returns.price_next_day = price_next_day["price"]
        returns.timestamp_next_day = price_next_day["timestamp"]
        returns.return_next_day = calculate_return(
            returns.price_at_sentiment, returns.price_next_day
        )
    
    # Calculate 2-day return
    target_2d = next_close + timedelta(days=1)
    price_2d = find_closest_price(target_2d, market_data)
    if price_2d:
        returns.price_2d = price_2d["price"]
        returns.timestamp_2d = price_2d["timestamp"]
        returns.return_2d = calculate_return(
            returns.price_at_sentiment, returns.price_2d
        )
    
    # Calculate 3-day return
    target_3d = target_2d + timedelta(days=1)
    price_3d = find_closest_price(target_3d, market_data)
    if price_3d:
        returns.price_3d = price_3d["price"]
        returns.timestamp_3d = price_3d["timestamp"]
        returns.return_3d = calculate_return(
            returns.price_at_sentiment, returns.price_3d
        )
    
    # Calculate previous day's return
    prev_close = sentiment_time.replace(hour=16, minute=0, second=0, microsecond=0)
    if sentiment_time >= prev_close:
        prev_close += timedelta(days=1)
    prev_close -= timedelta(days=1)
    
    price_prev_1d = find_closest_price(prev_close, market_data)
    if price_prev_1d:
        returns.price_prev_1d = price_prev_1d["price"]
        returns.timestamp_prev_1d = price_prev_1d["timestamp"]
        returns.return_prev_1d = calculate_return(
            price_prev_1d["price"], returns.price_at_sentiment
        )
    
    # Calculate 2 days prior return
    prev_2d_close = prev_close - timedelta(days=1)
    price_prev_2d = find_closest_price(prev_2d_close, market_data)
    if price_prev_2d:
        returns.price_prev_2d = price_prev_2d["price"]
        returns.timestamp_prev_2d = price_prev_2d["timestamp"]
        returns.return_prev_2d = calculate_return(
            price_prev_2d["price"], returns.price_at_sentiment
        )
    
    # Save to database
    db.add(returns)
    await db.commit()
    await db.refresh(returns)
    
    return {
        "3h": returns.return_3h,
        "24h": returns.return_24h,
        "next_day": returns.return_next_day,
        "2d": returns.return_2d,
        "3d": returns.return_3d,
        "prev_1d": returns.return_prev_1d,
        "prev_2d": returns.return_prev_2d
    }
