"""Ticker universe — validates symbols against the real US listed universe.

The naive `\\b[A-Z]{1,5}\\b` + stop-word-list approach produces a lot of false
tickers ("CEO", "FDA", "Q3", "US"). This module loads SEC's authoritative
company_tickers.json (~10.4k listed issuers, free, no API key) and uses it two
ways:

  1. **Validation** — a bare uppercase token is only a ticker if SEC lists it.
  2. **Company-name resolution** — "Sarepta Therapeutics announced..." resolves
     to SRPT even when the headline never prints the symbol, which is the
     common case for press-wire catalysts.

Matches carry a confidence so downstream scoring can trust `(NASDAQ: ABCD)`
more than a bare capitalised word.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger("newsagent.catalysts.universe")

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC requires a descriptive UA with contact info on automated requests.
SEC_UA = "NewsAgent/1.0 (open-source market news aggregator; contact via repo)"
CACHE_TTL_SECONDS = 7 * 24 * 3600

# ── Name normalisation ────────────────────────────────────────────────

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "companies",
    "ltd", "limited", "plc", "llc", "lp", "llp", "sa", "nv", "ag", "ab", "as",
    "oyj", "asa", "se", "kgaa", "spa", "bv", "gmbh", "pte", "pty", "holdings",
    "holding", "group", "groups", "the", "adr", "ads", "cl", "class", "common",
    "stock", "shares", "share", "ordinary", "trust", "reit", "fund", "etf",
    "new", "de", "delaware", "usa", "us", "intl", "international", "worldwide",
}
_PUNCT_RE = re.compile(r"[^\w\s&]")
_WS_RE = re.compile(r"\s+")


def normalize_company(name: str) -> str:
    """Lowercase, strip punctuation and legal suffixes: 'Apple Inc.' -> 'apple'."""
    s = _PUNCT_RE.sub(" ", name.lower())
    s = _WS_RE.sub(" ", s).strip()
    toks = [t for t in s.split() if t]
    # Trim trailing legal noise; keep at least the first token.
    while len(toks) > 1 and toks[-1] in _LEGAL_SUFFIXES:
        toks.pop()
    while len(toks) > 1 and toks[0] in _LEGAL_SUFFIXES:
        toks.pop(0)
    return " ".join(toks)


# Single-word company names that are also ordinary English and would fire on
# almost every headline. These stay out of the name index entirely; they can
# still be matched via an explicit exchange parenthetical or a $cashtag.
AMBIGUOUS_NAMES = {
    # Calendar and market-wrap vocabulary — "Stock Market Today" is not TDAY.
    "today", "tomorrow", "yesterday", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "january", "february", "march",
    "april", "june", "july", "august", "september", "october", "november",
    "december", "market", "markets", "stocks", "news", "daily", "weekly",
    "wrap", "recap", "close", "morning", "evening", "midday", "premarket",
    "week", "month", "year", "live", "brief", "report", "update", "alert",
    "watch", "wall", "street", "index", "sector", "world", "america",
    "china", "japan", "europe", "britain", "canada", "mexico", "india",
    "earnings", "revenue", "profit", "loss", "sales", "outlook", "guidance",
    "target", "gap", "block", "match", "root", "open", "shift", "sound", "core",
    "global", "national", "american", "united", "general", "first", "capital",
    "value", "growth", "select", "premier", "summit", "sky", "peak", "eagle",
    "liberty", "freedom", "victory", "vision", "future", "power", "energy",
    "digital", "data", "cloud", "wave", "pulse", "spark", "bridge",
    "path", "point", "range", "signal", "sun", "star", "moon", "one", "two",
    "next", "prime", "pure", "real", "smart", "solid", "strong", "trust",
    "under", "up", "way", "well", "west", "east", "north", "south", "aim",
    "arc", "ark", "axis", "beam", "bell", "bill", "bond", "book", "boot",
    "call", "card", "care", "cash", "cell", "chip", "city", "coin", "corn",
    "cost", "dawn", "deal", "dime", "dish", "dock", "door", "down", "duke",
    "edge", "fair", "fast", "flow", "food", "fort", "gain", "gate", "gold",
    "good", "grid", "hall", "hand", "hard", "haul", "head", "help", "hero",
    "hill", "home", "hope", "host", "hour", "hunt", "iron", "join", "jump",
    "keep", "kind", "king", "lake", "land", "lead", "leaf", "life", "lift",
    "line", "link", "lion", "loan", "lock", "loop", "luck", "main",
    "make", "mark", "mass", "mesa", "mile", "mind", "mint", "mode", "more",
    "move", "name", "near", "neat", "nest", "nice", "node", "note", "nova",
    "oaks", "onto", "pace", "pack", "page", "palm", "park", "part", "pass",
    "past", "pave", "pear", "peer", "pick", "pine", "plan", "play", "plus",
    "pool", "port", "post", "pray", "prep", "pull", "push", "quad", "race",
    "rail", "rain", "rank", "rate", "read", "reef", "rest", "rice", "rich",
    "ride", "ring", "rise", "risk", "road", "rock", "role", "roll", "roof",
    "room", "rose", "rule", "rush", "safe", "sage", "sail", "salt", "same",
    "sand", "save", "seal", "seat", "seed", "self", "sell", "send", "ship",
    "shop", "show", "side", "sign", "site", "size", "slam", "snap", "snow",
    "soft", "soil", "sole", "song", "sort", "soul", "span", "spin", "spot",
    "stag", "stay", "stem", "step", "stop", "surf", "swap", "tail", "take",
    "talk", "tall", "tank", "task", "team", "tech", "tell", "tend", "term",
    "test", "text", "tide", "tile", "time", "tire", "tone", "tool", "torn",
    "tour", "town", "trac", "tree", "trek", "trip", "true", "tube", "tune",
    "turn", "twin", "unit", "vast", "vent", "verb", "very", "vest", "view",
    "vine", "vote", "wage", "wait", "wake", "walk", "want", "ward",
    "warm", "warn", "wash", "wear", "weed", "what",
    "when", "wide", "wild", "will", "wind", "wine", "wing", "wire", "wise",
    "wish", "wolf", "wood", "wool", "word", "work", "yard", "your",
    "zone", "zoom",
}

# Alias heads must not be ordinary English. The uniqueness filter already drops
# shared heads like "American" or "National", but a one-off issuer named
# "Investors Title" would otherwise claim every headline starting "Investors".
_COMMON_HEAD_WORDS = {
    "investor", "investors", "shareholder", "shareholders", "holder", "holders",
    "analyst", "analysts", "trader", "traders", "consumer", "consumers",
    "customer", "customers", "worker", "workers", "employee", "employees",
    "company", "companies", "business", "businesses", "industry", "industries",
    "economy", "economic", "financial", "finance", "banking", "insurance",
    "housing", "mortgage", "lending", "savings", "credit", "payment", "payments",
    "revenue", "revenues", "profit", "profits", "earning", "earnings", "income",
    "growth", "decline", "increase", "decrease", "average", "median", "total",
    "quarter", "quarterly", "annual", "monthly", "yearly", "morning", "evening",
    "outlook", "forecast", "guidance", "estimate", "estimates", "results",
    "report", "reports", "update", "updates", "preview", "review", "summary",
    "leader", "leaders", "leading", "premier", "advance", "advanced", "modern",
    "national", "international", "american", "european", "global", "regional",
    "central", "eastern", "western", "northern", "southern", "pacific",
    "atlantic", "mountain", "valley", "harbor", "harbour", "coastal",
    "heritage", "legacy", "liberty", "freedom", "victory", "pioneer",
    "frontier", "horizon", "sterling", "provident", "citizens", "farmers",
    "peoples", "merchants", "security", "guaranty", "mutual", "community",
    "general", "special", "standard", "quality", "premium", "select",
    "superior", "supreme", "ultimate", "perfect", "complete", "unified",
    "combined", "allied", "associated", "affiliated", "integrated",
    "diversified", "consolidated", "universal", "worldwide", "continental",
    "strategy", "strategic", "tactical", "capital", "equity", "venture",
    "partner", "partners", "holding", "holdings", "enterprise", "enterprises",
    "resource", "resources", "material", "materials", "product", "products",
    "service", "services", "solution", "solutions", "system", "systems",
    "network", "networks", "platform", "digital", "virtual", "dynamic",
    "innovate", "innovative", "creative", "positive", "greater", "better",
    "future", "modernize", "sustainable", "renewable", "recovery", "rebound",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "august", "september", "october",
    "november", "december", "weekend", "midweek", "tonight", "tomorrow",
    "yesterday", "recent", "current", "former", "latest", "biggest",
    "largest", "smallest", "highest", "lowest", "strongest", "weakest",
}

# Uppercase tokens that collide with real tickers but are almost never the
# ticker in a news headline.
HARD_STOP_SYMBOLS = {
    "A", "I", "AI", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF",
    "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "ALL", "AND", "ANY", "ARE", "BIG", "BUT", "BUY", "CAN", "CEO",
    "CFO", "COO", "CTO", "CUT", "DAY", "DID", "EPS", "ETF", "FED", "FDA", "FOR",
    "GDP", "GET", "GOT", "HAD", "HAS", "HOW", "ILS", "INC", "IPO", "IRS", "ITS",
    "JOB", "LAW", "LOW", "MAY", "NEW", "NOT", "NOW", "OFF", "OIL", "OLD", "ONE",
    "OUR", "OUT", "OWN", "PAY", "PER", "PUT", "RAY", "RUN", "SAY", "SEC", "SEE",
    "SET", "SHE", "TAX", "THE", "TOO", "TOP", "TRY", "TWO", "USA", "USD", "WAR",
    "WAS", "WAY", "WHO", "WHY", "WIN", "YES", "YET", "YOU", "AGO", "APP", "ASK",
    "BAD", "BAN", "BAR", "BET", "BID", "BIT", "BOX", "CAR", "CUP", "DEAL",
    "EACH", "EAST", "EDIT", "ELSE", "EVEN", "EVER", "FALL", "FROM", "FULL",
    "HAVE", "HERE", "HIGH", "INTO", "JUST", "LAST", "LESS", "LIKE", "LONG",
    "LOOK", "MADE", "MAKE", "MANY", "MORE", "MOST", "MUCH", "MUST", "ONLY",
    "OPEN", "OVER", "SAID", "SAME", "SOME", "SUCH", "THAN", "THAT", "THEM",
    "THEN", "THEY", "THIS", "TIME", "VERY", "WELL", "WERE", "WHAT", "WHEN",
    "WILL", "WITH", "YEAR", "YOUR", "NYSE", "AMEX", "OTC", "SPAC", "GAAP",
    "ESG", "CPI", "PPI", "FOMC", "ECB", "BOJ", "IMF", "DOJ", "FTC",
    "USDA", "NATO", "OPEC", "NASA", "PDUFA", "CRL", "IND", "NDA", "BLA",
    "PHASE", "QUARTER", "STOCK", "NEWS", "WATCH", "ALERT", "UPDATE",
}

# Explicit exchange parenthetical, e.g. "(NASDAQ: SRPT)" or "(NYSE American:XY)".
EXCHANGE_RE = re.compile(
    r"\((?:NASDAQ|NYSE(?:\s+American|\s+Arca)?|AMEX|NYSEAMERICAN|OTCQB|OTCQX|OTC(?:\s*Markets)?|CBOE|BATS)"
    r"\s*[:\-]\s*([A-Z]{1,5})(?:\.[A-Z])?\)",
    re.IGNORECASE,
)
CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
BARE_RE = re.compile(r"\b([A-Z]{1,5})\b")

# Context words that make a nearby bare uppercase token far more likely a ticker.
_TICKER_CONTEXT_RE = re.compile(
    r"(?i)\b(shares?|stock|ticker|symbol|equity|holders?|investors?|traded?|trading)\b"
)

# A one-word company name is only believable as the headline's subject when it
# reads like a proper noun in subject position — otherwise "moving today"
# resolves to TDAY. Multi-word names need no such guard.
_SUBJECT_VERBS = {
    "announces", "announced", "announce", "reports", "reported", "report",
    "says", "said", "posts", "posted", "receives", "received", "wins", "won",
    "prices", "priced", "launches", "launched", "files", "filed", "completes",
    "completed", "appoints", "appointed", "names", "named", "unveils",
    "unveiled", "raises", "raised", "cuts", "cut", "beats", "beat", "misses",
    "missed", "acquires", "acquired", "to", "will", "and", "shares", "stock",
    "jumps", "jumped", "surges", "surged", "plunges", "plunged", "falls",
    "fell", "soars", "soared", "sinks", "sank", "rallies", "slides", "slid",
    "gains", "gained", "drops", "dropped", "climbs", "tumbles", "spikes",
    "secures", "signs", "signed", "enters", "expands", "initiates", "begins",
    "ceo", "cfo", "inc", "corp", "stocks", "earnings", "guidance", "q1", "q2",
    "q3", "q4",
}
_SUBJECT_WINDOW = 4  # a one-word name this far into the headline is still the subject
# Lowercase words that legitimately sit inside a capitalised company name.
# "s" appears because stripping punctuation turns "Wendy's" into "wendy s".
_NAME_CONNECTORS = {"and", "of", "the", "de", "la", "von", "van", "del", "for", "at", "on", "in", "s"}
# "raises price target on Apple" — the company is the prepositional object.
_OBJECT_PREPOSITIONS = {"on", "for", "of", "at", "in", "to", "by", "with", "from", "against", "into"}


# A bare symbol this far into the text is a headline-leading ticker.
_LEADING_SYMBOL_CHARS = 12
# Units and measurements that collide with real symbols: "150,000 BTU/Hr",
# "40 MW", "5 KM". A number before it or a slash after it gives them away.
_UNIT_BEFORE_RE = re.compile(r"[\d,.]\s*$")
_UNIT_AFTER_RE = re.compile(r"^\s*[/\-]")


def _looks_like_unit(text: str, start: int, end: int) -> bool:
    return bool(_UNIT_BEFORE_RE.search(text[:start]) or _UNIT_AFTER_RE.match(text[end:]))


@dataclass(frozen=True)
class TickerMatch:
    symbol: str
    confidence: float
    evidence: str  # "exchange" | "cashtag" | "name" | "symbol"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.symbol}({self.evidence}:{self.confidence:.2f})"


class TickerUniverse:
    """Loaded once per process; refreshed from SEC at most weekly."""

    def __init__(self, symbols: dict[str, str], extra_names: dict[str, str] | None = None):
        self.symbols = symbols  # SYMBOL -> company title
        self._name_index: dict[str, str] = {}
        self._max_name_tokens = 1
        alias_counts: dict[str, int] = {}
        alias_owner: dict[str, str] = {}
        for sym, title in symbols.items():
            norm = normalize_company(title)
            if not self._name_indexable(norm):
                continue
            # First writer wins so the SEC file's ordering (roughly by size /
            # familiarity) keeps the better-known issuer for colliding names.
            self._name_index.setdefault(norm, sym)
            self._max_name_tokens = max(self._max_name_tokens, len(norm.split()))
            head = norm.split()[0]
            if len(norm.split()) > 1 and self._alias_candidate(head):
                alias_counts[head] = alias_counts.get(head, 0) + 1
                alias_owner.setdefault(head, sym)
        # Headlines shorten "Sarepta Therapeutics" to "Sarepta". Only unambiguous
        # first words qualify — a head shared by two issuers identifies neither.
        self._alias_index = {
            head: sym for head, sym in alias_owner.items() if alias_counts[head] == 1
        }
        for name, sym in (extra_names or {}).items():
            norm = normalize_company(name)
            if norm:
                self._name_index[norm] = sym.upper()
                self._max_name_tokens = max(self._max_name_tokens, len(norm.split()))
        self._max_name_tokens = min(self._max_name_tokens, 6)

    @staticmethod
    def _alias_candidate(head: str) -> bool:
        return (
            len(head) >= 6
            and head.isalpha()
            and head not in AMBIGUOUS_NAMES
            and head not in _COMMON_HEAD_WORDS
        )

    @staticmethod
    def _name_indexable(norm: str) -> bool:
        if not norm:
            return False
        toks = norm.split()
        if len(toks) == 1:
            t = toks[0]
            return len(t) >= 4 and t not in AMBIGUOUS_NAMES and not t.isdigit()
        return True

    # ── Lookups ──────────────────────────────────────────────────────

    def is_valid(self, symbol: str) -> bool:
        return symbol.upper() in self.symbols

    def name_for(self, symbol: str) -> str:
        return self.symbols.get(symbol.upper(), "")

    def resolve_name(self, text: str) -> tuple[str, int] | None:
        """Longest n-gram company-name match in `text` as (symbol, n_tokens).

        Longest match wins, then leftmost. One-token matches must additionally
        look like a proper noun in subject position (see `_SUBJECT_VERBS`).
        """
        cleaned = _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip()
        toks_orig = cleaned.split()
        toks = [t.lower() for t in toks_orig]
        for n in range(min(self._max_name_tokens, len(toks)), 0, -1):
            for i in range(len(toks) - n + 1):
                hit = self._name_index.get(" ".join(toks[i:i + n]))
                if not hit:
                    continue
                if not self._is_proper_noun(toks_orig, i, n):
                    continue
                if n == 1 and not self._is_subject_position(toks_orig, toks, i):
                    continue
                return hit, n
        return self._resolve_alias(toks_orig, toks)

    def _resolve_alias(self, toks_orig: list[str], toks: list[str]) -> tuple[str, int] | None:
        for i, tok in enumerate(toks):
            sym = self._alias_index.get(tok)
            if sym and self._is_proper_noun(toks_orig, i, 1) and self._is_subject_position(toks_orig, toks, i):
                return sym, 1
        return None

    @staticmethod
    def _is_proper_noun(toks_orig: list[str], i: int, n: int) -> bool:
        """Every content word of the match must be capitalised in the source.

        Without this, "delivery growth and new restaurant brands" resolves to
        Restaurant Brands International. A real company mention is capitalised
        in both sentence case and title case; an incidental noun phrase is not.
        """
        for tok in toks_orig[i:i + n]:
            if tok.lower() in _NAME_CONNECTORS:
                continue
            if not tok[:1].isupper():
                return False
        return True

    @staticmethod
    def _is_subject_position(toks_orig: list[str], toks: list[str], i: int) -> bool:
        """Does this capitalised word sit where a company name sits?

        Three shapes cover almost every financial headline: the name leads
        ("Moderna announces..."), it precedes a reporting verb, or it is the
        object of a preposition ("raises price target on Apple"). A capitalised
        word anywhere else is far more likely ordinary prose.
        """
        if not toks_orig[i][:1].isupper():
            return False
        if i <= _SUBJECT_WINDOW:
            return True
        if i + 1 < len(toks) and toks[i + 1] in _SUBJECT_VERBS:
            return True
        if i + 1 < len(toks) and toks[i + 1] == "s":  # possessive, apostrophe stripped
            return True
        return i > 0 and toks[i - 1] in _OBJECT_PREPOSITIONS

    def extract(self, text: str, max_results: int = 6, allow_bare: bool = True) -> list[TickerMatch]:
        """All plausible tickers in `text`, best evidence first, deduplicated.

        `allow_bare=False` turns off matching of bare uppercase words, for text
        (like an article body) where a stray capitalised token is far more
        likely a unit or an acronym than the subject of the story.
        """
        found: dict[str, TickerMatch] = {}

        def add(sym: str, conf: float, evidence: str) -> None:
            sym = sym.upper()
            if sym in HARD_STOP_SYMBOLS or not self.is_valid(sym):
                return
            cur = found.get(sym)
            if cur is None or conf > cur.confidence:
                found[sym] = TickerMatch(sym, conf, evidence)

        for m in EXCHANGE_RE.finditer(text):
            add(m.group(1), 1.0, "exchange")
        for m in CASHTAG_RE.finditer(text):
            add(m.group(1), 0.95, "cashtag")

        name_hit = self.resolve_name(text)
        if name_hit:
            sym, n_tokens = name_hit
            add(sym, 0.90 if n_tokens > 1 else 0.80, "name")

        if allow_bare:
            has_context = bool(_TICKER_CONTEXT_RE.search(text))
            for m in BARE_RE.finditer(text):
                sym = m.group(1)
                if len(sym) < 2 or _looks_like_unit(text, m.start(), m.end()):
                    continue
                # A bare capital word is only a ticker when something says so:
                # nearby ticker vocabulary, or the headline-leading position
                # that "AEYE Q1 Earnings" uses. Otherwise "150,000 BTU/Hr"
                # becomes Peabody Energy.
                if has_context:
                    add(sym, 0.55, "symbol")
                elif m.start() <= _LEADING_SYMBOL_CHARS:
                    add(sym, 0.45, "symbol")

        ranked = sorted(found.values(), key=lambda t: (-t.confidence, t.symbol))
        return ranked[:max_results]

    def primary(self, text: str, min_confidence: float = 0.5, allow_bare: bool = True) -> str | None:
        """The single subject ticker of a headline, if we're confident enough."""
        for m in self.extract(text, allow_bare=allow_bare):
            if m.confidence >= min_confidence:
                return m.symbol
        return None


# ── Loading / caching ────────────────────────────────────────────────

_FALLBACK = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp", "NVDA": "NVIDIA CORP",
    "AMZN": "Amazon.com Inc", "GOOGL": "Alphabet Inc.", "META": "Meta Platforms Inc",
    "TSLA": "Tesla, Inc.", "AMD": "Advanced Micro Devices Inc", "NFLX": "NETFLIX INC",
    "JPM": "JPMORGAN CHASE & CO", "BAC": "BANK OF AMERICA CORP", "XOM": "Exxon Mobil Corp",
    "PFE": "PFIZER INC", "MRNA": "Moderna, Inc.", "LLY": "Eli Lilly & Co",
    "WMT": "Walmart Inc.", "TGT": "TARGET CORP", "COST": "COSTCO WHOLESALE CORP",
    "BA": "BOEING CO", "INTC": "INTEL CORP", "CRM": "Salesforce, Inc.",
    "ORCL": "ORACLE CORP", "UBER": "Uber Technologies, Inc", "COIN": "Coinbase Global, Inc.",
    "PLTR": "Palantir Technologies Inc.", "SOFI": "SoFi Technologies, Inc.",
}

_cached: TickerUniverse | None = None


def _cache_path(data_dir: Path) -> Path:
    return data_dir / "ticker_universe.json"


def _fetch_sec(timeout: float = 20.0) -> dict[str, str]:
    r = httpx.get(SEC_TICKERS_URL, headers={"User-Agent": SEC_UA}, timeout=timeout)
    r.raise_for_status()
    out: dict[str, str] = {}
    for row in r.json().values():
        sym = str(row.get("ticker", "")).upper().strip()
        if sym and sym.isalpha() and len(sym) <= 5:
            out[sym] = str(row.get("title", ""))
    if len(out) < 1000:
        raise ValueError(f"SEC ticker file looks truncated ({len(out)} rows)")
    return out


def load_universe(
    data_dir: Path,
    extra_names: dict[str, str] | None = None,
    force_refresh: bool = False,
) -> TickerUniverse:
    """Load (and memoise) the universe, refreshing the on-disk cache weekly.

    Never raises: a network failure falls back to the stale cache, then to a
    small built-in set, so ticker extraction degrades rather than breaking.
    """
    global _cached
    if _cached is not None and not force_refresh:
        return _cached

    data_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(data_dir)
    symbols: dict[str, str] = {}

    fresh = path.exists() and (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS
    if fresh and not force_refresh:
        try:
            symbols = json.loads(path.read_text())
        except Exception as exc:
            logger.warning("ticker cache unreadable: %s", exc)

    if not symbols:
        try:
            symbols = _fetch_sec()
            path.write_text(json.dumps(symbols))
            logger.info("loaded %d tickers from SEC", len(symbols))
        except Exception as exc:
            logger.warning("SEC ticker fetch failed (%s); using cache/fallback", exc)
            if path.exists():
                try:
                    symbols = json.loads(path.read_text())
                except Exception:
                    symbols = {}

    _cached = TickerUniverse(symbols or dict(_FALLBACK), extra_names)
    return _cached
