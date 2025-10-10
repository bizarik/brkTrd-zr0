"""Database models for brākTrād"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, func
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
import uuid

Base = declarative_base()


class MarketSession(str, Enum):
    """Market session types"""
    PRE = "pre"
    REGULAR = "regular"
    AFTER = "after"
    CLOSED = "closed"


class TimeHorizon(str, Enum):
    """Trading time horizons"""
    UNDER_1M = "<1m"
    MIN_1_5 = "1-5m"
    MIN_5_30 = "5-30m"
    SAME_DAY = "same_day"
    OVERNIGHT = "overnight"
    DAYS_1_3 = "1-3d"


class SentimentValue(int, Enum):
    """Sentiment values"""
    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1


class Headline(Base):
    """News headline model"""
    __tablename__ = "headlines"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Core fields
    ticker = Column(String(10), nullable=False, index=True)
    company = Column(String(255), nullable=False)
    headline = Column(Text, nullable=False)
    normalized_headline = Column(Text, nullable=False, index=True)
    
    # Source information
    source = Column(String(255), nullable=False)
    link = Column(Text, nullable=False)
    is_primary_source = Column(Boolean, default=False)
    
    # Timestamps
    headline_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    first_seen_timestamp = Column(DateTime(timezone=True), nullable=False, default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    # Market context
    market_session = Column(String(20), nullable=False)
    headline_age_minutes = Column(Integer)
    
    # Company metadata
    sector = Column(String(100), index=True)
    industry = Column(String(100), index=True)
    
    # Deduplication
    headline_hash = Column(String(64), unique=True, nullable=False)
    is_duplicate = Column(Boolean, default=False)
    parent_headline_id = Column(UUID(as_uuid=True), ForeignKey("headlines.id"), nullable=True)
    
    # Portfolio tracking
    portfolio_id = Column(Integer, index=True)
    
    # Relationships
    sentiments = relationship("SentimentAnalysis", back_populates="headline", cascade="all, delete-orphan")
    market_data = relationship("MarketData", back_populates="headline", cascade="all, delete-orphan")
    parent = relationship("Headline", remote_side=[id], backref="duplicates")
    
    __table_args__ = (
        Index("idx_headline_ticker_timestamp", "ticker", "headline_timestamp"),
        Index("idx_headline_sector_industry", "sector", "industry"),
        Index("idx_headline_portfolio_timestamp", "portfolio_id", "headline_timestamp"),
    )


class SentimentAnalysis(Base):
    """Individual model sentiment analysis"""
    __tablename__ = "sentiment_analyses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    headline_id = Column(UUID(as_uuid=True), ForeignKey("headlines.id"), nullable=False)
    
    # Model information
    model_provider = Column(String(50), nullable=False)  # groq or openrouter
    model_name = Column(String(100), nullable=False)
    
    # Analysis results
    sentiment = Column(Integer, nullable=False)  # -1, 0, 1
    confidence = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False)
    horizon = Column(String(20), nullable=False)
    
    # Metadata
    response_time_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    # Relationships
    headline = relationship("Headline", back_populates="sentiments")
    
    __table_args__ = (
        UniqueConstraint("headline_id", "model_provider", "model_name", name="uq_headline_model"),
        Index("idx_sentiment_headline", "headline_id"),
        Index("idx_sentiment_model", "model_provider", "model_name"),
        CheckConstraint("sentiment IN (-1, 0, 1)", name="check_sentiment_value"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="check_confidence_range"),
    )


class SentimentAggregate(Base):
    """Aggregated sentiment for headlines"""
    __tablename__ = "sentiment_aggregates"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    headline_id = Column(UUID(as_uuid=True), ForeignKey("headlines.id"), unique=True, nullable=False)
    
    # Aggregated metrics
    avg_sentiment = Column(Float, nullable=False)  # -1 to 1
    avg_confidence = Column(Float, nullable=False)  # 0 to 1
    dispersion = Column(Float, nullable=False)  # Standard deviation
    majority_vote = Column(Integer, nullable=False)  # -1, 0, 1
    
    # Model participation
    num_models = Column(Integer, nullable=False)
    model_votes = Column(JSONB, nullable=False)  # Array of {model, sentiment, confidence}
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index("idx_aggregate_sentiment", "avg_sentiment"),
        Index("idx_aggregate_confidence", "avg_confidence"),
        CheckConstraint("avg_sentiment >= -1 AND avg_sentiment <= 1", name="check_avg_sentiment_range"),
        CheckConstraint("avg_confidence >= 0 AND avg_confidence <= 1", name="check_avg_confidence_range"),
        CheckConstraint("majority_vote IN (-1, 0, 1)", name="check_majority_vote_value"),
    )


class MarketData(Base):
    """Intraday market data for tickers"""
    __tablename__ = "market_data"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    headline_id = Column(UUID(as_uuid=True), ForeignKey("headlines.id"), nullable=True)
    
    # Ticker information
    ticker = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Price data
    price = Column(Float, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    
    # Volume data
    volume = Column(Integer)
    volume_rel = Column(Float)  # Relative to average
    
    # Returns
    return_5m = Column(Float)
    return_30m = Column(Float)
    return_1d = Column(Float)
    
    # Volatility
    volatility_5m = Column(Float)
    volatility_30m = Column(Float)
    volatility_1d = Column(Float)
    
    # Technical indicators
    rsi = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    
    # Relationships
    headline = relationship("Headline", back_populates="market_data")
    
    __table_args__ = (
        Index("idx_market_ticker_timestamp", "ticker", "timestamp"),
        UniqueConstraint("ticker", "timestamp", name="uq_ticker_timestamp"),
    )


class PortfolioHolding(Base):
    """Snapshot of portfolio holdings and fundamentals from Finviz screener export"""
    __tablename__ = "portfolio_holdings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Portfolio and identity
    portfolio_id = Column(Integer, nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    company = Column(String(255), nullable=False)

    # Descriptive
    sector = Column(String(100), index=True)
    industry = Column(String(100), index=True)
    exchange = Column(String(50), index=True)

    # Fundamentals / snapshot
    pe = Column(Float)
    beta = Column(Float)
    volume = Column(Integer)
    price = Column(Float)
    change = Column(Float)  # percentage change

    # Timestamps
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("portfolio_id", "ticker", name="uq_portfolio_ticker"),
    )


class TradingOpportunity(Base):
    """Identified trading opportunities"""
    __tablename__ = "trading_opportunities"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Core information
    ticker = Column(String(10), nullable=False, index=True)
    opportunity_type = Column(String(20), nullable=False)  # long, short, options
    
    # Scoring
    score = Column(Float, nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    priority = Column(Integer, nullable=False, index=True)
    
    # Timing
    horizon = Column(String(20), nullable=False)
    time_sensitivity = Column(String(50))
    expiry_time = Column(DateTime(timezone=True))
    
    # Entry/Exit
    entry_price = Column(Float)
    target_price = Column(Float)
    stop_loss = Column(Float)
    position_size = Column(Float)
    
    # Risk metrics
    risk_reward_ratio = Column(Float)
    max_risk_amount = Column(Float)
    volatility_adjusted_size = Column(Float)
    
    # Supporting data
    supporting_headlines = Column(ARRAY(UUID(as_uuid=True)))
    sentiment_summary = Column(JSONB)
    market_context = Column(JSONB)
    
    # Status
    status = Column(String(20), default="active")  # active, executed, expired, cancelled
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index("idx_opportunity_score_priority", "score", "priority"),
        Index("idx_opportunity_status_ticker", "status", "ticker"),
    )


class Analytics(Base):
    """Pre-computed analytics and aggregations"""
    __tablename__ = "analytics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Grouping dimensions
    time_bucket = Column(String(20), nullable=False)  # day, week, month
    bucket_date = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Optional groupings
    ticker = Column(String(10), index=True)
    company = Column(String(255))
    sector = Column(String(100), index=True)
    industry = Column(String(100), index=True)
    source = Column(String(255), index=True)
    model_provider = Column(String(50), index=True)
    model_name = Column(String(100), index=True)
    
    # Metrics
    headline_count = Column(Integer, default=0)
    avg_sentiment = Column(Float)
    avg_confidence = Column(Float)
    sentiment_dispersion = Column(Float)
    
    # Sentiment breakdown
    positive_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    
    # Performance metrics
    avg_response_time_ms = Column(Float)
    cache_hit_rate = Column(Float)
    
    # Metadata
    computed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    __table_args__ = (
        Index("idx_analytics_bucket", "time_bucket", "bucket_date"),
        Index("idx_analytics_ticker_bucket", "ticker", "time_bucket", "bucket_date"),
        Index("idx_analytics_sector_bucket", "sector", "time_bucket", "bucket_date"),
        UniqueConstraint(
            "time_bucket", "bucket_date", "ticker", "company", "sector", 
            "industry", "source", "model_provider", "model_name",
            name="uq_analytics_dimensions"
        ),
    )


class UserSettings(Base):
    """User configuration and preferences"""
    __tablename__ = "user_settings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(100), unique=True, nullable=False)
    
    # API Keys (encrypted in production)
    finviz_api_key = Column(Text)
    groq_api_key = Column(Text)
    openrouter_api_key = Column(Text)
    
    # Portfolio configuration
    finviz_portfolio_numbers = Column(ARRAY(Integer), default=[])
    
    # Model selection
    selected_models = Column(ARRAY(String), default=[])
    
    # Preferences
    theme = Column(String(20), default="dark")
    notification_preferences = Column(JSONB, default={})
    dashboard_layout = Column(JSONB, default={})
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    last_key_rotation = Column(DateTime(timezone=True))


# Temporarily disabled until migration is run
class SentimentReturns(Base):
    """Historical returns linked to sentiment analysis"""
    __tablename__ = "sentiment_returns"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    headline_id = Column(UUID(as_uuid=True), ForeignKey("headlines.id"), nullable=False)
    
    # Sentiment information
    sentiment_value = Column(Integer, nullable=False)  # -1, 0, 1
    sentiment_confidence = Column(Float, nullable=False)  # 0 to 1
    
    # Returns over different timeframes
    return_3h = Column(Float)  # 3 hours or end of trading day
    return_24h = Column(Float)  # 24 hours (trading days only)
    return_next_day = Column(Float)  # End of next trading day
    return_2d = Column(Float)  # End of 2 trading days
    return_3d = Column(Float)  # End of 3 trading days
    return_prev_1d = Column(Float)  # Previous trading day
    return_prev_2d = Column(Float)  # Two trading days prior
    
    # Price data points
    price_at_sentiment = Column(Float, nullable=False)  # Price when sentiment was recorded
    price_3h = Column(Float)  # Price at 3h mark
    price_24h = Column(Float)  # Price at 24h mark
    price_next_day = Column(Float)  # Price at next day close
    price_2d = Column(Float)  # Price at 2d mark
    price_3d = Column(Float)  # Price at 3d mark
    price_prev_1d = Column(Float)  # Previous day's price
    price_prev_2d = Column(Float)  # Two days prior price
    
    # Timestamps for each price point
    timestamp_at_sentiment = Column(DateTime(timezone=True), nullable=False)
    timestamp_3h = Column(DateTime(timezone=True))
    timestamp_24h = Column(DateTime(timezone=True))
    timestamp_next_day = Column(DateTime(timezone=True))
    timestamp_2d = Column(DateTime(timezone=True))
    timestamp_3d = Column(DateTime(timezone=True))
    timestamp_prev_1d = Column(DateTime(timezone=True))
    timestamp_prev_2d = Column(DateTime(timezone=True))
    
    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    
    # Relationships
    headline = relationship("Headline", backref="sentiment_returns")
    
    __table_args__ = (
        Index("idx_sentiment_returns_headline", "headline_id"),
        Index("idx_sentiment_returns_sentiment", "sentiment_value", "sentiment_confidence"),
        CheckConstraint("sentiment_value IN (-1, 0, 1)", name="check_sentiment_returns_value"),
        CheckConstraint("sentiment_confidence >= 0 AND sentiment_confidence <= 1", name="check_sentiment_returns_confidence"),
    )


class SystemLog(Base):
    """System event and error logging"""
    __tablename__ = "system_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Log information
    level = Column(String(20), nullable=False, index=True)  # debug, info, warning, error, critical
    category = Column(String(50), nullable=False, index=True)  # fetch, sentiment, analytics, etc
    message = Column(Text, nullable=False)
    
    # Context
    context = Column(JSONB)
    error_details = Column(JSONB)
    
    # Tracking
    request_id = Column(String(100), index=True)
    user_id = Column(String(100), index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)
    
    __table_args__ = (
        Index("idx_log_level_category", "level", "category"),
        Index("idx_log_created", "created_at"),
    )
