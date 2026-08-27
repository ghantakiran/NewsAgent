"""Grok (xAI) as a news source and as an explainer.

RSS can only carry what someone has already published. The fastest market news
breaks on X first — a halt, a leak, a filing someone spotted — and often reaches
a wire minutes later. Grok's server-side `x_search` and `web_search` tools read
that live, which makes it two things here:

  * **A source.** `fetch_squawk` asks for market-moving posts from the last few
    minutes and returns them as `NewsItem`s, so they flow through the same
    detection, clustering and scoring as every RSS item.
  * **An explainer.** `explain_move` answers "why is this moving?" for a ticker
    that jumped without any catalyst the engine could find — the gap RSS leaves.

Entirely optional: with no `XAI_API_KEY` every entry point returns empty and the
rest of the pipeline is unaffected.

API shape: POST https://api.x.ai/v1/responses with `tools: [{"type": "x_search"}]`.
Response parsing is deliberately tolerant — the field layout has moved before.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from .sources import NewsItem, source_for_url

logger = logging.getLogger("newsagent.catalysts.grok")

XAI_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = os.getenv("XAI_MODEL", "grok-4.6")
DEFAULT_TIMEOUT = float(os.getenv("XAI_TIMEOUT", "45"))
# Grok calls cost money and hit the network; a squawk sweep is rate-limited.
MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("XAI_MIN_INTERVAL", "60"))


def api_key() -> str:
    return os.getenv("XAI_API_KEY", "").strip()


def available() -> bool:
    """True when Grok is configured. Everything here no-ops when it isn't."""
    return bool(api_key())


@dataclass
class GrokAnswer:
    text: str = ""
    citations: list[str] = field(default_factory=list)
    model: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


# ── Response parsing ─────────────────────────────────────────────────

def _collect_text(payload: dict) -> str:
    """Pull the assistant's final text out of a /v1/responses payload.

    Tries the documented Responses shape first, then the chat-completions shape,
    so a schema change degrades to "no answer" instead of a traceback.
    """
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    if isinstance(direct, list) and direct:
        return "\n".join(str(x) for x in direct).strip()

    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") not in (None, "message"):
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
            continue
        for part in content or []:
            if isinstance(part, dict) and part.get("text"):
                chunks.append(str(part["text"]))
    if chunks:
        return "\n".join(chunks).strip()

    for choice in payload.get("choices") or []:
        message = (choice or {}).get("message") or {}
        if message.get("content"):
            return str(message["content"]).strip()
    return ""


_URL_RE = re.compile(r"https?://[^\s\)\]\"'<>]+")


def _collect_citations(payload: dict, text: str) -> list[str]:
    urls: list[str] = []

    def add(value) -> None:
        if isinstance(value, str) and value.startswith("http"):
            urls.append(value)
        elif isinstance(value, dict):
            for key in ("url", "link", "source_url", "uri"):
                if isinstance(value.get(key), str) and value[key].startswith("http"):
                    urls.append(value[key])
                    return

    for value in payload.get("citations") or []:
        add(value)
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for value in item.get("citations") or []:
            add(value)
        for part in item.get("content") or []:
            if isinstance(part, dict):
                for note in part.get("annotations") or []:
                    add(note)
        for result in item.get("results") or []:
            add(result)
    urls.extend(_URL_RE.findall(text or ""))
    return list(dict.fromkeys(urls))[:12]


# ── Client ───────────────────────────────────────────────────────────

class GrokClient:
    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = DEFAULT_TIMEOUT,
                 min_interval: float = MIN_SECONDS_BETWEEN_CALLS):
        self.model = model
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call = 0.0

    def available(self) -> bool:
        return available()

    def _throttled(self) -> bool:
        return (time.monotonic() - self._last_call) < self.min_interval

    def ask(
        self,
        prompt: str,
        use_x: bool = True,
        use_web: bool = True,
        since_minutes: int | None = None,
        allowed_handles: list[str] | None = None,
        respect_throttle: bool = True,
    ) -> GrokAnswer:
        key = api_key()
        if not key:
            return GrokAnswer(error="XAI_API_KEY not set")
        if respect_throttle and self._throttled():
            return GrokAnswer(error="throttled")

        tools: list[dict] = []
        if use_x:
            x_tool: dict = {"type": "x_search"}
            if since_minutes:
                start = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
                x_tool["from_date"] = start.date().isoformat()
            if allowed_handles:
                x_tool["allowed_x_handles"] = allowed_handles[:20]
            tools.append(x_tool)
        if use_web:
            tools.append({"type": "web_search"})

        body = {
            "model": self.model,
            "input": [{"role": "user", "content": prompt}],
        }
        if tools:
            body["tools"] = tools

        self._last_call = time.monotonic()
        try:
            resp = httpx.post(
                XAI_URL, json=body, timeout=self.timeout,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
        except Exception as exc:
            logger.warning("grok request failed: %s", exc)
            return GrokAnswer(error=f"request failed: {exc}")

        if resp.status_code != 200:
            detail = resp.text[:200]
            logger.warning("grok HTTP %s: %s", resp.status_code, detail)
            return GrokAnswer(error=f"HTTP {resp.status_code}: {detail}")

        try:
            payload = resp.json()
        except ValueError:
            return GrokAnswer(error="response was not JSON")

        text = _collect_text(payload)
        if not text:
            return GrokAnswer(error="no text in response", model=self.model)
        return GrokAnswer(text=text, citations=_collect_citations(payload, text), model=self.model)


_client: GrokClient | None = None


def client() -> GrokClient:
    global _client
    if _client is None:
        _client = GrokClient()
    return _client


# ── JSON coaxing ─────────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def parse_json_list(text: str) -> list[dict]:
    """Best-effort extraction of a JSON array from a model reply."""
    if not text:
        return []
    candidates = _JSON_BLOCK_RE.findall(text)
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    return []


# ── Squawk: Grok as a news source ────────────────────────────────────

SQUAWK_PROMPT = """You are a market squawk desk. Search X and the web for \
US-listed equity news published in the last {minutes} minutes.

Report ONLY discrete, market-moving corporate events: halts, FDA decisions, \
M&A, offerings and dilution, guidance changes, earnings surprises, activist \
stakes, index changes, executive departures, short-seller reports, bankruptcies, \
major contracts, and regulatory actions.

Exclude: opinion, price-target chatter, technical analysis, "stocks to watch" \
lists, macro commentary, and anything without a specific US-listed company.

Return ONLY a JSON array, newest first, at most {limit} objects:
[{{"ticker":"ABCD","headline":"one factual sentence, no hype",\
"minutes_ago":5,"url":"https://source-link"}}]

Use the real exchange ticker. If you cannot identify one, omit the object. \
If nothing qualifies, return []."""


def fetch_squawk(minutes: int = 30, limit: int = 15, respect_throttle: bool = True) -> list[NewsItem]:
    """Breaking corporate events from X and the web as NewsItems.

    Returned items join the normal pipeline, so Grok's findings are detected,
    clustered and scored exactly like an RSS headline — including being merged
    with the wire story when it lands a few minutes later.
    """
    if not available():
        return []
    answer = client().ask(
        SQUAWK_PROMPT.format(minutes=minutes, limit=limit),
        use_x=True, use_web=True, since_minutes=minutes,
        respect_throttle=respect_throttle,
    )
    if not answer.ok:
        if answer.error not in ("throttled", "XAI_API_KEY not set"):
            logger.info("grok squawk unavailable: %s", answer.error)
        return []

    now = datetime.now(timezone.utc)
    items: list[NewsItem] = []
    for row in parse_json_list(answer.text)[:limit]:
        headline = str(row.get("headline") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        if not headline or not ticker.isalpha() or len(ticker) > 5:
            continue
        try:
            age = max(0, min(int(row.get("minutes_ago") or 0), minutes))
        except (TypeError, ValueError):
            age = 0
        url = str(row.get("url") or "").strip()
        # Grok is credited as the discovering source; the underlying publisher
        # is kept in the summary so the link still points at the original.
        items.append(NewsItem(
            title=f"{ticker}: {headline}" if not headline.upper().startswith(ticker) else headline,
            url=url,
            source="Grok Squawk",
            published=now - timedelta(minutes=age),
            summary=f"via {source_for_url(url, 'X')}" if url else "via X",
            ticker_hint=ticker,
        ))
    return items


# ── Explain an unexplained move ──────────────────────────────────────

EXPLAIN_PROMPT = """Search X and the web for why {ticker} stock is moving \
{direction} {change:.1f}% today.

Answer in at most three sentences, stating the specific catalyst and when it \
happened. If there is no identifiable news and the move looks technical, sector-\
driven or unexplained, say exactly that — do not speculate. Cite your sources."""


def explain_move(ticker: str, change_pct: float, respect_throttle: bool = True) -> GrokAnswer:
    """Why is this ticker moving? For movers the engine found no catalyst for."""
    if not available():
        return GrokAnswer(error="XAI_API_KEY not set")
    return client().ask(
        EXPLAIN_PROMPT.format(
            ticker=ticker.upper(),
            direction="up" if change_pct >= 0 else "down",
            change=abs(change_pct),
        ),
        use_x=True, use_web=True, since_minutes=1440,
        respect_throttle=respect_throttle,
    )
