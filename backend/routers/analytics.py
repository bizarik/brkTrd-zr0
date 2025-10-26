"""Analytics API router"""

from typing import Optional, List
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
import structlog

from models import Analytics, Headline, SentimentAggregate
from config import settings
from database import get_db

logger = structlog.get_logger()
router = APIRouter()


@router.get("/summary")
async def get_analytics_summary(
    time_bucket: str = Query(default="day", pattern="^(day|week|month)$"),
    ticker: Optional[str] = None,
    sector: Optional[str] = None,
    days: int = Query(default=7, le=30),
    db: AsyncSession = Depends(get_db)
):
    """Get analytics summary"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Build query
    query = select(Analytics).where(
        and_(
            Analytics.time_bucket == time_bucket,
            Analytics.bucket_date >= cutoff
        )
    )
    
    if ticker:
        query = query.where(Analytics.ticker == ticker.upper())
    
    if sector:
        query = query.where(Analytics.sector == sector)
    
    query = query.order_by(Analytics.bucket_date.desc())
    
    # Execute query
    result = await db.execute(query)
    analytics = result.scalars().all()
    
    return {
        "analytics": [
            {
                "date": a.bucket_date.isoformat(),
                "ticker": a.ticker,
                "sector": a.sector,
                "industry": a.industry,
                "headline_count": a.headline_count,
                "avg_sentiment": a.avg_sentiment,
                "avg_confidence": a.avg_confidence,
                "positive_count": a.positive_count,
                "neutral_count": a.neutral_count,
                "negative_count": a.negative_count
            }
            for a in analytics
        ],
        "filters": {
            "time_bucket": time_bucket,
            "ticker": ticker,
            "sector": sector,
            "days": days
        }
    }


@router.get("/word-cloud")
async def get_word_cloud(
    sentiment_filter: Optional[str] = Query(default=None, pattern="^(positive|neutral|negative)$"),
    ticker: Optional[str] = None,
    hours: int = Query(default=24, le=168),
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Generate word cloud data from headlines"""
    from collections import Counter
    import re
    
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    # Build query
    query = select(Headline, SentimentAggregate).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= cutoff
    )
    
    if ticker:
        query = query.where(Headline.ticker == ticker.upper())
    
    if sentiment_filter:
        if sentiment_filter == "positive":
            query = query.where(SentimentAggregate.avg_sentiment > 0.2)
        elif sentiment_filter == "negative":
            query = query.where(SentimentAggregate.avg_sentiment < -0.2)
        else:  # neutral
            query = query.where(
                and_(
                    SentimentAggregate.avg_sentiment >= -0.2,
                    SentimentAggregate.avg_sentiment <= 0.2
                )
            )
    
    # Execute query
    result = await db.execute(query)
    data = result.all()
    
    # Extract and count words
    word_counts = Counter()
    stopwords = get_stopwords()
    
    for headline, sentiment in data:
        # Tokenize headline
        words = re.findall(r'\b[a-z]+\b', headline.normalized_headline.lower())
        
        # Filter stopwords and short words
        words = [w for w in words if w not in stopwords and len(w) > 2]
        
        # Weight by sentiment strength
        weight = abs(sentiment.avg_sentiment)
        
        for word in words:
            word_counts[word] += weight
    
    # Get top words
    top_words = word_counts.most_common(limit)
    
    return {
        "words": [
            {"text": word, "value": round(count, 2)}
            for word, count in top_words
        ],
        "filters": {
            "sentiment": sentiment_filter,
            "ticker": ticker,
            "hours": hours
        }
    }


@router.get("/trends")
async def get_sentiment_trends(
    ticker: Optional[str] = None,
    sector: Optional[str] = None,
    days: int = Query(default=7, le=30),
    db: AsyncSession = Depends(get_db)
):
    """Get sentiment trends over time"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Query daily aggregates
    query = select(
        func.date(Headline.headline_timestamp).label("date"),
        func.count(Headline.id).label("headline_count"),
        func.avg(SentimentAggregate.avg_sentiment).label("avg_sentiment"),
        func.avg(SentimentAggregate.avg_confidence).label("avg_confidence")
    ).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= cutoff
    )
    
    if ticker:
        query = query.where(Headline.ticker == ticker.upper())
    
    if sector:
        query = query.where(Headline.sector == sector)
    
    query = query.group_by(func.date(Headline.headline_timestamp))
    query = query.order_by(func.date(Headline.headline_timestamp))
    
    # Execute query
    result = await db.execute(query)
    trends = result.all()
    
    return {
        "trends": [
            {
                "date": t.date.isoformat(),
                "headline_count": t.headline_count,
                "avg_sentiment": round(t.avg_sentiment, 3) if t.avg_sentiment else 0,
                "avg_confidence": round(t.avg_confidence, 3) if t.avg_confidence else 0
            }
            for t in trends
        ],
        "filters": {
            "ticker": ticker,
            "sector": sector,
            "days": days
        }
    }


@router.get("/top-movers")
async def get_top_movers(
    direction: str = Query(default="both", pattern="^(positive|negative|both)$"),
    hours: int = Query(default=24, le=168),
    limit: int = Query(default=10, le=50),
    db: AsyncSession = Depends(get_db)
):
    """Get top sentiment movers"""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    # Query aggregated sentiment by ticker
    query = select(
        Headline.ticker,
        Headline.company,
        func.count(Headline.id).label("headline_count"),
        func.avg(SentimentAggregate.avg_sentiment).label("avg_sentiment"),
        func.avg(SentimentAggregate.avg_confidence).label("avg_confidence")
    ).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= cutoff
    ).group_by(
        Headline.ticker,
        Headline.company
    )
    
    # Apply direction filter
    if direction == "positive":
        query = query.having(func.avg(SentimentAggregate.avg_sentiment) > 0)
        query = query.order_by(func.avg(SentimentAggregate.avg_sentiment).desc())
    elif direction == "negative":
        query = query.having(func.avg(SentimentAggregate.avg_sentiment) < 0)
        query = query.order_by(func.avg(SentimentAggregate.avg_sentiment))
    else:  # both
        query = query.order_by(func.abs(func.avg(SentimentAggregate.avg_sentiment)).desc())
    
    query = query.limit(limit)
    
    # Execute query
    result = await db.execute(query)
    movers = result.all()
    
    return {
        "movers": [
            {
                "ticker": m.ticker,
                "company": m.company,
                "headline_count": m.headline_count,
                "avg_sentiment": round(m.avg_sentiment, 3) if m.avg_sentiment else 0,
                "avg_confidence": round(m.avg_confidence, 3) if m.avg_confidence else 0,
                "sentiment_label": get_sentiment_label(m.avg_sentiment)
            }
            for m in movers
        ],
        "filters": {
            "direction": direction,
            "hours": hours,
            "limit": limit
        }
    }


@router.get("/sentiment-scatter-daily")
async def get_sentiment_scatter_daily(
    hours: int = Query(default=24, le=168),
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Calculate sentiment change as: current sentiment (last 24h) vs previous day's sentiment (24-48h ago)
    
    Returns scatter plot data where:
    - x-axis: Current average sentiment per ticker
    - y-axis: Change in sentiment from previous day
    """
    now = datetime.utcnow()
    
    # Query current period (last 24h)
    current_cutoff = now - timedelta(hours=hours)
    current_query = select(
        Headline.ticker,
        Headline.company,
        func.avg(SentimentAggregate.avg_sentiment).label("current_sentiment"),
        func.avg(SentimentAggregate.avg_confidence).label("current_confidence"),
        func.count(Headline.id).label("headline_count")
    ).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= current_cutoff,
        Headline.is_duplicate == False
    ).group_by(
        Headline.ticker,
        Headline.company
    )
    
    # Query previous period (24-48h ago for daily comparison)
    prev_start = now - timedelta(hours=hours * 2)
    prev_end = now - timedelta(hours=hours)
    previous_query = select(
        Headline.ticker,
        func.avg(SentimentAggregate.avg_sentiment).label("previous_sentiment")
    ).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= prev_start,
        Headline.headline_timestamp < prev_end,
        Headline.is_duplicate == False
    ).group_by(
        Headline.ticker
    )
    
    # Execute both queries
    current_result = await db.execute(current_query)
    previous_result = await db.execute(previous_query)
    
    # Build dictionaries for easy lookup
    current_data = {r.ticker: r for r in current_result}
    previous_data = {r.ticker: r.previous_sentiment for r in previous_result}
    
    # Calculate sentiment changes
    scatter_data = []
    for ticker, current in current_data.items():
        current_sentiment = round(current.current_sentiment, 3) if current.current_sentiment else 0.0
        previous_sentiment = round(previous_data.get(ticker, 0.0), 3)
        sentiment_change = round(current_sentiment - previous_sentiment, 3)
        
        scatter_data.append({
            "ticker": ticker,
            "company": current.company or ticker,
            "current_sentiment": current_sentiment,
            "sentiment_change": sentiment_change,
            "headline_count": current.headline_count,
            "current_confidence": round(current.current_confidence, 3) if current.current_confidence else 0.0
        })
    
    # Sort by absolute sentiment change and limit
    scatter_data.sort(key=lambda x: abs(x["sentiment_change"]), reverse=True)
    scatter_data = scatter_data[:limit]
    
    return {
        "data": scatter_data,
        "filters": {
            "timeframe": "daily",
            "hours": hours,
            "limit": limit
        }
    }


@router.get("/sentiment-scatter-intraday")
async def get_sentiment_scatter_intraday(
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Calculate intraday sentiment change: recent (last 6h) vs earlier today (6-12h ago)
    
    Returns scatter plot data showing intraday sentiment shifts
    """
    now = datetime.utcnow()
    
    # Query recent period (last 6 hours)
    recent_query = select(
        Headline.ticker,
        Headline.company,
        func.avg(SentimentAggregate.avg_sentiment).label("recent_sentiment"),
        func.avg(SentimentAggregate.avg_confidence).label("recent_confidence"),
        func.count(Headline.id).label("headline_count")
    ).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= now - timedelta(hours=6),
        Headline.is_duplicate == False
    ).group_by(
        Headline.ticker,
        Headline.company
    )
    
    # Query earlier period (6-12 hours ago)
    earlier_query = select(
        Headline.ticker,
        func.avg(SentimentAggregate.avg_sentiment).label("earlier_sentiment")
    ).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= now - timedelta(hours=12),
        Headline.headline_timestamp < now - timedelta(hours=6),
        Headline.is_duplicate == False
    ).group_by(
        Headline.ticker
    )
    
    # Execute both queries
    recent_result = await db.execute(recent_query)
    earlier_result = await db.execute(earlier_query)
    
    # Build dictionaries
    recent_data = {r.ticker: r for r in recent_result}
    earlier_data = {r.ticker: r.earlier_sentiment for r in earlier_result}
    
    # Calculate sentiment changes
    scatter_data = []
    for ticker, recent in recent_data.items():
        recent_sentiment = round(recent.recent_sentiment, 3) if recent.recent_sentiment else 0.0
        earlier_sentiment = round(earlier_data.get(ticker, 0.0), 3)
        sentiment_change = round(recent_sentiment - earlier_sentiment, 3)
        
        scatter_data.append({
            "ticker": ticker,
            "company": recent.company or ticker,
            "current_sentiment": recent_sentiment,
            "sentiment_change": sentiment_change,
            "headline_count": recent.headline_count,
            "recent_confidence": round(recent.recent_confidence, 3) if recent.recent_confidence else 0.0
        })
    
    # Sort by absolute sentiment change and limit
    scatter_data.sort(key=lambda x: abs(x["sentiment_change"]), reverse=True)
    scatter_data = scatter_data[:limit]
    
    return {
        "data": scatter_data,
        "filters": {
            "timeframe": "intraday",
            "limit": limit
        }
    }


@router.get("/sentiment-scatter-momentum")
async def get_sentiment_scatter_momentum(
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Calculate sentiment momentum/velocity based on 3-day trend using linear regression approach
    
    Returns scatter plot data where momentum represents the rate of sentiment change
    """
    now = datetime.utcnow()
    
    # Query sentiment data from last 72 hours, grouped by ticker and 24h buckets
    query = select(
        Headline.ticker,
        Headline.company,
        func.date(Headline.headline_timestamp).label("date_bucket"),
        func.avg(SentimentAggregate.avg_sentiment).label("sentiment"),
        func.count(Headline.id).label("headline_count")
    ).join(
        SentimentAggregate
    ).where(
        Headline.headline_timestamp >= now - timedelta(hours=72),
        Headline.is_duplicate == False
    ).group_by(
        Headline.ticker,
        Headline.company,
        func.date(Headline.headline_timestamp)
    ).order_by(
        Headline.ticker,
        func.date(Headline.headline_timestamp)
    )
    
    result = await db.execute(query)
    data = result.all()
    
    # Group by ticker and calculate momentum (slope of sentiment over time)
    ticker_data = defaultdict(list)
    
    for row in data:
        ticker_data[row.ticker].append({
            "company": row.company,
            "date": row.date_bucket,
            "sentiment": round(row.sentiment, 3) if row.sentiment else 0.0,
            "headline_count": row.headline_count
        })
    
    # Calculate momentum for each ticker (simple slope calculation)
    scatter_data = []
    for ticker, points in ticker_data.items():
        if len(points) < 2:
            # Need at least 2 data points to calculate momentum
            continue
        
        # Sort by date
        points.sort(key=lambda x: x["date"])
        
        # Calculate simple linear regression slope (momentum)
        n = len(points)
        sum_x = sum(range(n))
        sum_y = sum(p["sentiment"] for p in points)
        sum_xy = sum(i * p["sentiment"] for i, p in enumerate(points))
        sum_x_sq = sum(i * i for i in range(n))
        
        # Slope formula: (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x²) - sum(x)²)
        if n * sum_x_sq - sum_x * sum_x != 0:
            momentum = (n * sum_xy - sum_x * sum_y) / (n * sum_x_sq - sum_x * sum_x)
        else:
            momentum = 0.0
        
        current_sentiment = points[-1]["sentiment"]
        total_headlines = sum(p["headline_count"] for p in points)
        
        scatter_data.append({
            "ticker": ticker,
            "company": points[0]["company"] or ticker,
            "current_sentiment": current_sentiment,
            "momentum": round(momentum, 3),
            "headline_count": total_headlines,
            "data_points": n
        })
    
    # Sort by absolute momentum and limit
    scatter_data.sort(key=lambda x: abs(x["momentum"]), reverse=True)
    scatter_data = scatter_data[:limit]
    
    return {
        "data": scatter_data,
        "filters": {
            "timeframe": "momentum",
            "lookback_hours": 72,
            "limit": limit
        }
    }


def get_stopwords() -> set:
    """Get common stopwords to filter"""
    return {
        "the", "be", "to", "of", "and", "a", "in", "that", "have",
        "i", "it", "for", "not", "on", "with", "he", "as", "you",
        "do", "at", "this", "but", "his", "by", "from", "they",
        "we", "say", "her", "she", "or", "an", "will", "my", "one",
        "all", "would", "there", "their", "what", "so", "up", "out",
        "if", "about", "who", "get", "which", "go", "me", "when",
        "make", "can", "like", "time", "no", "just", "him", "know",
        "take", "people", "into", "year", "your", "good", "some",
        "could", "them", "see", "other", "than", "then", "now",
        "look", "only", "come", "its", "over", "think", "also",
        "back", "after", "use", "two", "how", "our", "work", "first",
        "well", "way", "even", "new", "want", "because", "any",
        "these", "give", "day", "most", "us", "is", "was", "are",
        "been", "has", "had", "were", "said", "did", "having", "may",
        "inc", "corp", "ltd", "llc", "co", "company", "stock", "share",
        "market", "trading", "price", "announces", "reports"
    }


def get_sentiment_label(sentiment: float) -> str:
    """Get sentiment label from value"""
    if sentiment > 0.5:
        return "Very Positive"
    elif sentiment > 0.2:
        return "Positive"
    elif sentiment < -0.5:
        return "Very Negative"
    elif sentiment < -0.2:
        return "Negative"
    else:
        return "Neutral"
