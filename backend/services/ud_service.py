"""Upgrade/Downgrade parsing, firm extraction, and grading.

Extracted from app.py lines 416-959 (ANALYST_FIRM_NAMES, _extract_ud_subject_ticker,
_extract_ud_firm, parse_upgrade_downgrade, grade_ud).
"""

import re

from .parser_service import (
    COMPANY_TO_TICKER,
    TICKER_EXCLUSIONS,
    _detect_ud_action,
    extract_ticker_from_name,
    extract_tickers,
)

# ──────────────────────────────────────────────────────────────
#  Analyst Firm Names (from app.py lines 418-437)
# ──────────────────────────────────────────────────────────────

ANALYST_FIRM_NAMES = {
    "goldman", "goldman sachs", "morgan stanley", "jpmorgan", "jp morgan",
    "bofa", "bofa securities", "bank of america", "citigroup", "citi",
    "barclays", "deutsche bank", "ubs", "credit suisse", "hsbc",
    "wells fargo", "raymond james", "piper sandler", "jefferies",
    "cowen", "td cowen", "wolfe research", "bernstein", "oppenheimer",
    "stifel", "needham", "wedbush", "canaccord", "rbc capital", "rbc",
    "bmo", "bmo capital", "btig", "mizuho", "truist",
    "evercore", "keybanc", "keybank", "loop capital", "rosenblatt",
    "susquehanna", "william blair", "da davidson", "baird",
    "guggenheim", "argus", "benchmark", "craig-hallum",
    "h.c. wainwright", "wainwright", "maxim group", "b. riley",
    "roth capital", "roth mkm", "lake street", "northland",
    "ladenburg", "cantor fitzgerald", "cantor", "macquarie",
    "redburn", "new street", "atlantic equities", "moffettnathanson",
    "sanford bernstein", "bnp paribas", "societe generale",
    "analyst", "analysts", "wall street", "seeking alpha", "sa analyst",
    "the street", "market", "markets", "investors",
}

# Known analyst firms for display (proper-case)
KNOWN_FIRMS = [
    "Goldman Sachs", "Goldman", "Morgan Stanley", "JPMorgan", "JP Morgan",
    "BofA", "BofA Securities", "Bank of America", "Citigroup", "Citi",
    "Barclays", "Deutsche Bank", "UBS", "Credit Suisse", "HSBC",
    "Wells Fargo", "Raymond James", "Piper Sandler", "Jefferies",
    "Cowen", "TD Cowen", "Wolfe Research", "Bernstein", "Oppenheimer",
    "Stifel", "Needham", "Wedbush", "Canaccord", "RBC Capital",
    "RBC", "BMO", "BMO Capital", "BTIG", "Mizuho", "Truist",
    "Evercore", "KeyBanc", "KeyBank", "Loop Capital", "Rosenblatt",
    "Susquehanna", "William Blair", "DA Davidson", "Baird",
    "Guggenheim", "Argus", "Benchmark", "Craig-Hallum",
    "H.C. Wainwright", "Wainwright", "Maxim Group", "B. Riley",
    "Roth Capital", "Roth MKM", "Lake Street", "Northland",
    "Ladenburg", "Cantor Fitzgerald", "Cantor", "Macquarie",
    "Redburn", "New Street", "Atlantic Equities", "MoffettNathanson",
    "Sanford Bernstein", "BNP Paribas", "Societe Generale",
]


def extract_ud_subject_ticker(title: str, summary: str) -> str:
    """Extract the stock ticker that is the SUBJECT of the upgrade/downgrade."""
    text = title + " " + summary

    # Pattern 0: Explicit parenthetical tickers like (AAPL), (NYSE:SMTC)
    m = re.search(r'\((?:NYSE|NASDAQ|NYSEARCA)?:?([A-Z]{1,5})\)', title)
    if m:
        candidate = m.group(1)
        if candidate not in TICKER_EXCLUSIONS:
            return candidate

    # Pattern 0b: "[TICKER]: Firm raises..." or "[TICKER] Stock:"
    m = re.match(r'^([A-Z]{1,5})(?:\s*:|(?:\s+(?:Stock|Analyst|Rating|Forecast|Price)))', title)
    if m:
        candidate = m.group(1)
        if candidate not in TICKER_EXCLUSIONS:
            return candidate

    # Pattern 1: "[Company/Ticker] receives/gets an upgrade/downgrade"
    m = re.match(r'^([\w\.\s&]+?)\s+(?:receives?|gets?|given)\s+(?:an?\s+)?(?:upgrade|downgrade|buy|sell|overweight|underweight|outperform|underperform|analyst|rating|price target)', title, re.IGNORECASE)
    if m:
        subject = m.group(1).strip()
        if subject.lower() not in ANALYST_FIRM_NAMES:
            if subject.isupper() and len(subject) <= 5 and subject not in TICKER_EXCLUSIONS:
                return subject
            mapped = extract_ticker_from_name(subject)
            if mapped:
                return mapped

    # Pattern 2: "[Firm] upgrades/downgrades [TICKER] to..."
    m = re.search(r'(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?)\s+(?:coverage\s+(?:on|of)\s+)?([A-Z]{1,5})\b', title)
    if m:
        candidate = m.group(1)
        if candidate not in TICKER_EXCLUSIONS:
            return candidate

    # Pattern 2b: "[Firm] upgrades/downgrades [Company Name] to..."
    m = re.search(r'(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?)\s+(?:coverage\s+(?:on|of)\s+)?([\w\.\s&]+?)(?:\s+(?:to|from|at|with|stock|price|rating|target)|\s*[,;:\-\(]|$)', title, re.IGNORECASE)
    if m:
        subject = m.group(1).strip()
        if subject.lower() not in ANALYST_FIRM_NAMES:
            if subject.isupper() and len(subject) <= 5 and subject not in TICKER_EXCLUSIONS:
                return subject
            mapped = extract_ticker_from_name(subject)
            if mapped:
                return mapped

    # Pattern 2c: "[Firm] raises/lowers [Company] stock price target"
    m = re.search(r'(?:raises?|lowers?|cuts?)\s+([\w\.\s&-]+?)\s+(?:stock\s+)?price\s+target', title, re.IGNORECASE)
    if m:
        subject = m.group(1).strip()
        if subject.lower() not in ANALYST_FIRM_NAMES:
            mapped = extract_ticker_from_name(subject)
            if mapped:
                return mapped
            tks = extract_tickers(subject)
            if tks:
                return tks[0]

    # Pattern 2d: "Raises/Lowers Price Target for [Company] ([TICKER])"
    m = re.search(r'(?:raises?|lowers?)\s+(?:\w+\s+)?(?:price\s+)?target\s+(?:for|on)\s+([\w\.\s&-]+?)(?:\s*\(|$)', title, re.IGNORECASE)
    if m:
        subject = m.group(1).strip()
        if subject.lower() not in ANALYST_FIRM_NAMES:
            mapped = extract_ticker_from_name(subject)
            if mapped:
                return mapped

    # Pattern 3: "[TICKER] upgraded/downgraded by..."
    m = re.match(r'^([A-Z]{1,5})\b\s+(?:upgraded|downgraded|initiated|reiterated)', title)
    if m:
        candidate = m.group(1)
        if candidate not in TICKER_EXCLUSIONS:
            return candidate

    # Pattern 3b: "Reaches Analyst Target Price" — not a real U/D
    if re.search(r'(?:reaches?|hits?|crosses?)\s+(?:above\s+|below\s+)?(?:analyst\s+|average\s+)*(?:target\s*(?:price)?|price\s+target)', title, re.IGNORECASE):
        m = re.match(r'^([\w\.\s&-]+?)\s+(?:reaches?|hits?|crosses?)', title, re.IGNORECASE)
        if m:
            subj = m.group(1).strip()
            if subj.isupper() and len(subj) <= 5 and subj not in TICKER_EXCLUSIONS:
                return subj
            mapped = extract_ticker_from_name(subj)
            if mapped:
                return mapped

    # Pattern 4: "...on [TICKER/Company]..." or "...for [TICKER/Company]..."
    m = re.search(r'(?<!target\s)\b(?:on|for)\s+([A-Z]{1,5})\b', title)
    if m:
        candidate = m.group(1)
        if candidate not in TICKER_EXCLUSIONS:
            return candidate

    # Pattern 5: Try company name mapping — but SKIP firm names
    action_split = re.split(r'\b(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?|raises?|lowers?|cuts?)\b', title, maxsplit=1, flags=re.IGNORECASE)
    if len(action_split) == 2:
        after_verb = action_split[1]
        clean = re.sub(r'\btarget\s+price\b|\b(?:stock\s+)?(?:price\s+)?target\b', '', after_verb, flags=re.IGNORECASE)
        mapped = extract_ticker_from_name(clean)
        if mapped:
            return mapped

    clean_title = re.sub(r'\btarget\s+price\b|\b(?:stock\s+)?(?:price\s+)?target\b', '', title, flags=re.IGNORECASE)
    mapped = extract_ticker_from_name(clean_title)
    if mapped:
        for firm_name in ANALYST_FIRM_NAMES:
            if firm_name in title.lower():
                firm_ticker = COMPANY_TO_TICKER.get(firm_name)
                if firm_ticker == mapped:
                    mapped = None
                    break
        if mapped:
            return mapped

    # Pattern 6: Try regex tickers from title
    clean_title2 = re.sub(r'\btarget\s+price\b|\b(?:price\s+)?target\b', '', title, flags=re.IGNORECASE)
    tickers = extract_tickers(clean_title2)
    if tickers:
        return tickers[0]

    # Pattern 7: Fall back to summary
    mapped = extract_ticker_from_name(summary)
    if mapped:
        return mapped
    tickers = extract_tickers(summary)
    if tickers:
        return tickers[0]

    return "N/A"


def extract_ud_firm(title: str, summary: str, subject_ticker: str) -> str:
    """Extract the analyst firm from a U/D headline."""
    text = title + " " + summary
    text_lower = text.lower()

    # Check for known firm names
    for firm in sorted(KNOWN_FIRMS, key=len, reverse=True):
        if firm.lower() in text_lower:
            return firm

    # Try regex patterns
    firm_patterns = [
        r'^([\w\.\s&]+?)\s+(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?|raises?|lowers?|cuts?)\s',
        r'(?:upgraded|downgraded|initiated|reiterated)\s+(?:by|at)\s+([\w\.\s&]+?)(?:\s*[,;:\-\(]|$)',
        r'after\s+([\w\.\s&]+?)\s+(?:upgrades?|downgrades?)',
    ]
    subject_names = set()
    for name, ticker in COMPANY_TO_TICKER.items():
        if ticker == subject_ticker:
            subject_names.add(name.lower())
    subject_names.add(subject_ticker.lower())

    noise_words = {"what", "does", "how", "why", "the", "this", "that", "it is",
                   "here", "there", "which", "where", "when", "who", "its",
                   "stock", "share", "analyst", "rating", "price", "target",
                   "receives", "gets", "given", "unknown"}

    for pattern in firm_patterns:
        m = re.search(pattern, title, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()[:50]
            cand_lower = candidate.lower()
            if len(candidate) <= 2:
                continue
            if candidate.upper() in TICKER_EXCLUSIONS:
                continue
            if cand_lower in subject_names:
                continue
            if any(sn in cand_lower for sn in subject_names if len(sn) > 2):
                continue
            if any(nw in cand_lower for nw in noise_words):
                continue
            return candidate

    return ""


def parse_upgrade_downgrade(article_title: str, article_summary: str,
                            article_tickers: list[str], article_published,
                            article_url: str, article_source: str) -> dict | None:
    """Parse upgrade/downgrade details from an article.

    Returns a dict with U/D fields or None if not a U/D article.
    """
    action = _detect_ud_action(article_title, article_summary)
    if action is None:
        return None

    ticker = extract_ud_subject_ticker(article_title, article_summary)
    firm = extract_ud_firm(article_title, article_summary, ticker)

    text = article_title + " " + article_summary

    # Extract ratings
    old_rating, new_rating = "", ""
    rating_patterns = [
        r'from\s+([\w\s-]+?)\s+to\s+([\w\s-]+?)(?:\s*[,;.\-\(]|$)',
        r'to\s+(Buy|Sell|Hold|Neutral|Overweight|Underweight|Outperform|Underperform|Market Perform|Equal Weight|Sector Weight)',
        r'(?:rating|rated)\s+(?:at|to|as)\s+(Buy|Sell|Hold|Neutral|Overweight|Underweight|Outperform|Underperform)',
        r'(?:Maintains|Reiterates|Initiates)\s+(?:with\s+)?(Buy|Sell|Hold|Neutral|Overweight|Underweight|Outperform|Underperform)',
        r'(?:stock rating at|stock rating to)\s+(Buy|Sell|Hold|Neutral|Overweight|Underweight|Outperform)',
    ]
    for pat in rating_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            if m.lastindex == 2:
                old_rating = m.group(1).strip()[:30]
                new_rating = m.group(2).strip()[:30]
            else:
                new_rating = m.group(1).strip()[:30]
            break

    # Extract price target
    price_target = ""
    pt_patterns = [
        r'\$([\d,.]+)',
        r'(?:price target|pt|target)\s*(?:of|to|at|:)?\s*\$?([\d,.]+)',
        r'(?:target|PT)\s*(?:raised|lowered|bumped|cut|set)\s*(?:to|at)?\s*\$?([\d,.]+)',
    ]
    for pat in pt_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(m.lastindex)
            try:
                num = float(val.replace(",", ""))
                if 0.5 <= num <= 99999:
                    price_target = f"${val}"
                    break
            except ValueError:
                continue

    return {
        "ticker": ticker,
        "firm": firm,
        "action": action,
        "old_rating": old_rating,
        "new_rating": new_rating,
        "price_target": price_target,
        "published": article_published,
        "source_url": article_url,
        "source": article_source,
    }


def grade_ud(ticker: str, firm: str, new_rating: str,
             price_target: str, action: str) -> str:
    """Grade analyst action quality: A+ (best) to C (incomplete)."""
    score = 0
    if ticker and ticker != "N/A":
        score += 1
    if firm:
        score += 1
    if new_rating:
        score += 1
    if price_target:
        score += 1
    if action and action not in ("mixed", "reiterated"):
        score += 1
    if score >= 5:
        return "A+"
    if score >= 4:
        return "A"
    if score >= 3:
        return "B"
    return "C"
