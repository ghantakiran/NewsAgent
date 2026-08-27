"""Tests for backend service modules."""

from backend.services.parser_service import (
    extract_tickers,
    extract_ticker_from_name,
    categorize,
    clean_html,
    make_article_id,
)
from backend.services.ud_service import (
    extract_ud_subject_ticker,
    extract_ud_firm,
    grade_ud,
)
from backend.services.article_service import (
    is_noise,
    deduplicate_articles,
    short_source,
)
from backend.services.earnings_service import (
    parse_earnings_from_article,
    get_earnings_by_ticker,
)


class TestTickerExtraction:
    def test_basic_tickers(self):
        tickers = extract_tickers("AAPL and NVDA reported earnings")
        assert "AAPL" in tickers
        assert "NVDA" in tickers

    def test_excludes_common_words(self):
        tickers = extract_tickers("THE CEO SAID ALL IS GOOD FOR NOW")
        assert tickers == []

    def test_max_10_tickers(self):
        text = " ".join([f"TICK{i}" for i in range(20)])
        tickers = extract_tickers(text)
        assert len(tickers) <= 10

    def test_no_duplicates(self):
        tickers = extract_tickers("AAPL beats AAPL estimates AAPL up")
        assert tickers.count("AAPL") == 1


class TestCompanyMapping:
    def test_apple(self):
        assert extract_ticker_from_name("Apple reports record revenue") == "AAPL"

    def test_nvidia(self):
        assert extract_ticker_from_name("nvidia beats expectations") == "NVDA"

    def test_no_match(self):
        assert extract_ticker_from_name("some random text") is None

    def test_target_not_tgt_in_price_context(self):
        result = extract_ticker_from_name("Goldman raises price target to $200")
        assert result != "TGT"


class TestCategorize:
    def test_earnings(self):
        assert categorize("AAPL beats earnings estimates", "", "general").value == "earnings"

    def test_upgrade_from_feed(self):
        assert categorize("Goldman upgrades AAPL", "", "upgrades_downgrades").value == "upgrade"

    def test_fda_from_feed(self):
        assert categorize("Drug gets new data", "", "fda").value == "fda"

    def test_general_default(self):
        assert categorize("Some random news", "", "general").value == "general"


class TestUDParsing:
    def test_extract_ticker_from_upgrade(self):
        ticker = extract_ud_subject_ticker("Goldman Sachs upgrades NVDA to Buy", "")
        assert ticker == "NVDA"

    def test_extract_firm(self):
        firm = extract_ud_firm("Goldman Sachs upgrades NVDA to Buy", "", "NVDA")
        assert "Goldman" in firm

    def test_grade_a_plus(self):
        grade = grade_ud("AAPL", "Goldman Sachs", "Buy", "$200", "upgrade")
        assert grade == "A+"

    def test_grade_c(self):
        grade = grade_ud("N/A", "", "", "", "mixed")
        assert grade == "C"


class TestNoiseFilter:
    def test_noise_detected(self):
        assert is_noise("husband wife divorce settlement") is True

    def test_not_noise(self):
        assert is_noise("AAPL earnings beat estimates", "earnings", True) is False

    def test_sports_noise(self):
        assert is_noise("NFL draft picks for 2024 super bowl") is True


class TestDeduplication:
    def test_dedup_by_title(self):
        articles = [
            {"title": "AAPL earnings beat", "category": "earnings", "tickers": ["AAPL"]},
            {"title": "AAPL earnings beat", "category": "earnings", "tickers": ["AAPL"]},
            {"title": "Different article", "category": "general", "tickers": []},
        ]
        deduped = deduplicate_articles(articles, apply_noise_filter=False)
        assert len(deduped) == 2


class TestEarnings:
    def test_parse_beat(self):
        result = parse_earnings_from_article(
            "AAPL beats estimates with EPS $1.52",
            "Revenue of $94.8B topped expectations",
            ["AAPL"], "http://example.com", "Yahoo",
            "2024-01-01T00:00:00Z", "earnings"
        )
        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["beat_miss"] == "beat"
        assert "$1.52" in result["eps"]

    def test_non_earnings_returns_none(self):
        result = parse_earnings_from_article(
            "Some news", "", [], "", "", "", "general"
        )
        assert result is None


class TestHelpers:
    def test_make_article_id(self):
        id1 = make_article_id("http://example.com/1")
        id2 = make_article_id("http://example.com/2")
        assert id1 != id2
        assert make_article_id("http://example.com/1") == id1  # deterministic

    def test_clean_html(self):
        assert clean_html("<p>Hello <b>world</b></p>") == "Hello world"
        assert clean_html("") == ""

    def test_short_source(self):
        assert short_source("Yahoo Finance News") == "Yahoo"
        assert short_source("Seeking Alpha News") == "SeekingAlpha"
