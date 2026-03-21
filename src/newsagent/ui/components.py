"""Reusable UI components for NewsAgent."""

import html as html_mod
import streamlit as st
from datetime import datetime, timezone

from ..models import Article, Category, CATEGORY_COLORS, UpgradeDowngrade


def _esc(text: str) -> str:
    """HTML-escape text to prevent rendering issues."""
    return html_mod.escape(text, quote=True)


def _relative_time(dt: datetime) -> str:
    """Format a datetime as a human-readable relative time string."""
    try:
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())

        if seconds < 0:
            return "just now"
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 7:
            return f"{days}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return "--:--"


def _render_article_html(article: Article) -> str:
    """Build HTML for a single article row."""
    time_str = article.published.strftime("%H:%M")
    rel_time = _relative_time(article.published)

    # Determine if recent (< 15 min)
    try:
        now = datetime.now(timezone.utc)
        pub = article.published
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        is_recent = (now - pub).total_seconds() < 900
    except Exception:
        is_recent = False

    time_class = "article-time article-time-recent" if is_recent else "article-time"

    # Ticker badges
    ticker_html = "".join(
        f'<span class="ticker-badge">{_esc(t)}</span>' for t in article.tickers[:3]
    )

    # Category tag
    cat_color = CATEGORY_COLORS.get(article.category, "#6b7394")
    cat_name = article.category.value.upper()
    cat_html = (
        f'<span class="cat-tag" style="background:{cat_color}14;'
        f'color:{cat_color};border:1px solid {cat_color}28">{cat_name}</span>'
    )

    title = _esc(article.title)
    url = _esc(article.url)
    source = _esc(article.source)

    return (
        f'<div class="article-card">'
        f'<span class="{time_class}">{time_str}</span> '
        f'<span class="article-time" style="min-width:52px;color:#3a3a3a">{rel_time}</span> '
        f'{ticker_html}'
        f'<a href="{url}" target="_blank" class="article-title">{title}</a> '
        f'{cat_html} '
        f'<span class="source-badge">{source}</span>'
        f'</div>'
    )


def render_article_list(articles: list[Article]) -> None:
    """Render a list of articles as a single HTML block."""
    if not articles:
        st.markdown(
            '<div style="text-align:center;color:#555;padding:2rem">'
            'No articles yet. Feeds are being fetched...</div>',
            unsafe_allow_html=True,
        )
        return

    # Batch all articles into one HTML block for better rendering performance
    parts = [_render_article_html(a) for a in articles]
    st.markdown("\n".join(parts), unsafe_allow_html=True)


def _render_ud_html(ud: UpgradeDowngrade) -> str:
    """Build HTML for an upgrade/downgrade row."""
    rel_time = _relative_time(ud.published)

    action_class = "ud-action-upgrade" if ud.action in ("upgrade", "initiated") else "ud-action-downgrade"
    action_label = _esc(ud.action.upper())
    ticker_color = "#00d68f" if "upgrade" in ud.action or "initiat" in ud.action else "#ff3b4e"

    rating_str = ""
    if ud.old_rating and ud.new_rating:
        rating_str = f'{_esc(ud.old_rating)} → {_esc(ud.new_rating)}'
    elif ud.new_rating:
        rating_str = _esc(ud.new_rating)

    pt_html = f'<span class="ud-pt">{_esc(ud.price_target)}</span>' if ud.price_target else ""

    return (
        f'<div class="ud-row">'
        f'<span class="article-time">{rel_time}</span>'
        f'<span class="ud-ticker" style="color:{ticker_color}">{_esc(ud.ticker)}</span>'
        f'<span class="{action_class}">{action_label}</span>'
        f'<span class="ud-firm">{_esc(ud.firm)}</span>'
        f'<span class="ud-rating">{rating_str}</span>'
        f'{pt_html}'
        f'<span class="source-badge">{_esc(ud.source)}</span>'
        f'</div>'
    )


def render_ud_list(uds: list[UpgradeDowngrade]) -> None:
    """Render list of upgrades/downgrades as a single HTML block."""
    if not uds:
        st.markdown(
            '<div style="text-align:center;color:#555;padding:2rem">'
            'No upgrades/downgrades detected yet. Monitoring feeds...</div>',
            unsafe_allow_html=True,
        )
        return

    parts = [_render_ud_html(ud) for ud in uds]
    st.markdown("\n".join(parts), unsafe_allow_html=True)


def render_stat_box(label: str, value: str | int) -> None:
    """Render a stat metric box."""
    st.markdown(
        f'<div class="stat-box"><div class="stat-number">{value}</div>'
        f'<div class="stat-label">{label}</div></div>',
        unsafe_allow_html=True,
    )


def render_status_bar(article_count: int, refresh_interval: int, last_fetch: datetime | None = None) -> None:
    """Render a compact status bar showing live status, article count, and refresh info."""
    if last_fetch:
        try:
            if last_fetch.tzinfo is None:
                last_fetch = last_fetch.replace(tzinfo=timezone.utc)
            fetch_str = last_fetch.strftime("%H:%M:%S")
            fetch_delta = _relative_time(last_fetch)
            fetch_html = f'<span class="refresh-info">Last fetch: <span style="color:#666">{fetch_str} UTC</span> ({fetch_delta})</span>'
        except Exception:
            fetch_html = '<span class="refresh-info">Fetching...</span>'
    else:
        fetch_html = '<span class="refresh-info">Fetching...</span>'

    st.markdown(
        f'<div class="status-bar">'
        f'<div class="status-left">'
        f'<span class="status-dot"></span>'
        f'<span class="article-count">{article_count} articles</span>'
        f'</div>'
        f'<div>{fetch_html} &middot; refreshes every {refresh_interval}s</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_header(watchlist: list[str]) -> None:
    """Render the top header bar."""
    col1, col2, col3 = st.columns([2, 4, 2])

    with col1:
        st.markdown(
            '<div class="newsagent-logo"><span class="pulse"></span>'
            'NewsAgent <span>v1.0</span></div>',
            unsafe_allow_html=True,
        )

    with col2:
        if watchlist:
            chips = " ".join(f'<span class="watchlist-chip">{t}</span>' for t in watchlist)
            st.markdown(chips, unsafe_allow_html=True)

    with col3:
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        st.markdown(
            f'<div style="text-align:right;color:#555;font-size:0.8rem;padding-top:8px">{now}</div>',
            unsafe_allow_html=True,
        )


def render_feed_status(feed_name: str, enabled: bool, error: str | None = None, is_custom: bool = False) -> dict:
    """Render a feed status row. Returns action dict."""
    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

    with col1:
        if error:
            status = '<span class="feed-err">ERR</span>'
        elif enabled:
            status = '<span class="feed-ok">OK</span>'
        else:
            status = '<span class="feed-disabled">OFF</span>'
        st.markdown(f'{status} **{feed_name}**', unsafe_allow_html=True)

    with col2:
        if error:
            st.caption(error[:40])

    action = {}
    with col3:
        if is_custom:
            new_enabled = st.checkbox("On", value=enabled, key=f"toggle_{feed_name}")
            if new_enabled != enabled:
                action["toggle"] = new_enabled

    with col4:
        if is_custom:
            if st.button("X", key=f"del_{feed_name}", type="secondary"):
                action["delete"] = True

    return action
