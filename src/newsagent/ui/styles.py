"""CSS styles for dark theme NewsAgent UI.

Note: The primary CSS lives inline in app.py (DARK_CSS constant).
This module provides the theme for any standalone UI components.
"""

DARK_THEME_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

    :root {
        --bg-primary: #07080a;
        --bg-secondary: #0c0d10;
        --bg-elevated: #111318;
        --bg-hover: #161820;
        --border-subtle: #1c1e26;
        --border-medium: #252833;
        --text-primary: #e8eaf0;
        --text-secondary: #9ba1b0;
        --text-muted: #5c6375;
        --text-dim: #3d4255;
        --accent-red: #ff3b4e;
        --accent-green: #00d68f;
        --accent-blue: #0ea5e9;
        --accent-gold: #f5c542;
        --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
        --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
        --radius-sm: 4px;
        --radius-md: 8px;
        --radius-lg: 12px;
    }

    .stApp {
        background-color: var(--bg-primary);
        color: var(--text-primary);
        font-family: var(--font-sans);
    }

    .newsagent-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.5rem 0;
        border-bottom: 1px solid var(--border-subtle);
        margin-bottom: 1rem;
    }
    .newsagent-logo {
        font-size: 1.6rem;
        font-weight: 900;
        background: linear-gradient(135deg, #ff3b4e, #ff6b7a);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.5px;
    }
    .newsagent-logo span {
        color: var(--text-dim);
        font-weight: 500;
    }

    .status-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 14px;
        background: var(--bg-elevated);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        margin-bottom: 10px;
        font-size: 0.76rem;
        color: var(--text-muted);
    }

    .article-card {
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 10px 16px;
        border-bottom: 1px solid var(--border-subtle);
        transition: all 0.2s ease;
        line-height: 1.6;
    }
    .article-card:hover {
        background: linear-gradient(90deg, var(--bg-hover) 0%, transparent 100%);
    }

    .article-time {
        color: var(--text-dim);
        font-size: 0.74rem;
        font-family: var(--font-mono);
        min-width: 62px;
        flex-shrink: 0;
        font-weight: 500;
    }

    .ticker-badge {
        background: rgba(14,165,233,0.08);
        color: var(--accent-blue);
        padding: 2px 9px;
        border-radius: var(--radius-sm);
        font-size: 0.73rem;
        font-weight: 700;
        font-family: var(--font-mono);
        margin-right: 4px;
        border: 1px solid rgba(14,165,233,0.15);
        letter-spacing: 0.6px;
    }

    .cat-tag {
        padding: 2px 10px;
        border-radius: 100px;
        font-size: 0.64rem;
        font-weight: 700;
        margin-left: 6px;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }

    .article-title {
        color: var(--text-primary);
        font-size: 0.86rem;
        line-height: 1.45;
        text-decoration: none;
        flex: 1;
        min-width: 0;
    }
    .article-title:hover {
        color: #fff;
        text-decoration: underline;
        text-decoration-color: var(--border-medium);
        text-underline-offset: 3px;
    }

    .source-badge {
        color: var(--text-dim);
        font-size: 0.68rem;
        margin-left: 8px;
        white-space: nowrap;
    }

    .ud-row {
        display: grid;
        grid-template-columns: 52px 56px auto;
        align-items: center;
        padding: 8px 12px;
        border-bottom: 1px solid var(--border-subtle);
        gap: 8px;
        transition: background 0.2s ease;
    }
    .ud-row:hover {
        background: linear-gradient(90deg, var(--bg-hover) 0%, transparent 100%);
    }

    .ud-ticker { font-weight: 800; font-size: 0.9rem; font-family: var(--font-mono); }
    .ud-action-upgrade { color: var(--accent-green); font-weight: 700; font-size: 0.74rem; }
    .ud-action-downgrade { color: var(--accent-red); font-weight: 700; font-size: 0.74rem; }
    .ud-firm { color: var(--text-secondary); font-size: 0.78rem; }
    .ud-rating { color: var(--text-primary); font-size: 0.78rem; }
    .ud-pt { color: var(--accent-gold); font-weight: 700; font-size: 0.82rem; font-family: var(--font-mono); }

    .stat-box {
        background: var(--bg-elevated);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        padding: 1rem;
        text-align: center;
        margin-bottom: 8px;
    }
    .stat-number { font-size: 1.6rem; font-weight: 800; color: #fff; font-family: var(--font-mono); }
    .stat-label { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }

    .feed-ok { color: var(--accent-green); }
    .feed-err { color: var(--accent-red); }
    .feed-disabled { color: var(--text-dim); }

    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        background: var(--bg-secondary);
        border-radius: var(--radius-lg);
        padding: 4px;
        border: 1px solid var(--border-subtle);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 9px 16px;
        font-size: 0.80rem;
        color: var(--text-muted);
        border-radius: var(--radius-md);
        transition: all 0.2s ease;
        font-weight: 600;
    }
    .stTabs [data-baseweb="tab"]:hover { color: var(--text-secondary); }
    .stTabs [aria-selected="true"] {
        background: var(--bg-hover) !important;
        color: #fff !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    .stTabs [data-baseweb="tab-highlight"] { display: none; }
    .stTabs [data-baseweb="tab-border"] { display: none; }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    .watchlist-chip {
        display: inline-block;
        background: rgba(14,165,233,0.10);
        color: var(--accent-blue);
        padding: 4px 12px;
        border-radius: 100px;
        font-size: 0.78rem;
        font-weight: 700;
        margin: 2px 4px;
        font-family: var(--font-mono);
        border: 1px solid rgba(14,165,233,0.15);
    }

    .pulse {
        display: inline-block;
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: var(--accent-green);
        animation: pulse-anim 2s infinite;
        margin-right: 8px;
    }
    @keyframes pulse-anim {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
    }
</style>
"""
