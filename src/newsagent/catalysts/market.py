"""Price confirmation — did the tape actually react to the catalyst?

A headline is a hypothesis; the tape is the evidence. This module fetches a
lightweight quote per ticker (last price, % change, volume vs. its 20-day
average) so `engine` can promote catalysts the market is already voting on and
demote ones it ignored.

Two free providers, no API key:
  * Yahoo `v8/finance/chart` — price, previous close, volume, 20-day volumes.
  * Nasdaq `api/quote/.../info` — fallback when Yahoo rate-limits (HTTP 429).

Every failure degrades to "no quote" rather than raising: price confirmation is
a bonus signal, never a dependency.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("newsagent.catalysts.market")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"
NASDAQ_INFO = "https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=stocks"

# Yahoo 429s quickly on long browser-like UAs; the short one is reliably served.
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
_NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json",
}

QUOTE_TTL_SECONDS = 90
MAX_WORKERS = 6
# Above this, a one-session move is more often a data artefact than news.
EXTREME_MOVE_PCT = 50.0
EXTREME_DISAGREEMENT_PCT = 15.0
REQUEST_TIMEOUT = 8.0
# Volume that makes a name genuinely news-sensitive rather than a mega-cap.
THIN_DOLLAR_VOLUME = 50_000_000
MICRO_DOLLAR_VOLUME = 5_000_000


@dataclass
class Quote:
    symbol: str
    price: float = 0.0
    prev_close: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    avg_volume: int = 0
    provider: str = ""
    fetched_at: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.price > 0

    @property
    def rel_volume(self) -> float:
        """Today's volume as a multiple of the 20-day average (0 if unknown)."""
        if self.avg_volume <= 0 or self.volume <= 0:
            return 0.0
        return round(self.volume / self.avg_volume, 2)

    @property
    def dollar_volume(self) -> float:
        return (self.avg_volume or self.volume) * self.price

    @property
    def size_bucket(self) -> str:
        dv = self.dollar_volume
        if dv <= 0:
            return "unknown"
        if dv < MICRO_DOLLAR_VOLUME:
            return "micro"
        if dv < THIN_DOLLAR_VOLUME:
            return "small"
        return "liquid"

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "price": self.price, "change_pct": self.change_pct,
            "volume": self.volume, "avg_volume": self.avg_volume,
            "rel_volume": self.rel_volume, "size_bucket": self.size_bucket,
            "provider": self.provider,
        }


def _pct(price: float, prev: float) -> float:
    if prev <= 0:
        return 0.0
    return round((price - prev) / prev * 100, 2)


def _previous_close(price: float, closes: list[float], meta: dict) -> float:
    """Yesterday's close from the daily series.

    `meta.chartPreviousClose` is the close *before the requested range* (a month
    ago here), not the prior session — using it reports a month's move as a day's.
    The last daily bar is the in-progress session whenever it matches the live
    price, so the prior session is the bar before it.
    """
    if not closes:
        return float(meta.get("previousClose") or 0)
    if len(closes) == 1:
        return closes[0]
    last = closes[-1]
    same_session = last > 0 and abs(price - last) / last < 0.005
    return closes[-2] if same_session else last


def _from_yahoo(symbol: str, client: httpx.Client) -> Quote | None:
    r = client.get(YAHOO_CHART.format(symbol=symbol), headers=_YAHOO_HEADERS)
    if r.status_code != 200:
        if r.status_code == 429:
            raise _RateLimited(symbol)
        return None
    result = (r.json().get("chart") or {}).get("result") or []
    if not result:
        return None
    meta = result[0].get("meta") or {}
    price = float(meta.get("regularMarketPrice") or 0)
    if price <= 0:
        return None
    quote_block = (result[0].get("indicators", {}).get("quote") or [{}])[0]
    closes = [c for c in (quote_block.get("close") or []) if c]
    prev = _previous_close(price, closes, meta)
    vols = [v for v in (quote_block.get("volume") or []) if v]
    avg = int(sum(vols[-20:]) / len(vols[-20:])) if vols else 0
    return Quote(
        symbol=symbol, price=price, prev_close=prev, change_pct=_pct(price, prev),
        volume=int(meta.get("regularMarketVolume") or 0), avg_volume=avg,
        provider="yahoo",
    )


def _from_nasdaq(symbol: str, client: httpx.Client) -> Quote | None:
    r = client.get(NASDAQ_INFO.format(symbol=symbol), headers=_NASDAQ_HEADERS)
    if r.status_code != 200:
        return None
    data = (r.json() or {}).get("data") or {}
    primary = data.get("primaryData") or {}
    try:
        price = float(str(primary.get("lastSalePrice", "")).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    try:
        change_pct = float(str(primary.get("percentageChange", "0")).replace("%", "").replace("+", ""))
    except (TypeError, ValueError):
        change_pct = 0.0
    try:
        volume = int(str(primary.get("volume", "0")).replace(",", ""))
    except (TypeError, ValueError):
        volume = 0
    return Quote(
        symbol=symbol, price=price,
        prev_close=round(price / (1 + change_pct / 100), 4) if change_pct != -100 else 0.0,
        change_pct=change_pct, volume=volume, provider="nasdaq",
    )


class _RateLimited(Exception):
    pass


class QuoteService:
    """Process-wide quote cache with TTL, provider failover and 429 backoff."""

    def __init__(self, ttl: float = QUOTE_TTL_SECONDS):
        self.ttl = ttl
        self._cache: dict[str, Quote] = {}
        self._lock = threading.Lock()
        self._yahoo_blocked_until = 0.0

    def cached(self, symbol: str) -> Quote | None:
        with self._lock:
            q = self._cache.get(symbol.upper())
        if q and (time.time() - q.fetched_at) < self.ttl:
            return q
        return None

    def get(self, symbol: str, client: httpx.Client | None = None) -> Quote | None:
        symbol = symbol.upper()
        if (hit := self.cached(symbol)) is not None:
            return hit
        owns = client is None
        client = client or httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)
        try:
            quote = None
            if time.time() >= self._yahoo_blocked_until:
                try:
                    quote = _from_yahoo(symbol, client)
                except _RateLimited:
                    self._yahoo_blocked_until = time.time() + 300
                    logger.info("yahoo rate-limited; falling back to nasdaq for 5m")
                except Exception as exc:
                    logger.debug("yahoo quote failed for %s: %s", symbol, exc)
            if quote is None:
                try:
                    quote = _from_nasdaq(symbol, client)
                except Exception as exc:
                    logger.debug("nasdaq quote failed for %s: %s", symbol, exc)
            elif abs(quote.change_pct) >= EXTREME_MOVE_PCT:
                quote = self._verify_extreme(quote, client)
            if quote is not None:
                with self._lock:
                    self._cache[symbol] = quote
            return quote
        finally:
            if owns:
                client.close()

    def _verify_extreme(self, quote: Quote, client: httpx.Client) -> Quote:
        """Second-source an implausible move before publishing it.

        Yahoo's daily bars are not always adjusted for a same-week reverse split
        or share exchange, which reads as a -90% session. A genuine collapse and
        a stale split factor look identical in one series, so an extreme move is
        confirmed against the other provider and its figure wins on disagreement.
        """
        try:
            second = _from_nasdaq(quote.symbol, client)
        except Exception as exc:
            logger.debug("extreme-move check failed for %s: %s", quote.symbol, exc)
            return quote
        if second is None or not second.ok:
            return quote
        if abs(second.change_pct - quote.change_pct) < EXTREME_DISAGREEMENT_PCT:
            return quote  # both agree it really moved that much
        logger.info(
            "%s: %.1f%% from yahoo looks like a corporate action; using nasdaq %.1f%%",
            quote.symbol, quote.change_pct, second.change_pct,
        )
        # Keep Yahoo's volume history, which Nasdaq does not provide.
        second.avg_volume = quote.avg_volume or second.avg_volume
        second.provider = "nasdaq(verified)"
        return second

    def get_many(self, symbols: list[str], max_symbols: int = 40, workers: int = MAX_WORKERS) -> dict[str, Quote]:
        """Fetch uncached symbols in a small thread pool.

        Capped at `max_symbols` per call so a burst of headlines can't turn into
        hundreds of requests; uncached extras simply come back without a quote.
        Concurrency is deliberately low — both providers throttle hard, and a
        429 costs more than the parallelism saves.
        """
        wanted = list(dict.fromkeys(s.upper() for s in symbols if s))
        out: dict[str, Quote] = {}
        pending: list[str] = []
        for s in wanted:
            hit = self.cached(s)
            if hit is not None:
                out[s] = hit
            else:
                pending.append(s)
        pending = pending[:max_symbols]
        if not pending:
            return out
        with (
            httpx.Client(
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=workers, max_keepalive_connections=workers),
            ) as client,
            ThreadPoolExecutor(max_workers=min(workers, len(pending))) as pool,
        ):
            futures = {pool.submit(self.get, s, client): s for s in pending}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    q = future.result()
                except Exception as exc:
                    logger.debug("quote failed for %s: %s", symbol, exc)
                    continue
                if q is not None:
                    out[symbol] = q
        return out


quotes = QuoteService()
