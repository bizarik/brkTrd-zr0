"""Finviz Elite API client for fetching headlines and market data"""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog
from bs4 import BeautifulSoup
import csv
from io import StringIO
import pandas as pd
from fuzzywuzzy import fuzz
import json

from config import settings
from models import MarketSession

logger = structlog.get_logger()


class FinvizClient:
    """Client for Finviz Elite API"""
    
    BASE_URL = "https://elite.finviz.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Finviz client"""
        self.api_key = api_key or settings.finviz_api_key
        if not self.api_key:
            raise ValueError("Finviz API key not provided")
        
        self.session = None
        self.rate_limiter = RateLimiter(
            rate_limit=settings.finviz_rate_limit,
            window=settings.finviz_rate_window
        )
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = httpx.AsyncClient(
            headers=self.HEADERS,
            timeout=30.0,
            follow_redirects=True
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.aclose()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))
    )
    async def fetch_portfolio_headlines(self, portfolio_id: int) -> List[Dict[str, Any]]:
        """Fetch headlines for a specific portfolio using Finviz Elite news export.

        Primary path: GET https://elite.finviz.com/news_export.ashx?pid={portfolio_id}&auth={api_key}
        Fallback: scrape portfolio news table when export is unavailable.
        """
        await self.rate_limiter.acquire()
        
        try:
            # Preferred: Export endpoint (non-CORS server-side)
            export_url = f"{self.BASE_URL}/news_export.ashx"
            export_params = {"pid": portfolio_id, "auth": self.api_key}
            export_resp = await self.session.get(export_url, params=export_params)
            logger.info(
                "finviz_export_response",
                portfolio_id=portfolio_id,
                status=export_resp.status_code,
                content_type=export_resp.headers.get("content-type")
            )
            export_resp.raise_for_status()

            headlines = self._parse_news_export(export_resp.text, portfolio_id)

            # If export returned empty, try fallback scrape
            if not headlines:
                logger.warning("finviz_export_empty", portfolio_id=portfolio_id)
                headlines = await self._fallback_fetch_scrape(portfolio_id)

            logger.info(
                "fetched_portfolio_headlines",
                portfolio_id=portfolio_id,
                count=len(headlines),
                source="export" if headlines else "fallback"
            )

            return headlines
            
        except Exception as e:
            logger.warning("export_fetch_error", portfolio_id=portfolio_id, error=str(e))
            # Fallback to scrape on any error
            try:
                headlines = await self._fallback_fetch_scrape(portfolio_id)
                return headlines
            except Exception as e2:
                logger.error(
                    "fetch_portfolio_headlines_error",
                    portfolio_id=portfolio_id,
                    error=str(e2)
                )
                raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))
    )
    async def fetch_screener_export(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Fetch screener export CSV for a list of tickers and map to holdings fields.

        Uses Finviz Elite export endpoint (server-side, non-CORS):
        https://elite.finviz.com/export.ashx?v=152&t=ABC,DEF&c=0,1,2,3,4,129,7,48,67,65,66&auth=API_KEY
        Returns list of dicts keyed by our internal schema.
        """
        await self.rate_limiter.acquire()

        if not tickers:
            return []

        # Normalize and limit tickers
        norm_tickers = []
        for t in tickers:
            if not t:
                continue
            try:
                tt = str(t).strip().upper()
                if len(tt) > 10:
                    tt = tt[:10]
                if tt not in norm_tickers:
                    norm_tickers.append(tt)
            except Exception:
                continue

        url = f"{self.BASE_URL}/export.ashx"
        params = {
            "v": "152",
            "t": ",".join(norm_tickers),
            # Columns: Ticker, Company, Sector, Industry, Exchange, P/E, Beta, Volume, Price, Change
            "c": "0,1,2,3,4,129,7,48,67,65,66",
            "auth": self.api_key,
        }

        response = await self.session.get(url, params=params)
        response.raise_for_status()

        text = (response.text or "").strip()
        if not text:
            return []

        # Parse CSV by header names for robustness
        items: List[Dict[str, Any]] = []
        try:
            f = StringIO(text)
            reader = csv.DictReader(f)
            for row in reader:
                mapped = self._map_screener_row(row)
                if mapped and mapped.get("ticker") in norm_tickers:
                    items.append(mapped)
        except Exception as e:
            logger.error("parse_screener_export_error", error=str(e))
            return []

        return items

    def _map_screener_row(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Map a screener CSV row to internal holding schema."""
        if not isinstance(row, dict):
            return None
        norm = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

        # Header names are case-insensitive; common Finviz headers:
        # ticker, company, sector, industry, exchange, p/e, beta, volume, price, change
        def get(*keys: str) -> Optional[str]:
            for k in keys:
                v = norm.get(k)
                if v not in (None, ""):
                    return v
            return None

        ticker = get("ticker", "symbol")
        company = get("company", "name") or ticker
        sector = get("sector")
        industry = get("industry")
        exchange = get("exchange")
        pe_raw = get("p/e", "pe")
        beta_raw = get("beta")
        volume_raw = get("volume")
        price_raw = get("price")
        change_raw = get("change", "perf w")  # fallback if needed

        def to_float(x):
            try:
                if x is None or x == "-":
                    return None
                s = str(x).replace(",", "").replace("%", "").strip()
                if s == "":
                    return None
                return float(s)
            except Exception:
                return None

        def to_int(x):
            try:
                if x is None or x == "-":
                    return None
                s = str(x).replace(",", "").strip()
                if s == "":
                    return None
                return int(float(s))
            except Exception:
                return None

        try:
            if ticker:
                ticker = str(ticker).strip().upper()
                if len(ticker) > 10:
                    ticker = ticker[:10]
        except Exception:
            pass

        return {
            "ticker": ticker,
            "company": company,
            "sector": sector,
            "industry": industry,
            "exchange": exchange,
            "pe": to_float(pe_raw),
            "beta": to_float(beta_raw),
            "volume": to_int(volume_raw),
            "price": to_float(price_raw),
            "change": to_float(change_raw),
        }

    async def _fallback_fetch_scrape(self, portfolio_id: int) -> List[Dict[str, Any]]:
        """Fallback HTML scrape from portfolio page when export is unavailable."""
        url = f"{self.BASE_URL}/portfolio.ashx"
        params = {"v": portfolio_id, "api_key": self.api_key, "news": "1"}
        response = await self.session.get(url, params=params)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        return self._parse_headlines(soup, portfolio_id)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))
    )
    async def fetch_portfolio_tickers(self, portfolio_id: int) -> List[str]:
        """Fetch list of tickers from Finviz portfolio page by scraping links.

        This avoids CORS and does not require a separate portfolio export.
        """
        await self.rate_limiter.acquire()

        url = f"{self.BASE_URL}/portfolio.ashx"
        params = {"v": portfolio_id, "api_key": self.api_key}
        response = await self.session.get(url, params=params)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        tickers: List[str] = []
        seen = set()

        try:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                # Common quote link pattern: /quote.ashx?t=XXX
                if "quote.ashx" in href and "t=" in href:
                    # Extract after t=
                    try:
                        import urllib.parse as _up
                        parsed = _up.urlparse(href)
                        qs = _up.parse_qs(parsed.query)
                        sym = None
                        for k in ("t", "ticker", "sym"):
                            if k in qs and qs[k]:
                                sym = qs[k][0]
                                break
                        if not sym and "?" not in href:
                            # fallback: split path
                            if "t=" in href:
                                sym = href.split("t=")[-1]
                        if sym:
                            s = sym.strip().upper()
                            if len(s) > 10:
                                s = s[:10]
                            if s and s not in seen:
                                seen.add(s)
                                tickers.append(s)
                    except Exception:
                        continue
        except Exception:
            pass

        logger.info("portfolio_tickers_scraped", portfolio_id=portfolio_id, count=len(tickers))
        return tickers
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))
    )
    async def fetch_ticker_data(self, ticker: str) -> Dict[str, Any]:
        """Fetch intraday market data for a ticker"""
        await self.rate_limiter.acquire()
        
        try:
            url = f"{self.BASE_URL}/quote.ashx"
            params = {
                "t": ticker,
                "api_key": self.api_key,
                "ta": "1"  # Include technical analysis
            }
            
            response = await self.session.get(url, params=params)
            response.raise_for_status()
            
            # Parse response
            data = self._parse_ticker_data(response.text, ticker)
            
            logger.info(
                "fetched_ticker_data",
                ticker=ticker,
                price=data.get("price")
            )
            
            return data
            
        except Exception as e:
            logger.error(
                "fetch_ticker_data_error",
                ticker=ticker,
                error=str(e)
            )
            raise
    
    def _parse_headlines(self, soup: BeautifulSoup, portfolio_id: int) -> List[Dict[str, Any]]:
        """Parse headlines from HTML"""
        headlines = []
        
        # Find news table
        news_table = soup.find("table", {"class": "news-table"})
        if not news_table:
            return headlines
        
        current_ticker = None
        
        for row in news_table.find_all("tr"):
            # Check for ticker row
            ticker_cell = row.find("td", {"class": "ticker"})
            if ticker_cell:
                current_ticker = ticker_cell.text.strip()
                continue
            
            if not current_ticker:
                continue
            
            # Parse headline row
            headline_data = self._parse_headline_row(row, current_ticker, portfolio_id)
            if headline_data:
                headlines.append(headline_data)
        
        return headlines

    def _parse_news_export(self, text: str, portfolio_id: int) -> List[Dict[str, Any]]:
        """Parse Finviz news export content (CSV or JSON) into headline dicts."""
        text = (text or "").strip()
        if not text:
            return []

        # Try JSON first
        try:
            data = json.loads(text)
            # Expect list of dicts; attempt to map fields
            items = []
            if isinstance(data, list):
                for row in data:
                    item = self._map_export_row(row, portfolio_id)
                    if item:
                        items.append(item)
            elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                for row in data["data"]:
                    item = self._map_export_row(row, portfolio_id)
                    if item:
                        items.append(item)
            if items:
                return items
        except Exception:
            pass

        # Fallback: CSV parsing
        try:
            f = StringIO(text)
            reader = csv.DictReader(f)
            items: List[Dict[str, Any]] = []
            for row in reader:
                item = self._map_export_row(row, portfolio_id)
                if item:
                    items.append(item)
            return items
        except Exception as e:
            logger.error("parse_news_export_error", error=str(e))
            return []

    def _map_export_row(self, row: Dict[str, Any], portfolio_id: int) -> Optional[Dict[str, Any]]:
        """Map an export row (JSON/CSV) to internal headline schema."""
        if not isinstance(row, dict):
            return None
        # Normalize keys
        norm = {str(k).strip().lower(): v for k, v in row.items()}

        ticker = norm.get("ticker") or norm.get("sym") or norm.get("symbol")
        if ticker:
            try:
                # Normalize: take first symbol if multiple, strip, uppercase, clamp to 10 chars
                t = str(ticker).strip().upper()
                # Split on commas/whitespace
                import re as _re
                parts = [p for p in _re.split(r"[\s,;|]+", t) if p]
                if parts:
                    t = parts[0]
                if len(t) > 10:
                    t = t[:10]
                ticker = t
            except Exception:
                pass
        headline = norm.get("headline") or norm.get("title") or norm.get("news") or norm.get("text")
        link = norm.get("url") or norm.get("link") or norm.get("href")
        source = norm.get("source") or norm.get("publisher") or "Unknown"
        company = norm.get("company") or norm.get("name") or ticker

        # Timestamp: could be a combined field or date+time
        ts = norm.get("timestamp") or norm.get("datetime") or norm.get("published_at")
        if not ts:
            date = norm.get("date") or norm.get("pubdate")
            time_s = norm.get("time") or norm.get("pubtime")
            if date and time_s:
                ts = f"{date} {time_s}"
            elif date:
                ts = date

        # Build timestamp
        timestamp = None
        if isinstance(ts, (int, float)):
            try:
                timestamp = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            except Exception:
                timestamp = None
        if not timestamp and isinstance(ts, str):
            # Try ISO format first
            try:
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                # If ISO timestamp has no timezone info, assume EST/EDT
                if timestamp.tzinfo is None:
                    from datetime import timezone as tz
                    month = timestamp.month
                    is_edt = month in [3, 4, 5, 6, 7, 8, 9, 10]  # March-October (DST period)
                    est_offset = -4 if is_edt else -5
                    est_tz = tz(timedelta(hours=est_offset))
                    timestamp = timestamp.replace(tzinfo=est_tz).astimezone(timezone.utc)
            except Exception:
                # Fallback to existing parser
                try:
                    timestamp = self._parse_timestamp(ts)
                except Exception:
                    timestamp = datetime.now(timezone.utc)
        if not timestamp:
            timestamp = datetime.now(timezone.utc)

        # Ensure timezone-aware (UTC) to avoid naive/aware arithmetic errors
        try:
            if timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except Exception:
            timestamp = datetime.now(timezone.utc)

        if not ticker or not headline:
            return None

        normalized = self._normalize_headline(headline)
        headline_hash = self._generate_hash(normalized)
        market_session = self._get_market_session(timestamp)
        age_minutes = int((datetime.now(timezone.utc) - timestamp).total_seconds() / 60)

        company_info = self._get_company_info(ticker)
        sector = company_info.get("sector")
        industry = company_info.get("industry")

        return {
            "ticker": ticker,
            "company": company or ticker,
            "headline": headline,
            "normalized_headline": normalized,
            "headline_hash": headline_hash,
            "source": source,
            "link": link if (isinstance(link, str) and link.startswith("http")) else (f"{self.BASE_URL}{link}" if link else ""),
            "headline_timestamp": timestamp,
            "market_session": market_session,
            "headline_age_minutes": age_minutes,
            "sector": sector,
            "industry": industry,
            "portfolio_id": portfolio_id,
            "is_primary_source": self._is_primary_source(source)
        }
    
    def _parse_headline_row(self, row, ticker: str, portfolio_id: int) -> Optional[Dict[str, Any]]:
        """Parse individual headline row"""
        try:
            # Find headline link
            link_elem = row.find("a", {"class": "news-link"})
            if not link_elem:
                return None
            
            headline = link_elem.text.strip()
            link = link_elem.get("href", "")
            
            # Parse timestamp
            time_elem = row.find("td", {"class": "news-time"})
            if not time_elem:
                return None
            
            timestamp = self._parse_timestamp(time_elem.text.strip())
            
            # Parse source
            source_elem = row.find("span", {"class": "news-source"})
            source = source_elem.text.strip() if source_elem else "Unknown"
            
            # Get company info
            company_info = self._get_company_info(ticker)
            
            # Normalize headline
            normalized = self._normalize_headline(headline)
            headline_hash = self._generate_hash(normalized)
            
            # Determine market session
            market_session = self._get_market_session(timestamp)
            
            # Calculate age
            age_minutes = int((datetime.now(timezone.utc) - timestamp).total_seconds() / 60)
            
            return {
                "ticker": ticker,
                "company": company_info.get("name", ticker),
                "headline": headline,
                "normalized_headline": normalized,
                "headline_hash": headline_hash,
                "source": source,
                "link": link if link.startswith("http") else f"{self.BASE_URL}{link}",
                "headline_timestamp": timestamp,
                "market_session": market_session,
                "headline_age_minutes": age_minutes,
                "sector": company_info.get("sector"),
                "industry": company_info.get("industry"),
                "portfolio_id": portfolio_id,
                "is_primary_source": self._is_primary_source(source)
            }
            
        except Exception as e:
            logger.error("parse_headline_row_error", error=str(e))
            return None
    
    def _parse_ticker_data(self, html: str, ticker: str) -> Dict[str, Any]:
        """Parse ticker market data from HTML"""
        soup = BeautifulSoup(html, "lxml")
        data = {"ticker": ticker}
        
        try:
            # Parse price data
            price_elem = soup.find("span", {"class": "quote-price"})
            if price_elem:
                data["price"] = float(price_elem.text.strip().replace(",", ""))
            
            # Parse volume
            volume_elem = soup.find("td", text="Volume").find_next_sibling("td")
            if volume_elem:
                volume_text = volume_elem.text.strip().replace(",", "")
                data["volume"] = int(float(volume_text))
            
            # Parse relative volume
            rel_vol_elem = soup.find("td", text="Rel Volume").find_next_sibling("td")
            if rel_vol_elem:
                data["volume_rel"] = float(rel_vol_elem.text.strip())
            
            # Parse returns
            change_elem = soup.find("span", {"class": "quote-change"})
            if change_elem:
                change_text = change_elem.text.strip().replace("%", "")
                data["return_1d"] = float(change_text)
            
            # Parse technical indicators
            rsi_elem = soup.find("td", text="RSI").find_next_sibling("td")
            if rsi_elem:
                data["rsi"] = float(rsi_elem.text.strip())
            
            # Parse volatility (ATR)
            atr_elem = soup.find("td", text="ATR").find_next_sibling("td")
            if atr_elem:
                data["volatility_1d"] = float(atr_elem.text.strip())
            
            data["timestamp"] = datetime.now(timezone.utc)
            
        except Exception as e:
            logger.error("parse_ticker_data_error", ticker=ticker, error=str(e))
        
        return data
    
    def _normalize_headline(self, headline: str) -> str:
        """Normalize headline for deduplication"""
        # Convert to lowercase
        normalized = headline.lower()
        
        # Remove punctuation except spaces
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        
        # Remove common boilerplate
        boilerplate = [
            "breaking", "alert", "update", "exclusive", "just in",
            "watch", "hot", "trending", "must read", "developing"
        ]
        for term in boilerplate:
            normalized = normalized.replace(term, "")
        
        # Collapse multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Trim
        normalized = normalized.strip()
        
        return normalized
    
    def _generate_hash(self, text: str) -> str:
        """Generate hash for deduplication"""
        return hashlib.sha256(text.encode()).hexdigest()
    
    def _parse_timestamp(self, time_str: str) -> datetime:
        """Parse timestamp from various formats"""
        now = datetime.now(timezone.utc)
        
        # Handle relative times like "5 minutes ago"
        if "ago" in time_str:
            match = re.search(r'(\d+)\s*(minute|hour|day)', time_str)
            if match:
                value = int(match.group(1))
                unit = match.group(2)
                
                if unit.startswith("minute"):
                    return now - timedelta(minutes=value)
                elif unit.startswith("hour"):
                    return now - timedelta(hours=value)
                elif unit.startswith("day"):
                    return now - timedelta(days=value)
        
        # Handle time only (today) - assume EST/EDT for market hours
        time_match = re.match(r'^\d{1,2}:\d{2}(AM|PM)?$', time_str, re.IGNORECASE)
        if time_match:
            # Parse time and combine with today's date
            try:
                # Try 12-hour format first
                if time_str[-2:].upper() in ['AM', 'PM']:
                    time = datetime.strptime(time_str, "%I:%M%p").time()
                else:
                    # Try 24-hour format
                    time = datetime.strptime(time_str, "%H:%M").time()
                
                # Assume EST/EDT for market times, then convert to UTC
                from datetime import timezone as tz
                # EST is UTC-5, EDT is UTC-4 (simplified: assume EDT during summer months)
                month = now.month
                is_edt = month in [3, 4, 5, 6, 7, 8, 9, 10]  # March-October (DST period)
                est_offset = -4 if is_edt else -5  # EDT is UTC-4, EST is UTC-5
                est_tz = tz(timedelta(hours=est_offset))
                est_datetime = datetime.combine(now.date(), time, tzinfo=est_tz)
                return est_datetime.astimezone(timezone.utc)
            except Exception as e:
                logger.debug("time_parse_error", time_str=time_str, error=str(e))
                pass
        
        # Handle full date/time - assume EST/EDT for market times
        try:
            parsed = datetime.strptime(time_str, "%b %d, %Y %I:%M%p")
            # Assume EST/EDT for market times, then convert to UTC
            from datetime import timezone as tz
            # EST is UTC-5, EDT is UTC-4 (simplified: assume EDT during summer months)
            month = parsed.month
            is_edt = month in [3, 4, 5, 6, 7, 8, 9, 10]  # March-October (DST period)
            est_offset = -4 if is_edt else -5  # EDT is UTC-4, EST is UTC-5
            est_tz = tz(timedelta(hours=est_offset))
            est_datetime = parsed.replace(tzinfo=est_tz)
            return est_datetime.astimezone(timezone.utc)
        except Exception as e:
            logger.debug("full_datetime_parse_error", time_str=time_str, error=str(e))
            pass
        
        # Default to now
        return now
    
    def _get_market_session(self, timestamp: datetime) -> str:
        """Determine market session based on timestamp"""
        # Convert to Eastern Time
        hour = timestamp.hour - 5  # Rough EST conversion
        
        if hour < 4:
            return MarketSession.CLOSED
        elif hour < 9.5:
            return MarketSession.PRE
        elif hour < 16:
            return MarketSession.REGULAR
        elif hour < 20:
            return MarketSession.AFTER
        else:
            return MarketSession.CLOSED
    
    def _get_company_info(self, ticker: str) -> Dict[str, str]:
        """Get company information (cached lookup)"""
        # This would normally query a database or API
        # For now, return placeholder
        return {
            "name": ticker,
            "sector": "Technology",
            "industry": "Software"
        }
    
    def _is_primary_source(self, source: str) -> bool:
        """Check if source is primary/official"""
        primary_sources = [
            "PR Newswire", "Business Wire", "Globe Newswire",
            "SEC", "Company Press Release", "Investor Relations"
        ]
        
        source_lower = source.lower()
        return any(ps.lower() in source_lower for ps in primary_sources)


class RateLimiter:
    """Simple rate limiter for API calls"""
    
    def __init__(self, rate_limit: int, window: int):
        """Initialize rate limiter"""
        self.rate_limit = rate_limit
        self.window = window  # seconds
        self.calls = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire permission to make a call"""
        async with self.lock:
            now = datetime.now()
            
            # Remove old calls outside window
            self.calls = [
                call for call in self.calls
                if (now - call).total_seconds() < self.window
            ]
            
            # Check if we're at limit
            if len(self.calls) >= self.rate_limit:
                # Wait until oldest call expires
                oldest = self.calls[0]
                wait_time = self.window - (now - oldest).total_seconds()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                # Retry
                return await self.acquire()
            
            # Record this call
            self.calls.append(now)


class HeadlineDeduplicator:
    """Deduplicate headlines using fuzzy matching"""
    
    def __init__(self, threshold: float = 0.85):
        """Initialize deduplicator"""
        self.threshold = threshold * 100  # fuzzywuzzy uses 0-100 scale
    
    def find_duplicates(self, headlines: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
        """Find duplicate headline pairs"""
        duplicates = []
        
        for i in range(len(headlines)):
            for j in range(i + 1, len(headlines)):
                # Compare normalized headlines
                similarity = fuzz.ratio(
                    headlines[i]["normalized_headline"],
                    headlines[j]["normalized_headline"]
                )
                
                if similarity >= self.threshold:
                    # Also check if same ticker
                    if headlines[i]["ticker"] == headlines[j]["ticker"]:
                        duplicates.append((i, j))
        
        return duplicates
    
    def deduplicate(self, headlines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate headlines, keeping earliest/primary source"""
        duplicates = self.find_duplicates(headlines)
        
        # Build groups of duplicates
        groups = {}
        for i, j in duplicates:
            if i not in groups:
                groups[i] = [i]
            groups[i].append(j)
        
        # Merge groups
        merged_groups = []
        seen = set()
        
        for primary, group in groups.items():
            if primary in seen:
                continue
            
            # Expand group to include all connected duplicates
            expanded = set(group)
            for idx in group:
                if idx in groups:
                    expanded.update(groups[idx])
            
            merged_groups.append(list(expanded))
            seen.update(expanded)
        
        # Add standalone headlines
        all_indices = set(range(len(headlines)))
        for idx in all_indices - seen:
            merged_groups.append([idx])
        
        # Select best from each group
        deduplicated = []
        
        for group in merged_groups:
            # Sort by: primary source first, then earliest
            group_headlines = [headlines[i] for i in group]
            group_headlines.sort(
                key=lambda h: (
                    not h["is_primary_source"],  # Primary sources first
                    h["headline_timestamp"]  # Earlier first
                )
            )
            
            # Keep the best one
            best = group_headlines[0]
            
            # Mark others as duplicates
            if len(group) > 1:
                best["has_duplicates"] = True
                best["duplicate_count"] = len(group) - 1
            
            deduplicated.append(best)
        
        return deduplicated
