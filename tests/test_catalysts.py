"""Tests for the catalyst engine — detection, ticker resolution, scoring, storage.

Everything here is offline: the ticker universe is built from a fixture rather
than downloaded, and no test touches a quote provider.
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from newsagent.catalysts import detect as D  # noqa: E402
from newsagent.catalysts.engine import (  # noqa: E402
    Catalyst,
    CatalystEngine,
    CatalystSource,
    corroboration_factor,
    price_factor,
    recency_factor,
    score_catalyst,
    source_weight,
    ticker_factor,
)
from newsagent.catalysts.market import Quote, _previous_close  # noqa: E402
from newsagent.catalysts.store import (  # noqa: E402
    catalyst_stats,
    get_catalyst,
    get_catalysts,
    init_catalyst_tables,
    mark_alerted,
    pending_alerts,
    prune_catalysts,
    upsert_catalysts,
)
from newsagent.catalysts.types import SPECS, Direction  # noqa: E402
from newsagent.catalysts.types import CatalystType as CT
from newsagent.catalysts.universe import TickerUniverse, normalize_company  # noqa: E402

FIXTURE_SYMBOLS = {
    "AAPL": "Apple Inc.",
    "NVDA": "NVIDIA CORP",
    "SRPT": "Sarepta Therapeutics, Inc.",
    "MRNA": "Moderna, Inc.",
    "TGT": "TARGET CORP",
    "GS": "GOLDMAN SACHS GROUP INC",
    "QSR": "Restaurant Brands International Inc.",
    "ALOT": "AstroNova, Inc.",
    "CWD": "CaliberCos Inc.",
    "BMRA": "BIOMERICA INC",
    "LGVN": "Longeveron Inc.",
    "FTFT": "Future Fintech Group Inc.",
    "EXTR": "EXTREME NETWORKS INC",
}


@pytest.fixture
def universe():
    return TickerUniverse(FIXTURE_SYMBOLS)


@pytest.fixture
def engine(universe, tmp_path):
    return CatalystEngine(tmp_path, universe=universe)


@pytest.fixture
def cat_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_catalyst_tables(conn)
    yield conn
    conn.close()


def make_article(title, summary="", source="Benzinga", url="https://example.com/a", minutes_ago=5, aid="a1"):
    return {
        "id": aid, "title": title, "summary": summary, "source": source, "url": url,
        "published": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
    }


# ── Detection ────────────────────────────────────────────────────────

class TestDetection:
    @pytest.mark.parametrize("headline,expected", [
        ("FDA approves Acme's lead therapy for rare disease", CT.FDA_APPROVAL),
        ("Acme receives Complete Response Letter from FDA", CT.FDA_REJECTION),
        ("Acme agrees to be acquired by Blackstone for $4.2 billion", CT.BUYOUT_TARGET),
        ("Acme prices $50 million underwritten public offering", CT.OFFERING),
        ("Acme announces 1-for-20 reverse stock split", CT.REVERSE_SPLIT),
        ("Acme cuts full-year guidance", CT.GUIDANCE_CUT),
        ("Acme raises full-year guidance", CT.GUIDANCE_RAISE),
        ("Hindenburg Research targets Acme alleging fraud", CT.SHORT_REPORT),
        ("Acme files for Chapter 11 bankruptcy protection", CT.BANKRUPTCY),
        ("Acme joins the S&P 500", CT.INDEX_INCLUSION),
        ("Acme's phase 3 trial failed to meet its primary endpoint", CT.CLINICAL_NEGATIVE),
        ("Acme met its primary endpoint in pivotal study", CT.CLINICAL_POSITIVE),
        ("Acme CEO steps down", CT.EXEC_CHANGE),
        ("Acme receives notice of delisting from Nasdaq", CT.DELISTING),
    ])
    def test_types(self, headline, expected):
        assert expected in {d.type for d in D.detect(headline)}

    def test_direction_matches_type(self):
        assert SPECS[CT.FDA_APPROVAL].direction is Direction.BULLISH
        assert SPECS[CT.OFFERING].direction is Direction.BEARISH

    def test_no_catalyst_in_plain_news(self):
        assert D.detect("Markets were quiet ahead of the long weekend") == []

    def test_speculation_lowers_confidence(self):
        firm = D.detect("Acme agrees to be acquired by Blackstone")[0].confidence
        rumour = D.detect("Acme could reportedly be acquired by Blackstone")[0].confidence
        assert rumour < firm

    def test_opinion_pieces_discounted(self):
        assert D.is_opinion("3 Top Dividend Stocks to Buy in 2026")
        assert D.is_opinion("Why Rocket Lab Stock Soared Today")
        assert not D.is_opinion("Rocket Lab wins $500 million Space Force contract")

    def test_summary_matches_score_below_title_matches(self):
        from_title = D.detect("Acme cuts full-year guidance")[0].confidence
        from_summary = D.detect("Acme reports", "The company cuts full-year guidance")[0].confidence
        assert from_summary < from_title


class TestDigests:
    @pytest.mark.parametrize("headline", [
        "SA analyst upgrades/downgrades: AMD, DELL, ASAN, UPST",
        "Stock Market Today, June 1: Tech and Software Stocks Lift Markets",
        "Wall Street Lunch: Nvidia Unveils New AI Chips",
        "Top analyst calls of the week",
    ])
    def test_digest_detected(self, headline):
        assert D.is_digest(headline)

    def test_single_event_is_not_a_digest(self):
        assert not D.is_digest("Sarepta Therapeutics announces FDA approval")

    def test_engine_drops_digests(self, engine):
        assert engine.analyze([make_article("SA analyst upgrades/downgrades: AMD, DELL, ASAN")]) == []


class TestFactExtraction:
    def test_deal_value(self):
        assert D.extract_facts("Acme to be acquired for $4.2 billion")["deal_value"] == "$4.2 billion"

    def test_offering_size(self):
        assert D.extract_facts("prices $50 million public offering")["offering_size"] == "$50M"

    def test_phase(self):
        assert D.extract_facts("phase 3 trial data")["phase"] == "Phase 3"

    def test_percent_move(self):
        assert D.extract_facts("shares plunge 12%")["move_pct"] == "12%"

    def test_nothing_to_extract(self):
        assert D.extract_facts("Acme names a new chief executive") == {}


class TestFilings:
    def test_8k_item_maps_to_type(self):
        found = {d.type for d in D.detect_8k_items("Item 3.01: Notice of Delisting")}
        assert found == {CT.DELISTING}

    def test_routine_items_are_not_news(self):
        assert D.detect_8k_items("Item 7.01: Regulation FD <br />Item 9.01: Exhibits") == []

    def test_multiple_items(self):
        found = {d.type for d in D.detect_8k_items("Item 5.02: Departure <br />Item 2.02: Results")}
        assert found == {CT.EXEC_CHANGE, CT.EARNINGS_RESULTS}

    def test_sec_title_parsing(self):
        assert D.parse_sec_title("8-K - CaliberCos Inc. (0001627282) (Filer)") == ("8-K", "CaliberCos Inc.")

    def test_sec_title_rejects_prose(self):
        assert D.parse_sec_title("Apple beats on earnings") is None

    def test_non_operating_filers_excluded(self):
        assert D.is_non_operating_filer("Ark 21Shares Bitcoin ETF")
        assert D.is_non_operating_filer("Carlyle Private Equity Partners Fund, L.P.")
        assert not D.is_non_operating_filer("NVIDIA CORP")

    def test_filing_headline_is_readable(self):
        headline = D.filing_headline("CaliberCos Inc.", "8-K", ["3.01"])
        assert "CaliberCos" in headline and "delisting" in headline

    def test_source_routing(self):
        assert D.source_kind("SEC 8-K Filings") == "8k"
        assert D.source_kind("Nasdaq Trading Halts") == "halt"
        assert D.source_kind("Benzinga News") == ""


class TestHalts:
    HALT_HTML = (
        "<table><tr><th>Halt Date</th></tr><tr><td>08/26/2026</td><td>09:31:00</td>"
        "<td>LGVN</td><td>Longeveron Inc.</td><td>NASDAQ</td><td>T1</td></tr></table>"
    )

    def test_parses_html_table(self):
        halt = D.parse_halt("LGVN", self.HALT_HTML)
        assert halt == {"symbol": "LGVN", "reason_code": "T1", "reason": "News pending", "market": "NASDAQ"}

    def test_parses_flattened_text(self):
        # The feed pipeline strips HTML before storage.
        halt = D.parse_halt("LGVN", "08/26/2026 09:31:00 LGVN Longeveron Inc. NASDAQ T1")
        assert halt["reason_code"] == "T1"

    def test_unknown_reason_code_rejected(self):
        assert D.parse_halt("ABCD", "08/26/2026 09:31:00 ABCD Some Co NASDAQ ZZ9") is None


# ── Ticker resolution ────────────────────────────────────────────────

class TestTickerResolution:
    def test_exchange_parenthetical_wins(self, universe):
        best = universe.extract("Apple Inc. (NASDAQ: AAPL) beats on earnings")[0]
        assert (best.symbol, best.evidence) == ("AAPL", "exchange")

    def test_cashtag(self, universe):
        assert universe.primary("Why $NVDA is moving") == "NVDA"

    def test_company_name(self, universe):
        assert universe.primary("Sarepta Therapeutics announces FDA approval") == "SRPT"

    def test_ambiguous_single_word_name_ignored(self, universe):
        # "Target" the retailer vs. "target" the noun — never resolved by name.
        assert universe.primary("Target says CEO will step down") is None

    def test_lowercase_noun_phrase_is_not_a_company(self, universe):
        assert universe.primary("delivery growth and new restaurant brands drive results") is None

    def test_capitalised_multiword_name_resolves(self, universe):
        assert universe.primary("Restaurant Brands International reports a beat") == "QSR"

    def test_calendar_words_are_not_tickers(self, universe):
        assert universe.primary("Stock Market Today: shares rise") is None

    def test_invalid_symbols_rejected(self, universe):
        assert not universe.is_valid("ZZZZZ")
        assert universe.primary("The CEO told the SEC and FDA about GDP") is None

    def test_normalisation_strips_legal_suffixes(self):
        assert normalize_company("Apple Inc.") == "apple"
        assert normalize_company("BIOMERICA INC") == "biomerica"
        assert normalize_company("Sarepta Therapeutics, Inc.") == "sarepta therapeutics"

    def test_analyst_firm_is_not_the_subject(self, engine):
        # "Goldman Sachs upgrades Apple" is news about AAPL, not GS.
        catalysts = engine.analyze([make_article("Goldman Sachs upgrades Apple to Buy")], )
        assert catalysts and catalysts[0].ticker == "AAPL"

    def test_firm_names_stripped(self):
        assert "Goldman" not in D.strip_analyst_firms("Goldman Sachs upgrades Apple")


# ── Scoring ──────────────────────────────────────────────────────────

class TestScoring:
    def _catalyst(self, ctype=CT.FDA_APPROVAL, **kw):
        now = datetime.now(timezone.utc)
        defaults = {
            "id": "x", "ticker": "SRPT", "company": "Sarepta", "type": ctype,
            "direction": SPECS[ctype].direction, "headline": "h", "url": "u",
            "published": now, "latest": now,
            "detect_confidence": 1.0, "ticker_confidence": 1.0,
            "sources": [CatalystSource("Business Wire", "h", "u", now)],
        }
        defaults.update(kw)
        return Catalyst(**defaults)

    def test_impact_ordering_survives_scoring(self):
        approval = score_catalyst(self._catalyst(CT.FDA_APPROVAL))
        pt_raise = score_catalyst(self._catalyst(CT.PRICE_TARGET_RAISE))
        assert approval > pt_raise

    def test_score_is_bounded(self):
        c = self._catalyst(CT.BUYOUT_TARGET, quote=Quote("SRPT", price=10, prev_close=5, change_pct=100, volume=10**7, avg_volume=10**5))
        assert 0 <= score_catalyst(c) <= 100

    def test_recency_decays(self):
        now = datetime.now(timezone.utc)
        assert recency_factor(now, now) > recency_factor(now - timedelta(hours=6), now)
        assert recency_factor(now - timedelta(hours=6), now) > recency_factor(now - timedelta(days=3), now)

    def test_missing_ticker_penalised_except_macro(self):
        assert ticker_factor("", 0.0, CT.FDA_APPROVAL) < ticker_factor("SRPT", 1.0, CT.FDA_APPROVAL)
        assert ticker_factor("", 0.0, CT.MACRO) == 1.0

    def test_corroboration_rewards_multiple_sources(self):
        assert corroboration_factor(1) < corroboration_factor(4) <= 1.2

    def test_price_confirmation_boosts_and_conflict_penalises(self):
        big_up = Quote("X", price=11, prev_close=10, change_pct=10, volume=10**6, avg_volume=10**5)
        big_down = Quote("X", price=9, prev_close=10, change_pct=-10, volume=10**6, avg_volume=10**5)
        assert price_factor(big_up, Direction.BULLISH) > 1.0
        # The tape disagreeing with a bullish headline is a warning, not a boost.
        assert price_factor(big_down, Direction.BULLISH) < price_factor(big_down, Direction.BEARISH)

    def test_no_quote_is_neutral(self):
        assert price_factor(None, Direction.BULLISH) == 1.0

    def test_primary_sources_outrank_aggregators(self):
        assert source_weight("SEC 8-K Filings") > source_weight("Benzinga")
        assert source_weight("Reuters") > source_weight("Google News Earnings")

    def test_confirmed_requires_agreeing_move(self):
        bull = self._catalyst(CT.FDA_APPROVAL, quote=Quote("SRPT", price=11, prev_close=10, change_pct=10))
        against = self._catalyst(CT.FDA_APPROVAL, quote=Quote("SRPT", price=9, prev_close=10, change_pct=-10))
        assert bull.confirmed and not against.confirmed


class TestQuoteMath:
    def test_previous_close_uses_prior_session(self):
        # The last daily bar is the live session when it matches the live price.
        assert _previous_close(10.0, [8.0, 9.0, 10.0], {}) == 9.0

    def test_previous_close_when_session_not_yet_in_series(self):
        assert _previous_close(10.0, [8.0, 9.0], {}) == 9.0

    def test_relative_volume(self):
        assert Quote("X", price=5, volume=300, avg_volume=100).rel_volume == 3.0
        assert Quote("X", price=5, volume=300, avg_volume=0).rel_volume == 0.0

    def test_size_buckets(self):
        assert Quote("X", price=1, avg_volume=1_000).size_bucket == "micro"
        assert Quote("X", price=100, avg_volume=10_000_000).size_bucket == "liquid"


# ── Engine ───────────────────────────────────────────────────────────

class TestEngine:
    def test_end_to_end(self, engine):
        catalysts = engine.analyze([
            make_article("Sarepta Therapeutics announces FDA approves its lead therapy",
                         source="Business Wire", aid="a1"),
        ])
        assert len(catalysts) == 1
        c = catalysts[0]
        assert (c.ticker, c.type, c.direction) == ("SRPT", CT.FDA_APPROVAL, Direction.BULLISH)
        assert c.score > 0

    def test_clusters_same_event_across_outlets(self, engine):
        catalysts = engine.analyze([
            make_article("Sarepta Therapeutics announces FDA approves lead therapy",
                         source="Business Wire", aid="a1", url="u1"),
            make_article("FDA approves Sarepta Therapeutics lead therapy",
                         source="Reuters", aid="a2", url="u2"),
            make_article("Sarepta Therapeutics wins FDA approval for lead therapy",
                         source="CNBC", aid="a3", url="u3"),
        ])
        assert len(catalysts) == 1
        assert catalysts[0].source_count == 3

    def test_different_events_stay_separate(self, engine):
        catalysts = engine.analyze([
            make_article("Sarepta Therapeutics announces FDA approves lead therapy", aid="a1"),
            make_article("Moderna prices $200 million public offering", aid="a2"),
        ])
        assert {c.type for c in catalysts} == {CT.FDA_APPROVAL, CT.OFFERING}

    def test_ranked_by_score(self, engine):
        catalysts = engine.analyze([
            make_article("Analyst raises price target on Apple", aid="a1"),
            make_article("Apple agrees to be acquired in $400 billion all-cash deal", aid="a2"),
        ])
        assert catalysts == sorted(catalysts, key=lambda c: -c.score)

    def test_filing_feed_uses_item_codes(self, engine):
        catalysts = engine.analyze([make_article(
            "8-K - CaliberCos Inc. (0001627282) (Filer)",
            summary="Filed: 2026-08-26 Item 3.01: Notice of Delisting",
            source="SEC 8-K Filings", aid="a1",
        )])
        assert len(catalysts) == 1
        assert catalysts[0].type is CT.DELISTING
        assert catalysts[0].ticker == "CWD"
        # The raw EDGAR title is replaced with something readable.
        assert "(Filer)" not in catalysts[0].headline

    def test_halt_feed(self, engine):
        catalysts = engine.analyze([make_article(
            "LGVN", summary="08/26/2026 09:31:00 LGVN Longeveron Inc. NASDAQ T1",
            source="Nasdaq Trading Halts", aid="a1",
        )])
        assert len(catalysts) == 1
        assert catalysts[0].type is CT.TRADING_HALT
        assert catalysts[0].facts["halt_reason"] == "News pending"

    def test_reverse_split_not_reported_as_split(self, engine):
        catalysts = engine.analyze([make_article("Future Fintech Group announces 1-for-20 reverse stock split")])
        assert catalysts[0].type is CT.REVERSE_SPLIT

    def test_untitled_articles_ignored(self, engine):
        assert engine.analyze([{"id": "x", "title": "", "summary": "", "source": "", "url": "", "published": None}]) == []

    def test_accepts_objects_as_well_as_dicts(self, engine):
        class Row:
            id, title, source, url = "a1", "Moderna prices $200 million public offering", "PR Newswire", "u"
            summary = ""
            published = datetime.now(timezone.utc)
        assert engine.analyze([Row()])[0].type is CT.OFFERING


# ── Storage ──────────────────────────────────────────────────────────

class TestStore:
    def _seed(self, engine, conn, headlines=None):
        headlines = headlines or [
            ("Sarepta Therapeutics announces FDA approves lead therapy", "a1"),
            ("Moderna prices $200 million public offering", "a2"),
        ]
        catalysts = engine.analyze([make_article(h, aid=i) for h, i in headlines])
        return catalysts, upsert_catalysts(conn, catalysts)

    def test_insert_then_update(self, engine, cat_db):
        catalysts, (new, updated) = self._seed(engine, cat_db)
        assert (new, updated) == (len(catalysts), 0)
        assert upsert_catalysts(cat_db, catalysts) == (0, len(catalysts))

    def test_round_trip(self, engine, cat_db):
        self._seed(engine, cat_db)
        rows = get_catalysts(cat_db, hours=24)
        assert {r["ticker"] for r in rows} == {"SRPT", "MRNA"}
        assert all(r["label"] and r["color"] for r in rows)

    def test_first_seen_preserved_across_updates(self, engine, cat_db):
        catalysts, _ = self._seed(engine, cat_db)
        first = get_catalyst(cat_db, catalysts[0].id)["first_seen"]
        upsert_catalysts(cat_db, catalysts)
        assert get_catalyst(cat_db, catalysts[0].id)["first_seen"] == first

    def test_quote_data_survives_a_quoteless_rescan(self, engine, cat_db):
        catalysts, _ = self._seed(engine, cat_db)
        catalysts[0].quote = Quote("SRPT", price=20.0, prev_close=10.0, change_pct=100.0,
                                   volume=10**6, avg_volume=10**5)
        score_catalyst(catalysts[0])
        upsert_catalysts(cat_db, catalysts)
        priced = get_catalyst(cat_db, catalysts[0].id)
        assert priced["change_pct"] == 100.0

        catalysts[0].quote = None  # a fast, network-free rescan
        score_catalyst(catalysts[0])
        upsert_catalysts(cat_db, catalysts)
        assert get_catalyst(cat_db, catalysts[0].id)["change_pct"] == 100.0

    def test_filters(self, engine, cat_db):
        self._seed(engine, cat_db)
        assert len(get_catalysts(cat_db, groups=["clinical"])) == 1
        assert len(get_catalysts(cat_db, direction="bearish")) == 1
        assert len(get_catalysts(cat_db, ticker="SRPT")) == 1
        assert len(get_catalysts(cat_db, search="Moderna")) == 1
        assert len(get_catalysts(cat_db, min_score=101)) == 0

    def test_ordering(self, engine, cat_db):
        self._seed(engine, cat_db)
        scores = [r["score"] for r in get_catalysts(cat_db, order="score")]
        assert scores == sorted(scores, reverse=True)

    def test_stats(self, engine, cat_db):
        self._seed(engine, cat_db)
        stats = catalyst_stats(cat_db, hours=24)
        assert stats["total"] == 2 and stats["tickers"] == 2
        assert set(stats["by_group"]) == {"clinical", "capital"}

    def test_prune_drops_old_events(self, engine, cat_db):
        catalysts = engine.analyze([make_article("Sarepta Therapeutics announces FDA approves lead therapy",
                                                 minutes_ago=60 * 24 * 30)])
        upsert_catalysts(cat_db, catalysts)
        assert prune_catalysts(cat_db, days=7) == 1
        assert get_catalysts(cat_db, hours=24 * 365) == []

    def test_missing_catalyst_returns_none(self, cat_db):
        assert get_catalyst(cat_db, "nope") is None


class TestAlerts:
    def test_high_score_events_pend_then_clear(self, engine, cat_db):
        catalysts = engine.analyze([
            make_article("Sarepta Therapeutics announces FDA approves lead therapy", source="Business Wire"),
        ])
        upsert_catalysts(cat_db, catalysts)
        pending = pending_alerts(cat_db, min_score=10)
        assert len(pending) == 1
        mark_alerted(cat_db, pending, channel="discord")
        assert pending_alerts(cat_db, min_score=10) == []

    def test_below_threshold_does_not_alert(self, engine, cat_db):
        upsert_catalysts(cat_db, engine.analyze([make_article("Analyst raises price target on Apple")]))
        assert pending_alerts(cat_db, min_score=95) == []

    def test_watchlist_lowers_the_bar(self, engine, cat_db):
        upsert_catalysts(cat_db, engine.analyze([make_article("Analyst raises price target on Apple")]))
        assert pending_alerts(cat_db, min_score=100) == []
        assert pending_alerts(cat_db, min_score=40, watchlist=["AAPL"]) != []


class TestStalePruning:
    """Re-analysis must replace the board, not accumulate beside it."""

    def test_reresolved_event_does_not_duplicate(self, engine, cat_db):
        from newsagent.catalysts.store import prune_stale_catalysts

        article = make_article("Trian shelves take-private bid for Wendy's", aid="a1")
        first = engine.analyze([article])
        upsert_catalysts(cat_db, first)
        prune_stale_catalysts(cat_db, [c.id for c in first], hours=48)

        # Simulate ticker resolution improving: same event, different id.
        improved = engine.analyze([article])
        for c in improved:
            c.id = c.id[:-2] + "zz"
        upsert_catalysts(cat_db, improved)
        prune_stale_catalysts(cat_db, [c.id for c in improved], hours=48)

        rows = get_catalysts(cat_db, hours=48, min_score=0)
        assert len(rows) == len(improved)
        assert {r["id"] for r in rows} == {c.id for c in improved}

    def test_events_outside_the_window_survive(self, engine, cat_db):
        from newsagent.catalysts.store import prune_stale_catalysts

        old = engine.analyze([make_article("Acme prices $50 million public offering",
                                           minutes_ago=60 * 24 * 3, aid="old")])
        upsert_catalysts(cat_db, old)
        # A 6-hour scan had no chance to re-derive a 3-day-old event.
        prune_stale_catalysts(cat_db, [], hours=6)
        assert len(get_catalysts(cat_db, hours=24 * 7, min_score=0)) == len(old)

    def test_handles_more_ids_than_sqlite_parameter_limit(self, engine, cat_db):
        from newsagent.catalysts.store import prune_stale_catalysts

        catalysts = engine.analyze([make_article("Sarepta Therapeutics announces FDA approves therapy")])
        upsert_catalysts(cat_db, catalysts)
        keep = [c.id for c in catalysts] + [f"filler-{i}" for i in range(2000)]
        assert prune_stale_catalysts(cat_db, keep, hours=48) == 0
        assert len(get_catalysts(cat_db, hours=48, min_score=0)) == len(catalysts)
