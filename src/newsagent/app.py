"""NewsAgent — Streamlit entry point."""

import logging
from datetime import datetime, timedelta, timezone

import streamlit as st

from .database import (
    get_articles,
    get_article_count,
    get_connection,
    get_source_counts,
    get_upgrades_downgrades,
    init_db,
    prune_old_articles,
)
from .feeds import (
    add_custom_feed,
    load_all_feeds,
    load_custom_feeds,
    load_settings,
    remove_custom_feed,
    toggle_feed,
)
from .fetcher import FeedRefresher, fetch_all_feeds, get_fetch_errors, get_last_fetch_time
from .models import Category
from .ui.components import render_article_list, render_header, render_stat_box, render_status_bar, render_ud_list
from .ui.styles import DARK_THEME_CSS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Page Config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="NewsAgent",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Inject dark theme
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# Load settings
settings = load_settings()
REFRESH_INTERVAL = settings.get("general", {}).get("refresh_interval", 30)
MAX_ARTICLES = settings.get("general", {}).get("max_articles", 500)
PRUNE_DAYS = settings.get("general", {}).get("prune_after_days", 7)

# ── Session State Init ──────────────────────────────────────────────
if "watchlist" not in st.session_state:
    st.session_state.watchlist = []
if "refresher_started" not in st.session_state:
    st.session_state.refresher_started = False

# ── Initialize DB ────────────────────────────────────────────────────
conn = get_connection()
init_db(conn)
prune_old_articles(conn, PRUNE_DAYS)

# ── Load & Start Feeds ──────────────────────────────────────────────
feeds = load_all_feeds()

# Start background refresher immediately (non-blocking).
# The refresher fetches on its first tick, so the UI loads instantly
# and data appears within seconds as feeds come in.
if not st.session_state.refresher_started:
    refresher = FeedRefresher(feeds, interval=REFRESH_INTERVAL)
    refresher.start()
    st.session_state.refresher_started = True
    st.session_state.refresher = refresher

# ── Header ───────────────────────────────────────────────────────────
render_header(st.session_state.watchlist)

# ── Sidebar: Watchlist & Settings ────────────────────────────────────
with st.sidebar:
    st.markdown("### Watchlist")
    new_ticker = st.text_input(
        "Add ticker", placeholder="e.g. AAPL", max_chars=5, key="new_ticker_input"
    ).upper().strip()
    if new_ticker and st.button("Add", key="add_ticker_btn"):
        if new_ticker not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_ticker)
            st.rerun()

    if st.session_state.watchlist:
        for i, t in enumerate(st.session_state.watchlist):
            col1, col2 = st.columns([3, 1])
            col1.markdown(f'<span class="watchlist-chip">{t}</span>', unsafe_allow_html=True)
            if col2.button("X", key=f"rm_ticker_{i}"):
                st.session_state.watchlist.pop(i)
                st.rerun()

    st.divider()

    st.markdown("### Stats")
    article_count = get_article_count(conn)
    render_stat_box("Articles Cached", article_count)

    source_counts = get_source_counts(conn)
    if source_counts:
        render_stat_box("Active Sources", len(source_counts))

    last_fetch = get_last_fetch_time()
    if last_fetch:
        st.caption(f"Last fetch: {last_fetch.strftime('%H:%M:%S')} UTC")

    errors = get_fetch_errors()
    if errors:
        with st.expander(f"Feed Errors ({len(errors)})"):
            for name, err in errors.items():
                st.caption(f"**{name}**: {err[:80]}")

# ── Main Tabs ────────────────────────────────────────────────────────
tab_feed, tab_ud, tab_catalysts, tab_rss = st.tabs(
    ["📰 Live Feed", "📊 Upgrades / Downgrades", "⚡ Catalysts", "📡 RSS Feeds"]
)


# ═══════════════════════════════════════════════════════════════════════
# Tab 1: Live Feed — auto-refreshes every 30s via st.fragment
# ═══════════════════════════════════════════════════════════════════════
@st.fragment(run_every=timedelta(seconds=REFRESH_INTERVAL))
def live_feed_fragment():
    """Auto-refreshing live news feed."""
    fconn = get_connection()

    col_search, col_cat, col_ticker = st.columns([3, 1, 1])
    with col_search:
        search_query = st.text_input(
            "Search", placeholder="Search headlines...",
            label_visibility="collapsed", key="search_feed",
        )
    with col_cat:
        cat_options = ["all"] + [c.value for c in Category]
        selected_cat = st.selectbox(
            "Category", cat_options, key="cat_filter", label_visibility="collapsed",
        )
    with col_ticker:
        ticker_options = ["All Tickers"] + st.session_state.watchlist
        selected_ticker = st.selectbox(
            "Ticker", ticker_options, key="ticker_filter", label_visibility="collapsed",
        )

    ticker_filter = selected_ticker if selected_ticker != "All Tickers" else None

    articles = get_articles(
        fconn,
        limit=MAX_ARTICLES,
        category=selected_cat if selected_cat != "all" else None,
        ticker=ticker_filter,
        search=search_query if search_query else None,
    )

    render_status_bar(len(articles), REFRESH_INTERVAL, get_last_fetch_time())

    render_article_list(articles)
    fconn.close()


with tab_feed:
    live_feed_fragment()


# ═══════════════════════════════════════════════════════════════════════
# Tab 2: Upgrades/Downgrades — auto-refreshes
# ═══════════════════════════════════════════════════════════════════════
@st.fragment(run_every=timedelta(seconds=REFRESH_INTERVAL))
def ud_fragment():
    """Auto-refreshing upgrades/downgrades feed."""
    fconn = get_connection()

    col1, col2 = st.columns([2, 2])
    with col1:
        ud_ticker_filter = st.text_input(
            "Filter by ticker", placeholder="e.g. NVDA", key="ud_ticker_filter",
        ).upper().strip()
    with col2:
        st.markdown("")

    uds = get_upgrades_downgrades(
        fconn, limit=100,
        ticker=ud_ticker_filter if ud_ticker_filter else None,
    )

    # Also show articles categorized as upgrade/downgrade
    ud_articles = get_articles(
        fconn, limit=100, category="upgrade",
        ticker=ud_ticker_filter if ud_ticker_filter else None,
    )
    ud_articles += get_articles(
        fconn, limit=100, category="downgrade",
        ticker=ud_ticker_filter if ud_ticker_filter else None,
    )

    if uds:
        st.markdown(f'**{len(uds)} analyst actions detected**')
        render_ud_list(uds)

    if ud_articles:
        st.markdown(f'**{len(ud_articles)} upgrade/downgrade articles**')
        render_article_list(ud_articles)

    if not uds and not ud_articles:
        st.markdown(
            '<div style="text-align:center;color:#555;padding:3rem 0">'
            'No upgrades/downgrades detected yet.<br>'
            '<span style="font-size:0.8rem">Monitoring analyst feeds for rating changes...</span></div>',
            unsafe_allow_html=True,
        )
    fconn.close()


with tab_ud:
    ud_fragment()


# ═══════════════════════════════════════════════════════════════════════
# Tab 3: Catalysts — auto-refreshes
# ═══════════════════════════════════════════════════════════════════════
@st.fragment(run_every=timedelta(seconds=REFRESH_INTERVAL))
def catalysts_fragment():
    """Auto-refreshing catalysts feed."""
    fconn = get_connection()

    catalyst_cats = ["earnings", "fda", "m&a", "ipo", "insider", "dividend", "filing"]
    selected_catalyst = st.selectbox(
        "Catalyst Type", ["all"] + catalyst_cats, key="catalyst_type",
        label_visibility="collapsed",
    )

    if selected_catalyst == "all":
        catalyst_articles = []
        for cat in catalyst_cats:
            catalyst_articles.extend(get_articles(fconn, limit=50, category=cat))
        # Normalize all datetimes to UTC-aware for safe comparison
        def _sort_key(a):
            dt = a.published
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        catalyst_articles.sort(key=_sort_key, reverse=True)
        catalyst_articles = catalyst_articles[:100]
    else:
        catalyst_articles = get_articles(fconn, limit=100, category=selected_catalyst)

    render_status_bar(len(catalyst_articles), REFRESH_INTERVAL, get_last_fetch_time())

    render_article_list(catalyst_articles)
    fconn.close()


with tab_catalysts:
    catalysts_fragment()


# ═══════════════════════════════════════════════════════════════════════
# Tab 4: RSS Feeds — static (no auto-refresh needed)
# ═══════════════════════════════════════════════════════════════════════
with tab_rss:
    st.markdown("### Default Feeds")
    custom_feed_names = {cf.name for cf in load_custom_feeds()}
    default_feeds = [f for f in feeds if f.name not in custom_feed_names]
    errors = get_fetch_errors()

    for feed in default_feeds:
        err = errors.get(feed.name)
        col1, col2 = st.columns([4, 1])
        with col1:
            if err:
                status_icon = "🔴"
            elif feed.enabled:
                status_icon = "🟢"
            else:
                status_icon = "⚪"
            st.markdown(f"{status_icon} **{feed.name}**  \n`{feed.url}`")
        with col2:
            st.markdown(f"*{feed.category}*")
        if err:
            st.caption(f"Error: {err[:100]}")

    st.divider()
    st.markdown("### Custom Feeds")

    custom_feeds = load_custom_feeds()
    if custom_feeds:
        for cf in custom_feeds:
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"**{cf.name}**  \n`{cf.url}`")
            with col2:
                new_state = st.checkbox("Enabled", value=cf.enabled, key=f"cf_toggle_{cf.name}")
                if new_state != cf.enabled:
                    toggle_feed(cf.name, new_state)
                    st.rerun()
            with col3:
                if st.button("Remove", key=f"cf_del_{cf.name}"):
                    remove_custom_feed(cf.name)
                    st.rerun()
    else:
        st.caption("No custom feeds added yet.")

    st.divider()
    st.markdown("### Add Custom Feed")
    with st.form("add_feed_form"):
        col1, col2 = st.columns(2)
        with col1:
            new_feed_name = st.text_input("Feed Name", placeholder="My Custom Feed")
        with col2:
            new_feed_cat = st.selectbox(
                "Category",
                ["general", "upgrades_downgrades", "fda", "filings", "crypto"],
            )
        new_feed_url = st.text_input("RSS URL", placeholder="https://example.com/feed.xml")

        if st.form_submit_button("Add Feed"):
            if new_feed_name and new_feed_url:
                add_custom_feed(new_feed_name, new_feed_url, new_feed_cat)
                st.success(f"Added feed: {new_feed_name}")
                if hasattr(st.session_state, "refresher"):
                    st.session_state.refresher.update_feeds(load_all_feeds())
                st.rerun()
            else:
                st.error("Please fill in both name and URL.")

conn.close()
