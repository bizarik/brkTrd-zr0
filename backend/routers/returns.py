"""API routes for historical returns and sentiment comparisons"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from io import StringIO
import csv
import structlog

from database import get_db
from models import Headline, SentimentReturns, SentimentAggregate, MarketData, PortfolioHolding
from services.market_data import calculate_returns

logger = structlog.get_logger()
router = APIRouter(prefix="/api/returns", tags=["returns"])


@router.get("/tickers")
async def get_available_tickers(
    db: AsyncSession = Depends(get_db)
):
    """Get list of available tickers from portfolio holdings and headlines"""
    # Get tickers from portfolio holdings
    holdings_result = await db.execute(
        select(PortfolioHolding.ticker, PortfolioHolding.company)
        .distinct()
        .order_by(PortfolioHolding.ticker)
    )
    holdings = holdings_result.all()
    
    # Also get tickers from headlines that have sentiment analysis
    headlines_result = await db.execute(
        select(Headline.ticker, Headline.company)
        .join(SentimentAggregate, SentimentAggregate.headline_id == Headline.id)
        .distinct()
        .order_by(Headline.ticker)
    )
    headlines = headlines_result.all()
    
    # Merge and deduplicate
    ticker_map = {}
    for ticker, company in holdings:
        if ticker:
            ticker_map[ticker] = company or ticker
    
    for ticker, company in headlines:
        if ticker and ticker not in ticker_map:
            ticker_map[ticker] = company or ticker
    
    tickers = [
        {"ticker": ticker, "company": company}
        for ticker, company in sorted(ticker_map.items())
    ]
    
    return {"tickers": tickers}


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


@router.post("/upload-quote-data")
async def upload_quote_data(
    file: UploadFile = File(...),
    ticker: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload Finviz quote export CSV for a ticker to populate market data.
    
    Expected CSV format from Finviz quote export (intraday data):
    Date,Open,High,Low,Close,Volume
    
    Note: Finviz has different date/time formats by period:
    
    5-minute periods (and other minute-based):
    - All times use 12-hour format with AM/PM: "10/6/2025 9:30 AM", "10/6/2025 1:00 PM"
    
    Hourly periods:
    - 4:00 AM - 12:59 PM: "10/6/2025 9:30" (single-digit day, no suffix)
    - 1:00 PM - 8:00 PM: "10/06/2025 13:00 PM" (double-digit day, PM suffix, military time)
    
    The data will be used for returns analysis calculations.
    """
    try:
        # Read and decode file
        content_bytes = await file.read()
        try:
            text = content_bytes.decode("utf-8")
        except Exception:
            text = content_bytes.decode("latin-1", errors="ignore")
        
        # Parse CSV
        f = StringIO(text)
        reader = csv.DictReader(f)
        
        ticker = ticker.upper().strip()
        if not ticker:
            raise HTTPException(status_code=400, detail="Ticker is required")
        
        rows_parsed = 0
        rows_stored = 0
        errors = []
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (1 for header)
            try:
                # Parse date/time - Finviz has different formats by period
                date_str = row.get("Date", "").strip()
                if not date_str:
                    continue
                
                # Finviz uses different formats:
                # 5-min periods: "10/6/2025 9:30 AM" or "10/6/2025 1:00 PM" (12-hour with AM/PM)
                # Hourly periods: "10/6/2025 9:30" or "10/06/2025 13:00 PM" (mixed format)
                
                timestamp = None
                
                # Try format 1: 12-hour format with AM/PM (used in 5-min periods)
                if " AM" in date_str or " PM" in date_str:
                    try:
                        # Format: "10/6/2025 9:30 AM" or "10/6/2025 1:00 PM"
                        timestamp = datetime.strptime(date_str, "%m/%d/%Y %I:%M %p")
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                
                # Try format 2: Hourly format (24-hour, PM suffix on afternoon only)
                if not timestamp:
                    try:
                        # Strip redundant " PM" if present (already in military time)
                        date_str_clean = date_str.replace(" PM", "").strip()
                        # Format: "10/6/2025 9:30" or "10/06/2025 13:00"
                        timestamp = datetime.strptime(date_str_clean, "%m/%d/%Y %H:%M")
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                
                if not timestamp:
                    errors.append(f"Row {row_num}: Invalid date/time format '{date_str}'")
                    continue
                
                # Parse price fields
                def parse_float(value, default=None):
                    if not value or value == "-" or value == "N/A":
                        return default
                    try:
                        # Remove commas and dollar signs
                        value = str(value).replace(",", "").replace("$", "").strip()
                        return float(value)
                    except (ValueError, AttributeError):
                        return default
                
                open_price = parse_float(row.get("Open"))
                high_price = parse_float(row.get("High"))
                low_price = parse_float(row.get("Low"))
                close_price = parse_float(row.get("Close"))
                volume = parse_float(row.get("Volume"))
                
                # Close price is required
                if close_price is None:
                    errors.append(f"Row {row_num}: Missing close price")
                    continue
                
                rows_parsed += 1
                
                # Check if market data already exists for this ticker and timestamp
                existing = await db.execute(
                    select(MarketData).where(
                        and_(
                            MarketData.ticker == ticker,
                            MarketData.timestamp == timestamp
                        )
                    )
                )
                existing_data = existing.scalar_one_or_none()
                
                if existing_data:
                    # Update existing record
                    existing_data.price = close_price
                    existing_data.open = open_price
                    existing_data.high = high_price
                    existing_data.low = low_price
                    existing_data.close = close_price
                    if volume is not None:
                        existing_data.volume = int(volume)
                else:
                    # Create new record
                    market_data = MarketData(
                        ticker=ticker,
                        timestamp=timestamp,
                        price=close_price,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=int(volume) if volume is not None else None
                    )
                    db.add(market_data)
                    rows_stored += 1
                
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")
                logger.warning("quote_data_row_error", row=row_num, error=str(e))
                continue
        
        # Commit all changes
        await db.commit()
        
        logger.info(
            "quote_data_uploaded",
            ticker=ticker,
            rows_parsed=rows_parsed,
            rows_stored=rows_stored,
            errors=len(errors)
        )
        
        response = {
            "status": "ok",
            "ticker": ticker,
            "rows_parsed": rows_parsed,
            "rows_stored": rows_stored,
            "rows_updated": rows_parsed - rows_stored,
            "message": f"Successfully processed {rows_parsed} rows for {ticker}"
        }
        
        if errors and len(errors) <= 10:  # Only include errors if not too many
            response["errors"] = errors
        elif errors:
            response["error_count"] = len(errors)
            response["first_errors"] = errors[:10]
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_quote_data_error", ticker=ticker, error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to process upload: {str(e)}")
