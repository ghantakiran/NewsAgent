"""Tests for Pydantic models."""

from backend.models.schemas import (
    ArticleResponse,
    Category,
    CATEGORY_COLORS,
    UpgradeDowngradeResponse,
    EarningsResultResponse,
    FeedResponse,
    TokenResponse,
)


def test_category_values():
    assert Category.EARNINGS.value == "earnings"
    assert Category.UPGRADE.value == "upgrade"
    assert Category.DOWNGRADE.value == "downgrade"


def test_category_colors_complete():
    for cat in Category:
        assert cat in CATEGORY_COLORS


def test_article_response():
    article = ArticleResponse(
        id="abc123",
        title="Test Article",
        url="http://example.com",
        source="Test Source",
        published="2024-01-01T00:00:00Z",
        category="earnings",
        tickers=["AAPL"],
    )
    assert article.id == "abc123"
    assert article.tickers == ["AAPL"]


def test_token_response():
    token = TokenResponse(
        access_token="abc",
        refresh_token="def",
    )
    assert token.token_type == "bearer"
