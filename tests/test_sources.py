"""Tests for news source adapters, fan-out tiering, and the Grok client.

All offline: HTML is parsed from fixtures and the Grok client is exercised
against a stubbed transport, so the suite never touches Finviz or the xAI API.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from newsagent.catalysts import fanout, grok  # noqa: E402
from newsagent.catalysts.fanout import (  # noqa: E402
    Tier,
    TieredScheduler,
    dedupe,
    group_by_tier,
    tier_for,
)
from newsagent.catalysts.sources import (  # noqa: E402
    NewsItem,
    fetch_finviz_news,
    fetch_finviz_ticker,
    parse_finviz_time,
    source_for_url,
)

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)

FINVIZ_NEWS_HTML = """
<html><body>
<table class="styled-table-new"><tbody>
  <tr class="news_table-row"><td></td><td>07:00AM</td>
    <td><a class="nn-tab-link" href="https://www.reuters.com/markets/story-a">Reuters headline A</a></td></tr>
  <tr class="news_table-row"><td></td><td>06:55AM</td>
    <td><a class="nn-tab-link" href="https://www.wsj.com/finance/story-b">WSJ headline B</a></td></tr>
</tbody></table>
<table class="styled-table-new"><tbody>
  <tr class="news_table-row"><td></td><td>06:00AM</td>
    <td><a class="nn-tab-link" href="https://example.com/blog">A blog opinion post</a></td></tr>
</tbody></table>
</body></html>
"""

FINVIZ_TICKER_HTML = """
<html><body><table id="news-table"><tbody>
  <tr><td>Aug-26-26 11:13AM</td><td>
      <a href="https://www.businesswire.com/x">Acme prices $50 million offering</a>
      <div><span>(Business Wire)</span></div></td></tr>
  <tr><td>10:18AM</td><td>
      <a href="https://www.barrons.com/y">Acme stock sinks on trial result</a>
      <div><span>(Barrons.com)</span></div></td></tr>
</tbody></table></body></html>
"""


def stub_client(html: str) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))


# ── Source attribution ───────────────────────────────────────────────

class TestSourceAttribution:
    @pytest.mark.parametrize("url,expected", [
        ("https://www.reuters.com/markets/x", "Reuters"),
        ("https://www.wsj.com/finance/y", "Wall Street Journal"),
        ("https://finance.yahoo.com/news/z", "Yahoo Finance"),
        ("https://www.businesswire.com/news/a", "Business Wire"),
        ("https://www.stocktitan.net/news/b", "StockTitan"),
    ])
    def test_known_domains(self, url, expected):
        assert source_for_url(url) == expected

    def test_unknown_domain_falls_back_to_host(self):
        assert source_for_url("https://www.someblog.io/post") == "someblog.io"

    def test_garbage_url_uses_fallback(self):
        assert source_for_url("", "Finviz") == "Finviz"


# ── Finviz time parsing ──────────────────────────────────────────────

class TestFinvizTime:
    def test_dated_row(self):
        ts, carry = parse_finviz_time("Aug-26-26 11:13AM", None, NOW)
        assert ts == datetime(2026, 8, 26, 15, 13, tzinfo=timezone.utc)  # 11:13 ET
        assert carry is not None

    def test_bare_time_inherits_previous_date(self):
        _, carry = parse_finviz_time("Aug-26-26 11:13AM", None, NOW)
        ts, _ = parse_finviz_time("10:18AM", carry, NOW)
        assert ts.date() == datetime(2026, 8, 26, tzinfo=timezone.utc).date()

    def test_today_prefix_stripped(self):
        ts, _ = parse_finviz_time("Today 09:30AM", None, NOW)
        assert ts.date() == NOW.astimezone(timezone.utc).date()

    def test_future_bare_time_rolls_back_a_day(self):
        # 11:00PM ET has not happened yet at 16:00 UTC, so it is yesterday's.
        ts, _ = parse_finviz_time("11:00PM", None, NOW)
        assert ts < NOW

    def test_unparseable_falls_back_to_now(self):
        ts, carry = parse_finviz_time("Loading…", None, NOW)
        assert ts == NOW and carry is None


# ── Finviz adapters ──────────────────────────────────────────────────

class TestFinvizAdapters:
    def test_news_table_only_not_blogs(self):
        with stub_client(FINVIZ_NEWS_HTML) as c:
            items = fetch_finviz_news(c)
        assert [i.title for i in items] == ["Reuters headline A", "WSJ headline B"]

    def test_credits_original_publisher_not_finviz(self):
        with stub_client(FINVIZ_NEWS_HTML) as c:
            items = fetch_finviz_news(c)
        assert {i.source for i in items} == {"Reuters", "Wall Street Journal"}

    def test_ticker_page_uses_provider_span(self):
        with stub_client(FINVIZ_TICKER_HTML) as c:
            items = fetch_finviz_ticker("ACME", c)
        assert [i.source for i in items] == ["Business Wire", "Barrons.com"]

    def test_ticker_page_sets_hint_not_tickers(self):
        # A per-ticker page also lists peer stories, so the symbol is a hint.
        with stub_client(FINVIZ_TICKER_HTML) as c:
            items = fetch_finviz_ticker("ACME", c)
        assert all(i.ticker_hint == "ACME" for i in items)
        assert all(i.tickers == [] for i in items)

    def test_network_failure_returns_empty(self):
        def boom(request):
            raise httpx.ConnectError("down")
        with httpx.Client(transport=httpx.MockTransport(boom)) as c:
            assert fetch_finviz_news(c) == []
            assert fetch_finviz_ticker("ACME", c) == []

    def test_items_carry_stable_ids(self):
        with stub_client(FINVIZ_NEWS_HTML) as c:
            first = fetch_finviz_news(c)
        with stub_client(FINVIZ_NEWS_HTML) as c:
            second = fetch_finviz_news(c)
        assert [i.id for i in first] == [i.id for i in second]


# ── Tiering ──────────────────────────────────────────────────────────

class TestTiering:
    @pytest.mark.parametrize("name,category,expected", [
        ("SEC 8-K Filings", "filing", Tier.FLASH),
        ("Nasdaq Trading Halts", "filing", Tier.FLASH),
        ("StockTitan Press Releases", "general", Tier.FLASH),
        ("Business Wire", "general", Tier.FLASH),
        ("Finviz News", "general", Tier.FAST),
        ("MarketWatch Real-Time Headlines", "general", Tier.FAST),
        ("Yahoo Finance", "general", Tier.STEADY),
        ("Google News Earnings", "earnings", Tier.STEADY),
    ])
    def test_tier_assignment(self, name, category, expected):
        assert tier_for(name, category) is expected

    def test_grouping_covers_every_feed(self):
        feeds = [
            {"name": "SEC 8-K Filings", "category": "filing"},
            {"name": "Finviz News", "category": "general"},
            {"name": "Yahoo Finance", "category": "general"},
        ]
        grouped = group_by_tier(feeds)
        assert sum(len(v) for v in grouped.values()) == len(feeds)
        assert len(grouped[Tier.FLASH]) == 1


class TestScheduler:
    def test_all_tiers_due_initially(self):
        assert set(TieredScheduler().due(now=0.0)) == set(Tier)

    def test_marked_tier_not_due_until_interval_elapses(self):
        s = TieredScheduler({Tier.FLASH: 10, Tier.FAST: 45, Tier.STEADY: 180})
        s.mark(Tier.FLASH, now=0.0)
        assert Tier.FLASH not in s.due(now=5.0)
        assert Tier.FLASH in s.due(now=11.0)

    def test_fast_tier_runs_more_often_than_slow(self):
        s = TieredScheduler({Tier.FLASH: 10, Tier.STEADY: 180})
        for tier in (Tier.FLASH, Tier.STEADY):
            s.mark(tier, now=0.0)
        due_at_60s = s.due(now=60.0)
        assert Tier.FLASH in due_at_60s and Tier.STEADY not in due_at_60s

    def test_sleep_hint_never_exceeds_shortest_interval(self):
        s = TieredScheduler({Tier.FLASH: 10, Tier.STEADY: 180})
        for tier in (Tier.FLASH, Tier.STEADY):
            s.mark(tier, now=0.0)
        assert s.seconds_until_next(now=0.0) == 10


class TestDedupe:
    def _item(self, title, url, minutes_ago, source):
        return NewsItem(title=title, url=url, source=source,
                        published=NOW - timedelta(minutes=minutes_ago))

    def test_keeps_earliest_sighting(self):
        # Latency is the point: whoever printed it first owns the timestamp.
        items = [
            self._item("Acme halted", "https://x/1", 2, "Yahoo"),
            self._item("Acme halted", "https://x/1", 9, "Business Wire"),
        ]
        result = dedupe(items)
        assert len(result) == 1
        assert result[0].source == "Business Wire"

    def test_distinct_urls_survive(self):
        items = [self._item("A", "https://x/1", 1, "S"), self._item("B", "https://x/2", 2, "S")]
        assert len(dedupe(items)) == 2

    def test_sorted_newest_first(self):
        items = [self._item("old", "https://x/1", 30, "S"), self._item("new", "https://x/2", 1, "S")]
        assert [i.title for i in dedupe(items)] == ["new", "old"]

    def test_urlless_items_key_on_source_and_title(self):
        items = [self._item("Same", "", 5, "Grok"), self._item("Same", "", 8, "Grok")]
        assert len(dedupe(items)) == 1


class TestLatency:
    def test_latency_seconds(self):
        item = NewsItem(title="t", url="u", source="s", published=NOW - timedelta(seconds=90))
        assert fanout.latency_seconds(item, NOW) == pytest.approx(90, abs=1)

    def test_future_timestamps_clamp_to_zero(self):
        item = NewsItem(title="t", url="u", source="s", published=NOW + timedelta(minutes=5))
        assert fanout.latency_seconds(item, NOW) == 0.0


# ── Grok ─────────────────────────────────────────────────────────────

class TestGrokWithoutKey:
    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        assert not grok.available()

    def test_every_entry_point_degrades_quietly(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        assert grok.fetch_squawk() == []
        assert not grok.explain_move("NVDA", 5.0).ok


class TestGrokParsing:
    def test_responses_shape(self):
        payload = {"output": [{"type": "message",
                               "content": [{"type": "output_text", "text": "answer"}]}]}
        assert grok._collect_text(payload) == "answer"

    def test_output_text_shortcut(self):
        assert grok._collect_text({"output_text": "answer"}) == "answer"

    def test_chat_completions_shape(self):
        assert grok._collect_text({"choices": [{"message": {"content": "answer"}}]}) == "answer"

    def test_unknown_shape_yields_empty(self):
        assert grok._collect_text({"weird": True}) == ""

    def test_citations_from_all_locations(self):
        payload = {
            "citations": ["https://x.com/a"],
            "output": [{"content": [{"annotations": [{"url": "https://reuters.com/b"}]}]}],
        }
        urls = grok._collect_citations(payload, "also https://wsj.com/c")
        assert urls == ["https://x.com/a", "https://reuters.com/b", "https://wsj.com/c"]

    def test_citations_deduplicated(self):
        payload = {"citations": ["https://x.com/a", "https://x.com/a"]}
        assert grok._collect_citations(payload, "") == ["https://x.com/a"]

    @pytest.mark.parametrize("text,expected_len", [
        ('[{"ticker":"NVDA","headline":"h"}]', 1),
        ('```json\n[{"ticker":"NVDA","headline":"h"}]\n```', 1),
        ('prose before [{"ticker":"A","headline":"h"}] prose after', 1),
        ("not json at all", 0),
        ("", 0),
    ])
    def test_json_extraction(self, text, expected_len):
        assert len(grok.parse_json_list(text)) == expected_len


class TestGrokSquawk:
    def _respond(self, monkeypatch, payload, status=200):
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        captured = {}

        def fake_post(url, json=None, timeout=None, headers=None):
            captured["url"] = url
            captured["body"] = json
            captured["headers"] = headers
            return httpx.Response(status, json=payload)

        monkeypatch.setattr(grok.httpx, "post", fake_post)
        return captured

    def test_request_matches_documented_api(self, monkeypatch):
        captured = self._respond(monkeypatch, {"output_text": "[]"})
        grok.GrokClient().ask("hello", use_x=True, use_web=True)
        assert captured["url"] == "https://api.x.ai/v1/responses"
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        body = captured["body"]
        assert body["input"] == [{"role": "user", "content": "hello"}]
        assert {t["type"] for t in body["tools"]} == {"x_search", "web_search"}

    def test_x_search_can_be_scoped_to_handles(self, monkeypatch):
        captured = self._respond(monkeypatch, {"output_text": "[]"})
        grok.GrokClient().ask("hi", use_web=False, allowed_handles=["DeItaone"])
        x_tool = captured["body"]["tools"][0]
        assert x_tool["type"] == "x_search"
        assert x_tool["allowed_x_handles"] == ["DeItaone"]

    def test_squawk_items_become_news_items(self, monkeypatch):
        payload = {"output_text": '[{"ticker":"SRPT","headline":"FDA approves therapy",'
                                  '"minutes_ago":3,"url":"https://x.com/p/1"}]'}
        self._respond(monkeypatch, payload)
        items = grok.fetch_squawk(minutes=30, respect_throttle=False)
        assert len(items) == 1
        assert items[0].ticker_hint == "SRPT"
        assert items[0].source == "Grok Squawk"
        assert "FDA approves therapy" in items[0].title

    def test_squawk_drops_rows_without_a_usable_ticker(self, monkeypatch):
        payload = {"output_text": '[{"ticker":"","headline":"something"},'
                                  '{"ticker":"TOOLONGSYM","headline":"x"},'
                                  '{"ticker":"OK","headline":"good"}]'}
        self._respond(monkeypatch, payload)
        items = grok.fetch_squawk(respect_throttle=False)
        assert [i.ticker_hint for i in items] == ["OK"]

    def test_squawk_ages_items_from_minutes_ago(self, monkeypatch):
        payload = {"output_text": '[{"ticker":"AAA","headline":"h","minutes_ago":10}]'}
        self._respond(monkeypatch, payload)
        item = grok.fetch_squawk(minutes=30, respect_throttle=False)[0]
        age = (datetime.now(timezone.utc) - item.published).total_seconds()
        assert 540 < age < 660

    def test_http_error_is_not_raised(self, monkeypatch):
        self._respond(monkeypatch, {"error": "nope"}, status=500)
        assert grok.fetch_squawk(respect_throttle=False) == []

    def test_throttle_blocks_rapid_calls(self, monkeypatch):
        self._respond(monkeypatch, {"output_text": "[]"})
        c = grok.GrokClient(min_interval=999)
        assert c.ask("first").error != "throttled"
        assert c.ask("second").error == "throttled"

    def test_explain_move_returns_text_and_citations(self, monkeypatch):
        payload = {"output_text": "Halted pending news.", "citations": ["https://x.com/p/2"]}
        self._respond(monkeypatch, payload)
        answer = grok.GrokClient().ask("why")
        assert answer.ok
        assert answer.citations == ["https://x.com/p/2"]
