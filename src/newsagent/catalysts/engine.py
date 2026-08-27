"""The catalyst engine — headlines in, ranked tradeable events out.

Pipeline:

    articles ─▶ detect types ─▶ resolve ticker ─▶ cluster into events
             ─▶ attach quote ─▶ score 0-100 ─▶ rank

Clustering is what turns a news *feed* into a catalyst *board*: six outlets
rewriting one FDA approval collapse into a single event with six sources, and
the corroboration itself becomes evidence the event is real.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import detect as D
from .market import Quote, QuoteService
from .market import quotes as default_quotes
from .types import SPECS, CatalystGroup, Direction
from .types import CatalystType as CT
from .universe import TickerUniverse, load_universe

logger = logging.getLogger("newsagent.catalysts.engine")

# ── Source authority ─────────────────────────────────────────────────
# Primary sources are the filing/press-release wire itself; everything else is
# someone retelling it, and Google News is often a retelling of a retelling.
PRIMARY_SOURCES = {
    "sec", "edgar", "fda", "globenewswire", "globe newswire", "pr newswire",
    "prnewswire", "business wire", "businesswire", "accesswire", "nasdaq trading halts",
}
TIER1_SOURCES = {"reuters", "cnbc", "marketwatch", "bloomberg", "wall street journal", "wsj", "barron", "financial times"}
AGGREGATOR_SOURCES = {"yahoo", "seeking alpha", "seekingalpha", "benzinga", "investing.com", "nasdaq", "zacks", "thestreet"}


def source_weight(source: str) -> float:
    s = (source or "").lower()
    if any(k in s for k in PRIMARY_SOURCES):
        return 1.0
    if "google news" in s or "news.google" in s:
        return 0.78
    if any(k in s for k in TIER1_SOURCES):
        return 0.95
    if any(k in s for k in AGGREGATOR_SOURCES):
        return 0.86
    return 0.82


# Rules that fire together where the broader one is redundant.
SUPPRESSED_BY: dict[CT, set[CT]] = {
    CT.STOCK_SPLIT: {CT.REVERSE_SPLIT},
    CT.ACQUIRER: {CT.BUYOUT_TARGET},
    CT.SEC_FILING_8K: set(SPECS) - {CT.SEC_FILING_8K},
    CT.EARNINGS_SCHEDULED: {CT.EARNINGS_BEAT, CT.EARNINGS_MISS, CT.GUIDANCE_RAISE, CT.GUIDANCE_CUT},
    CT.SHELF_ATM: {CT.OFFERING},
    CT.PRODUCT_LAUNCH: {CT.FDA_APPROVAL, CT.CONTRACT_WIN},
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "by", "from", "as", "is", "are", "was", "were", "be", "its", "it", "after",
    "over", "into", "new", "says", "said", "amid", "stock", "shares", "inc",
    "corp", "company", "update", "report", "reports",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _fingerprint(text: str) -> frozenset[str]:
    return frozenset(t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ── Data model ───────────────────────────────────────────────────────

@dataclass
class CatalystSource:
    source: str
    title: str
    url: str
    published: datetime
    article_id: str = ""

    def as_dict(self) -> dict:
        return {
            "source": self.source, "title": self.title, "url": self.url,
            "published": _aware(self.published).isoformat(), "article_id": self.article_id,
        }


@dataclass
class Catalyst:
    id: str
    ticker: str
    company: str
    type: CT
    direction: Direction
    headline: str
    url: str
    published: datetime          # earliest report — when the event hit the tape
    latest: datetime             # most recent retelling
    sources: list[CatalystSource] = field(default_factory=list)
    secondary_types: list[CT] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    detect_confidence: float = 0.0
    ticker_confidence: float = 0.0
    score: float = 0.0
    score_parts: dict[str, float] = field(default_factory=dict)
    quote: Quote | None = None

    @property
    def group(self) -> CatalystGroup:
        return SPECS[self.type].group

    @property
    def label(self) -> str:
        return SPECS[self.type].label

    @property
    def color(self) -> str:
        return SPECS[self.type].color

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def confirmed(self) -> bool:
        """The tape agrees: a real move, in the direction the catalyst implies."""
        q = self.quote
        if q is None or not q.ok or abs(q.change_pct) < 2.0:
            return False
        if self.direction is Direction.BULLISH:
            return q.change_pct >= 2.0
        if self.direction is Direction.BEARISH:
            return q.change_pct <= -2.0
        return True

    def as_dict(self) -> dict:
        return {
            "id": self.id, "ticker": self.ticker, "company": self.company,
            "type": self.type.value, "label": self.label, "group": self.group.value,
            "direction": self.direction.value, "color": self.color,
            "headline": self.headline, "url": self.url,
            "published": _aware(self.published).isoformat(),
            "latest": _aware(self.latest).isoformat(),
            "score": self.score, "score_parts": self.score_parts,
            "detect_confidence": self.detect_confidence,
            "ticker_confidence": self.ticker_confidence,
            "secondary_types": [t.value for t in self.secondary_types],
            "facts": self.facts, "source_count": self.source_count,
            "sources": [s.as_dict() for s in self.sources],
            "quote": self.quote.as_dict() if self.quote and self.quote.ok else None,
            "confirmed": self.confirmed,
        }


# ── Article adapter ──────────────────────────────────────────────────

@dataclass
class _Classified:
    type: CT
    secondary: list[CT]
    confidence: float
    ticker: str
    ticker_confidence: float
    facts: dict[str, str] = field(default_factory=dict)
    headline: str = ""  # replaces the raw feed title when it is machine syntax


@dataclass
class _Item:
    id: str
    title: str
    summary: str
    source: str
    url: str
    published: datetime
    ticker_hint: str = ""


def _adapt(article: Any) -> _Item | None:
    get = article.get if isinstance(article, dict) else lambda k, d=None: getattr(article, k, d)
    title = (get("title") or "").strip()
    if not title:
        return None
    published = get("published") or datetime.now(timezone.utc)
    if isinstance(published, str):
        try:
            published = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            published = datetime.now(timezone.utc)
    return _Item(
        id=str(get("id") or hashlib.sha1(title.encode()).hexdigest()[:16]),
        title=title,
        summary=(get("summary") or "")[:600],
        source=get("source") or "",
        url=get("url") or "",
        published=_aware(published),
        ticker_hint=(get("ticker_hint") or "").upper(),
    )


# ── Scoring ──────────────────────────────────────────────────────────

def recency_factor(published: datetime, now: datetime | None = None) -> float:
    age_h = (( now or datetime.now(timezone.utc)) - _aware(published)).total_seconds() / 3600
    if age_h < 0.5:
        return 1.0
    if age_h < 2:
        return 0.96
    if age_h < 6:
        return 0.88
    if age_h < 24:
        return 0.74
    if age_h < 48:
        return 0.55
    return 0.38


def ticker_factor(ticker: str, confidence: float, ctype: CT) -> float:
    if not ticker:
        # A macro print has no issuer; everything else loses its edge without one.
        return 1.0 if ctype is CT.MACRO else 0.55
    if confidence >= 0.9:
        return 1.0
    if confidence >= 0.75:
        return 0.95
    if confidence >= 0.5:
        return 0.86
    return 0.76


def price_factor(quote: Quote | None, direction: Direction) -> float:
    if quote is None or not quote.ok:
        return 1.0
    move = abs(quote.change_pct)
    if move >= 15:
        f = 1.28
    elif move >= 8:
        f = 1.18
    elif move >= 4:
        f = 1.10
    elif move >= 2:
        f = 1.04
    else:
        f = 0.96
    rvol = quote.rel_volume
    if rvol >= 3:
        f *= 1.10
    elif rvol >= 1.5:
        f *= 1.05
    # The tape disagreeing with the headline is a real warning sign.
    if direction is Direction.BULLISH and quote.change_pct <= -3 or direction is Direction.BEARISH and quote.change_pct >= 3:
        f *= 0.85
    return min(f, 1.4)


def size_factor(quote: Quote | None) -> float:
    if quote is None or not quote.ok:
        return 1.0
    return {"micro": 1.15, "small": 1.08}.get(quote.size_bucket, 1.0)


def corroboration_factor(n_sources: int) -> float:
    return min(1.0 + 0.05 * max(0, n_sources - 1), 1.2)


def score_catalyst(c: Catalyst, now: datetime | None = None) -> float:
    base = SPECS[c.type].impact
    parts = {
        "base": float(base),
        "detection": round(c.detect_confidence, 3),
        "ticker": round(ticker_factor(c.ticker, c.ticker_confidence, c.type), 3),
        "source": round(max(source_weight(s.source) for s in c.sources) if c.sources else 0.82, 3),
        "recency": round(recency_factor(c.published, now), 3),
        "corroboration": round(corroboration_factor(c.source_count), 3),
        "size": round(size_factor(c.quote), 3),
        "price": round(price_factor(c.quote, c.direction), 3),
    }
    score = base
    for key, value in parts.items():
        if key != "base":
            score *= value
    c.score_parts = parts
    c.score = round(min(max(score, 0.0), 100.0), 1)
    return c.score


# ── Engine ───────────────────────────────────────────────────────────

CLUSTER_WINDOW = timedelta(hours=24)
CLUSTER_SIMILARITY = 0.42


class CatalystEngine:
    def __init__(
        self,
        data_dir: Path,
        universe: TickerUniverse | None = None,
        quote_service: QuoteService | None = None,
        extra_names: dict[str, str] | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.universe = universe or load_universe(self.data_dir, extra_names=extra_names)
        self.quotes = quote_service or default_quotes

    # ── step 1: per-article detection ────────────────────────────────

    def _classify(self, item: _Item) -> _Classified | None:
        kind = D.source_kind(item.source)
        if kind:
            return self._classify_structured(item, kind)
        if D.is_digest(item.title):
            return None  # a roundup would pin every event on its first ticker
        detections = D.detect(item.title, item.summary, item.source)
        if not detections:
            return None
        # Highest-impact type wins the primary slot, weighted by how sure we are.
        ranked = sorted(detections, key=lambda d: -(SPECS[d.type].impact * d.confidence))
        primary = ranked[0]
        suppressed = SUPPRESSED_BY.get(primary.type, set())
        present = {d.type for d in detections}
        for candidate in ranked:
            if candidate.type in suppressed:
                continue
            blockers = SUPPRESSED_BY.get(candidate.type, set())
            if present & blockers and candidate.type is not primary.type:
                continue
            primary = candidate
            break
        secondary = [d.type for d in ranked if d.type is not primary.type][:3]

        ticker, tconf = self._resolve_ticker(item, primary.type)
        if not ticker and primary.type is not CT.MACRO and primary.confidence < 0.85:
            return None  # an unattributed weak signal is noise, not a catalyst
        return _Classified(primary.type, secondary, primary.confidence, ticker, tconf)

    def _classify_structured(self, item: _Item, kind: str) -> _Classified | None:
        """Filing and halt feeds carry machine-readable structure — use it.

        An 8-K Item code or a halt reason code states the event outright, so
        these bypass the prose rules entirely and resolve their issuer from the
        filer name rather than by scanning the headline for capital letters.
        """
        if kind == "halt":
            halt = D.parse_halt(item.title, item.summary)
            if not halt:
                return None
            symbol = halt["symbol"]
            if not self.universe.is_valid(symbol):
                return None
            return _Classified(
                CT.TRADING_HALT, [], 0.95, symbol, 1.0,
                facts={"halt_reason": halt["reason"], "halt_code": halt["reason_code"]},
            )

        parsed = D.parse_sec_title(item.title)
        if not parsed:
            return None
        form, company = parsed
        if D.is_non_operating_filer(company):
            return None  # ETFs and partnerships file constantly and move nothing
        symbol = self.universe.primary(company, min_confidence=0.75) or ""
        if not symbol:
            return None

        if kind == "424b5" or form.startswith("424"):
            return _Classified(
                CT.OFFERING, [CT.SHELF_ATM], 0.9, symbol, 0.9,
                facts={"filing": form, "company": company},
                headline=f"{company} — shelf takedown priced ({form})",
            )

        items = D.detect_8k_items(item.summary)
        if not items:
            return None
        ranked = sorted(items, key=lambda d: -SPECS[d.type].impact)
        codes = [d.evidence.replace("Item ", "") for d in ranked]
        return _Classified(
            ranked[0].type,
            [d.type for d in ranked[1:3]],
            ranked[0].confidence,
            symbol, 0.9,
            facts={"filing": form, "items": ", ".join(f"Item {c}" for c in D.item_codes(item.summary))},
            headline=D.filing_headline(company, form, codes),
        )

    def _resolve_ticker(self, item: _Item, ctype: CT) -> tuple[str, float]:
        """Which company is this news *about*?

        For rating actions the headline names two companies — the sell-side firm
        and the company it rated — so the firm is stripped out first, and its own
        ticker is refused outright.
        """
        analyst_action = SPECS[ctype].group is CatalystGroup.ANALYST
        title = D.strip_analyst_firms(item.title) if analyst_action else item.title
        summary = D.strip_analyst_firms(item.summary) if analyst_action else item.summary
        # Bare uppercase words are trusted in a headline but not in body text,
        # where acronyms and units vastly outnumber real ticker mentions.
        for text, allow_bare in ((title, True), (f"{title} {summary}", False)):
            for match in self.universe.extract(text, allow_bare=allow_bare):
                if analyst_action and match.symbol in D.FIRM_TICKERS:
                    continue
                return match.symbol, match.confidence
        # Nothing named in the text — fall back to the page we pulled it from,
        # at reduced confidence since per-ticker pages carry peer stories too.
        if item.ticker_hint and self.universe.is_valid(item.ticker_hint):
            return item.ticker_hint, 0.6
        return "", 0.0

    # ── step 2: cluster same-event articles ──────────────────────────

    def _cluster(self, classified: list[tuple[_Item, _Classified]]) -> list[Catalyst]:
        buckets: dict[tuple[str, str], list[list[tuple[_Item, _Classified]]]] = {}
        for item, meta in sorted(classified, key=lambda x: x[0].published):
            key = (meta.ticker or "_MACRO", meta.type.value)
            groups = buckets.setdefault(key, [])
            fp = _fingerprint(item.title)
            placed = False
            for group in groups:
                seed_item, _ = group[0]
                if item.published - seed_item.published > CLUSTER_WINDOW:
                    continue
                if _jaccard(fp, _fingerprint(seed_item.title)) >= CLUSTER_SIMILARITY:
                    group.append((item, meta))
                    placed = True
                    break
            if not placed:
                groups.append([(item, meta)])

        out: list[Catalyst] = []
        for (ticker, _), groups in buckets.items():
            for group in groups:
                out.append(self._build(ticker if ticker != "_MACRO" else "", group))
        return out

    def _build(self, ticker: str, group: list[tuple[_Item, _Classified]]) -> Catalyst:
        # Prefer the most authoritative report as the display headline; keep the
        # earliest timestamp, because that is when the event actually hit.
        best_item, best_meta = max(
            group, key=lambda g: (source_weight(g[0].source), g[1].confidence, -g[0].published.timestamp())
        )
        ctype = best_meta.type
        display_headline = best_meta.headline or best_item.title
        published = min(i.published for i, _ in group)
        latest = max(i.published for i, _ in group)
        facts: dict[str, str] = {}
        for item, meta in group:
            for k, v in meta.facts.items():
                facts.setdefault(k, v)
            for k, v in D.extract_facts(f"{item.title} {item.summary}").items():
                facts.setdefault(k, v)
        seed_tokens = [t for t in _TOKEN_RE.findall(best_item.title.lower()) if t not in _STOPWORDS][:6]
        raw_id = f"{ticker}|{ctype.value}|{published:%Y-%m-%d}|{'-'.join(seed_tokens)}"
        sources = [
            CatalystSource(i.source, i.title, i.url, i.published, i.id)
            for i, _ in sorted(group, key=lambda g: g[0].published)
        ]
        secondary_all: list[CT] = []
        for _, meta in group:
            for t in [meta.type, *meta.secondary]:
                if t is not ctype and t not in secondary_all:
                    secondary_all.append(t)
        return Catalyst(
            id=hashlib.sha1(raw_id.encode()).hexdigest()[:16],
            ticker=ticker,
            company=self.universe.name_for(ticker) if ticker else "",
            type=ctype,
            direction=SPECS[ctype].direction,
            headline=display_headline,
            url=best_item.url,
            published=published,
            latest=latest,
            sources=sources,
            secondary_types=secondary_all[:3],
            facts=facts,
            detect_confidence=round(max(m.confidence for _, m in group), 3),
            ticker_confidence=round(max(m.ticker_confidence for _, m in group), 3),
        )

    # ── public API ───────────────────────────────────────────────────

    def analyze(self, articles: Iterable[Any], now: datetime | None = None) -> list[Catalyst]:
        """Detect, cluster and score. Pure CPU — no network calls."""
        classified: list[tuple[_Item, _Classified]] = []
        for raw in articles:
            item = _adapt(raw)
            if item is None:
                continue
            meta = self._classify(item)
            if meta is not None:
                classified.append((item, meta))
        catalysts = self._cluster(classified)
        for c in catalysts:
            score_catalyst(c, now)
        catalysts.sort(key=lambda c: -c.score)
        return catalysts

    QUOTE_SCORE_FLOOR = 30.0

    def attach_quotes(
        self, catalysts: Sequence[Catalyst], max_symbols: int = 40, min_score: float | None = None
    ) -> None:
        """Fetch quotes for the highest-scoring tickers and rescore in place.

        Catalysts arrive sorted by score, so this walks the top of the board and
        stops — confirming a rating change nobody will trade is not worth a
        request.
        """
        floor = self.QUOTE_SCORE_FLOOR if min_score is None else min_score
        symbols: list[str] = []
        for c in catalysts:
            if c.score < floor:
                break
            if c.ticker and c.ticker not in symbols:
                symbols.append(c.ticker)
            if len(symbols) >= max_symbols:
                break
        if not symbols:
            return
        quote_map = self.quotes.get_many(symbols, max_symbols=max_symbols)
        for c in catalysts:
            q = quote_map.get(c.ticker)
            if q is not None:
                c.quote = q
                score_catalyst(c)
        catalysts_sorted = sorted(catalysts, key=lambda c: -c.score)
        if isinstance(catalysts, list):
            catalysts[:] = catalysts_sorted

    def run(self, articles: Iterable[Any], with_quotes: bool = True, max_symbols: int = 40) -> list[Catalyst]:
        catalysts = self.analyze(articles)
        if with_quotes:
            self.attach_quotes(catalysts, max_symbols=max_symbols)
        return catalysts
