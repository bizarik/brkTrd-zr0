"""Portfolio holdings API router"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from models import PortfolioHolding, UserSettings
from services.finviz_client import FinvizClient
from config import settings
from database import get_db, AsyncSessionLocal

logger = structlog.get_logger()
router = APIRouter()


@router.get("/holdings")
async def get_holdings(
    portfolio_id: Optional[int] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    db: AsyncSession = Depends(get_db)
):
    """Return holdings for a portfolio or all portfolios."""
    query = select(PortfolioHolding)
    if portfolio_id is not None:
        query = query.where(PortfolioHolding.portfolio_id == portfolio_id)

    query = query.order_by(PortfolioHolding.portfolio_id, PortfolioHolding.ticker).limit(limit)

    result = await db.execute(query)
    holdings = result.scalars().all()

    return {
        "holdings": [
            {
                "portfolio_id": h.portfolio_id,
                "ticker": h.ticker,
                "company": h.company,
                "sector": h.sector,
                "industry": h.industry,
                "exchange": h.exchange,
                "pe": h.pe,
                "beta": h.beta,
                "volume": h.volume,
                "price": h.price,
                "change": h.change,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
            }
            for h in holdings
        ],
        "total": len(holdings),
    }


@router.post("/refresh")
async def refresh_holdings(
    background_tasks: BackgroundTasks,
    portfolio_id: Optional[int] = Query(default=None),
    sync: bool = Query(default=False),
    db: AsyncSession = Depends(get_db)
):
    """Refresh portfolio holdings for the given portfolio by fetching Finviz screener export."""
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
        result = await refresh_holdings_task(pid, db, api_key, return_result=True)
        return {"status": "completed", "portfolio_id": pid, **(result or {})}
    else:
        background_tasks.add_task(refresh_holdings_task, pid, db, api_key)
        return {
            "status": "refreshing",
            "portfolio_id": pid,
            "message": "Holdings refresh initiated",
        }


async def refresh_holdings_task(
    portfolio_id: int, db: Optional[AsyncSession], api_key: str, return_result: bool = False
):
    """Task to refresh holdings: derive tickers from portfolio headlines, fetch screener export, upsert holdings."""
    # Ensure we have a usable DB session
    external_session = db is not None
    if not external_session:
        db = AsyncSessionLocal()
    try:
        async with FinvizClient(api_key=api_key) as client:
            # Preferred: scrape portfolio page to get full tickers list
            uniq_tickers: List[str] = []
            try:
                uniq_tickers = await client.fetch_portfolio_tickers(portfolio_id)
            except Exception as e:
                logger.warning("refresh_holdings_tickers_error", portfolio_id=portfolio_id, error=str(e))
                uniq_tickers = []

            # Fallback: derive from headlines if tickers list empty
            if not uniq_tickers:
                try:
                    headlines = await client.fetch_portfolio_headlines(portfolio_id)
                    seen = set()
                    for h in headlines:
                        t = (h.get("ticker") or "").strip().upper()
                        if t and t not in seen:
                            seen.add(t)
                            uniq_tickers.append(t)
                except Exception as e:
                    logger.warning("refresh_holdings_headlines_error", portfolio_id=portfolio_id, error=str(e))

            if not uniq_tickers:
                logger.warning("refresh_holdings_no_tickers", portfolio_id=portfolio_id)
                if return_result:
                    return {"fetched": 0, "stored": 0}
                return None

            # Fetch screener export for these tickers
            items = await client.fetch_screener_export(uniq_tickers)
            logger.info("screener_items_fetched", portfolio_id=portfolio_id, count=len(items))

            # Upsert holdings
            stored = 0
            for item in items:
                if not item.get("ticker"):
                    continue
                # Check if exists
                result = await db.execute(
                    select(PortfolioHolding).where(
                        (PortfolioHolding.portfolio_id == portfolio_id)
                        & (PortfolioHolding.ticker == item["ticker"])
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.company = item.get("company") or existing.company
                    existing.sector = item.get("sector")
                    existing.industry = item.get("industry")
                    existing.exchange = item.get("exchange")
                    existing.pe = item.get("pe")
                    existing.beta = item.get("beta")
                    existing.volume = item.get("volume")
                    existing.price = item.get("price")
                    existing.change = item.get("change")
                else:
                    db.add(
                        PortfolioHolding(
                            portfolio_id=portfolio_id,
                            ticker=item.get("ticker"),
                            company=item.get("company") or item.get("ticker"),
                            sector=item.get("sector"),
                            industry=item.get("industry"),
                            exchange=item.get("exchange"),
                            pe=item.get("pe"),
                            beta=item.get("beta"),
                            volume=item.get("volume"),
                            price=item.get("price"),
                            change=item.get("change"),
                        )
                    )
                    stored += 1

            await db.commit()
            logger.info("holdings_upserted", portfolio_id=portfolio_id, inserted=stored, total=len(items))
            if return_result:
                return {"fetched": len(items), "stored": stored}

    except Exception as e:
        logger.error("refresh_holdings_task_error", portfolio_id=portfolio_id, error=str(e), exc_info=True)
        if return_result:
            return {"error": str(e), "fetched": 0, "stored": 0}
    finally:
        if not external_session and db is not None:
            await db.close()


@router.post("/upload")
async def upload_holdings(
    file: UploadFile = File(...),
    portfolio_id: int = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload Finviz screener export CSV and upsert portfolio holdings.

    Accepts the CSV as provided by elite.finviz.com/export.ashx (v=152 recommended).
    """
    try:
        content_bytes = await file.read()
        try:
            text = content_bytes.decode("utf-8")
        except Exception:
            text = content_bytes.decode("latin-1", errors="ignore")

        # Reuse FinvizClient mapping to ensure schema compatibility
        client = FinvizClient(api_key="upload")  # dummy key for helpers
        # Private map function expects dict rows; parse as CSV via pandas-like approach in client
        from io import StringIO
        import csv
        f = StringIO(text)
        reader = csv.DictReader(f)

        items = []
        for row in reader:
            mapped = client._map_screener_row(row)  # type: ignore[attr-defined]
            if mapped and mapped.get("ticker"):
                items.append(mapped)

        stored = 0
        for item in items:
            # Upsert per existing logic
            result = await db.execute(
                select(PortfolioHolding).where(
                    (PortfolioHolding.portfolio_id == portfolio_id)
                    & (PortfolioHolding.ticker == item["ticker"]) 
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.company = item.get("company") or existing.company
                existing.sector = item.get("sector")
                existing.industry = item.get("industry")
                existing.exchange = item.get("exchange")
                existing.pe = item.get("pe")
                existing.beta = item.get("beta")
                existing.volume = item.get("volume")
                existing.price = item.get("price")
                existing.change = item.get("change")
            else:
                db.add(
                    PortfolioHolding(
                        portfolio_id=portfolio_id,
                        ticker=item.get("ticker"),
                        company=item.get("company") or item.get("ticker"),
                        sector=item.get("sector"),
                        industry=item.get("industry"),
                        exchange=item.get("exchange"),
                        pe=item.get("pe"),
                        beta=item.get("beta"),
                        volume=item.get("volume"),
                        price=item.get("price"),
                        change=item.get("change"),
                    )
                )
                stored += 1

        await db.commit()
        logger.info("uploaded_holdings_upserted", portfolio_id=portfolio_id, uploaded=len(items), stored=stored)
        return {"status": "ok", "portfolio_id": portfolio_id, "uploaded": len(items), "stored": stored}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_holdings_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to process upload: {str(e)}")

