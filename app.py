"""NewsAgent — Real-time stock market news aggregator.

Run with: streamlit run app.py
"""

import hashlib
import html as html_mod
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import httpx
import streamlit as st
import toml
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("newsagent")

ROOT = Path(__file__).parent

# The catalyst engine lives in src/ so the FastAPI backend can share it.
sys.path.insert(0, str(ROOT / "src"))
from newsagent.catalysts import fanout as fanout_mod  # noqa: E402
from newsagent.catalysts import grok as grok_mod  # noqa: E402
from newsagent.catalysts import sources as sources_mod  # noqa: E402
from newsagent.catalysts import (  # noqa: E402
    SPECS as CATALYST_SPECS,
    CatalystEngine,
    CatalystGroup,
    CatalystType,
    catalyst_stats,
    get_catalysts,
    init_catalyst_tables,
    prune_catalysts,
    prune_stale_catalysts,
    upsert_catalysts,
)

# ══════════════════════════════════════════════════════════════════════
#  Timezone support
# ══════════════════════════════════════════════════════════════════════

TIMEZONE_OPTIONS = {
    "US/Eastern (ET)": "America/New_York",
    "US/Central (CT)": "America/Chicago",
    "US/Mountain (MT)": "America/Denver",
    "US/Pacific (PT)": "America/Los_Angeles",
    "UTC": "UTC",
    "London (GMT/BST)": "Europe/London",
    "Europe/Central (CET)": "Europe/Berlin",
    "India (IST)": "Asia/Kolkata",
    "Hong Kong (HKT)": "Asia/Hong_Kong",
    "Singapore (SGT)": "Asia/Singapore",
    "Tokyo (JST)": "Asia/Tokyo",
    "Sydney (AEST)": "Australia/Sydney",
}


def _get_user_tz() -> ZoneInfo:
    """Get the user's selected timezone from session state."""
    tz_name = st.session_state.get("user_tz", "America/New_York")
    return ZoneInfo(tz_name)


def _to_local(dt: datetime) -> datetime:
    """Convert a datetime to the user's selected timezone."""
    tz = _get_user_tz()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def _format_time(dt: datetime, fmt: str = "%H:%M:%S") -> str:
    """Format a datetime in the user's selected timezone."""
    try:
        return _to_local(dt).strftime(fmt)
    except Exception:
        return "--:--:--" if "S" in fmt else "--:--"


def _tz_abbrev() -> str:
    """Get short abbreviation for the current timezone."""
    try:
        return _to_local(datetime.now(timezone.utc)).strftime("%Z")
    except Exception:
        return "UTC"


def _relative_time(dt: datetime) -> str:
    """Return a human-readable relative time string like '2m ago', '3h ago'."""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════
#  Models
# ══════════════════════════════════════════════════════════════════════

class Category(str, Enum):
    GENERAL = "general"
    EARNINGS = "earnings"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    MACRO = "macro"
    FDA = "fda"
    MA = "m&a"
    IPO = "ipo"
    INSIDER = "insider"
    DIVIDEND = "dividend"
    FILING = "filing"
    CRYPTO = "crypto"
    TECH = "tech"


CATEGORY_COLORS = {
    Category.GENERAL: "#6b7394",
    Category.EARNINGS: "#f5c542",
    Category.UPGRADE: "#00d68f",
    Category.DOWNGRADE: "#ff3b4e",
    Category.MACRO: "#0ea5e9",
    Category.FDA: "#a78bfa",
    Category.MA: "#f97316",
    Category.IPO: "#06b6d4",
    Category.INSIDER: "#fb923c",
    Category.DIVIDEND: "#4ade80",
    Category.FILING: "#94a3b8",
    Category.CRYPTO: "#f59e0b",
    Category.TECH: "#8b5cf6",
}


@dataclass
class Article:
    id: str
    title: str
    url: str
    source: str
    published: datetime
    category: Category = Category.GENERAL
    tickers: list[str] = field(default_factory=list)
    summary: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Symbol of the per-ticker page this came from, when fan-out fetched it.
    # Only a hint — the catalyst engine prefers what the headline itself names.
    ticker_hint: str = ""


@dataclass
class Feed:
    name: str
    url: str
    category: str = "general"
    enabled: bool = True
    last_fetched: datetime | None = None
    error: str | None = None


@dataclass
class UpgradeDowngrade:
    ticker: str
    firm: str
    action: str
    old_rating: str
    new_rating: str
    price_target: str = ""
    published: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_url: str = ""
    source: str = ""


# ══════════════════════════════════════════════════════════════════════
#  Parser — ticker extraction, categorization
# ══════════════════════════════════════════════════════════════════════

TICKER_EXCLUSIONS = {
    # Single letters (most are not real tickers in news context)
    "A", "B", "C", "D", "E", "G", "H", "I", "J", "K", "L", "M", "N", "O",
    "P", "Q", "R", "S", "U", "W", "X", "Y", "Z",
    # 2-letter common words
    "AM", "PM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "AD", "AG", "AH", "AW", "AX", "EM", "EX", "HA", "HI", "HO",
    "LA", "LO", "MA", "OH", "OW", "OX", "PA", "PI", "RE", "TA",
    # 3-letter common words / abbreviations
    "CEO", "CFO", "COO", "CTO", "FDA", "SEC", "FED", "GDP", "IPO", "ETF",
    "NYSE", "API", "CEO", "CPI", "PPI", "DOJ", "EPA", "FBI", "CIA", "NSA",
    "IRS", "IMF", "WHO", "CDC", "NIH", "MIT", "IBM", "LLC", "INC", "LTD",
    "AGO", "ACE", "ACT", "ADD", "AGE", "AID", "AIM", "AIR", "ALL", "AND",
    "ANY", "APE", "ARC", "ARE", "ARK", "ART", "ASK", "ATE", "AWE",
    "BAD", "BAG", "BAN", "BAR", "BAT", "BED", "BET", "BID", "BIG", "BIT",
    "BOX", "BOY", "BUS", "BUT", "BUY", "CAB", "CAN", "CAP", "CAR", "COP",
    "CUP", "CUT", "DAD", "DAM", "DAY", "DID", "DIG", "DIP", "DOG", "DOT",
    "DRY", "DUE", "DUG", "EAR", "EAT", "EGG", "END", "ERA", "EVE", "EYE",
    "FAD", "FAN", "FAR", "FAT", "FAX", "FED", "FEE", "FEW", "FIG", "FIN",
    "FIT", "FIX", "FLY", "FOR", "FOX", "FUN", "FUR", "GAP", "GAS", "GAY",
    "GET", "GOD", "GOT", "GUM", "GUN", "GUT", "GUY", "HAD", "HAS", "HAT",
    "HER", "HID", "HIM", "HIP", "HIS", "HIT", "HOG", "HOP", "HOT", "HOW",
    "HUB", "HUG", "ICE", "ILL", "INK", "INN", "ION", "ITS", "JAM", "JAR",
    "JAW", "JET", "JOB", "JOG", "JOY", "KEY", "KID", "KIN", "KIT",
    "LAB", "LAP", "LAW", "LAY", "LED", "LEG", "LET", "LID", "LIE", "LIP",
    "LIT", "LOG", "LOT", "LOW", "MAD", "MAN", "MAP", "MAT", "MAY", "MEN",
    "MET", "MID", "MIX", "MOB", "MOM", "MOP", "MUD", "MUG",
    "NAP", "NET", "NEW", "NIT", "NOD", "NOR", "NOT", "NOW", "NUN", "NUT",
    "OAK", "OAT", "ODD", "OFF", "OIL", "OLD", "ONE", "OPT", "ORB", "ORE",
    "OUR", "OUT", "OWE", "OWL", "OWN", "PAD", "PAN", "PAT", "PAW", "PAY",
    "PEA", "PEG", "PEN", "PER", "PET", "PIE", "PIG", "PIN", "PIT", "PLY",
    "POD", "POP", "POT", "POW", "PRO", "PRY", "PUB", "PUG", "PUN", "PUP",
    "PUT", "RAG", "RAM", "RAN", "RAP", "RAT", "RAW", "RAY", "RED", "REF",
    "RIB", "RID", "RIG", "RIM", "RIP", "ROB", "ROD", "ROT", "ROW", "RUB",
    "RUG", "RUN", "RUT", "SAD", "SAG", "SAP", "SAT", "SAW", "SAY", "SEA",
    "SET", "SEW", "SHE", "SHY", "SIN", "SIP", "SIS", "SIT", "SIX", "SKI",
    "SKY", "SLY", "SOB", "SOD", "SON", "SOP", "SOT", "SOW", "SOY", "SPA",
    "SPY", "STY", "SUB", "SUM", "SUN", "SUP",
    "TAB", "TAG", "TAN", "TAP", "TAR", "TAX", "TEA", "TEN", "THE", "TIE",
    "TIN", "TIP", "TOE", "TON", "TOO", "TOP", "TOW", "TOY", "TRY", "TUB",
    "TUG", "TWO", "URN", "USE", "VAN", "VAT", "VET", "VIA", "VOW",
    "WAD", "WAR", "WAX", "WAY", "WEB", "WED", "WET", "WIG", "WIN", "WIT",
    "WOE", "WOK", "WON", "WOO", "WOW", "YAM", "YAP", "YAW", "YEA", "YES",
    "YET", "YEW", "YOU", "ZAP", "ZEN", "ZIP", "ZIT", "ZOO",
    # 4-5 letter common words / false positives
    "ALSO", "JUST", "OVER", "THAN", "THEM", "VERY", "WHEN", "WITH", "FROM",
    "HERE", "INTO", "LAST", "LONG", "MADE", "MANY", "MORE", "MOST", "MUCH",
    "MUST", "NAME", "ONLY", "PART", "SAID", "SAME", "SOME", "SUCH", "TELL",
    "THAT", "THIS", "WHAT", "WILL", "YEAR", "YOUR", "AFTER", "COULD",
    "EVERY", "FIRST", "ABOUT", "BEEN", "CALL", "CAME", "COME", "EACH",
    "FIND", "FREE", "GOOD", "HAVE", "HELP", "HOLD", "KEEP", "KNOW", "LIKE",
    "LIVE", "LOOK", "MAKE", "NEAR", "NEXT", "OPEN", "PLAN", "REAL", "RISE",
    "SEEN", "SHOW", "TAKE", "TURN", "WANT", "WELL", "WORK", "EVEN", "BACK",
    "DOWN", "FULL", "GIVE", "GOES", "HALF", "LATE", "LESS", "LOSS", "MOVE",
    "NEED", "ONCE", "RATE", "REST", "SELL", "SIDE", "SIGN", "STILL", "SURE",
    "TALK", "THEN", "USED", "WEEK", "BEST", "BOTH", "DEAL", "DOES", "DONE",
    "DREW", "EVER", "FACT", "GETS", "GREW", "GROW", "HOPE", "HUGE", "IDEA",
    "LEFT", "LINE", "LINK", "LIST", "LOST", "MAIN", "MARK", "MEAN", "MEET",
    "NOTE", "PAST", "PLAY", "PUSH", "READ", "SAYS", "SENT", "STEP", "STOP",
    "TEST", "TOLD", "TRUE", "TYPE", "VIEW", "VOTE", "WAIT", "WENT", "WERE",
    "WIDE", "WORD", "ZERO", "HIGH",
    # Financial / news jargon that looks like tickers
    "EST", "PST", "CST", "MST", "UTC", "RSS", "USA", "UK",
    "EV", "TV", "PE", "Q1", "Q2", "Q3", "Q4", "PT", "SA", "RBC", "BUY",
    "IRA", "CAD", "EUR", "GBP", "JPY", "CNY", "AUD", "NZD", "CHF",
    "ESG", "APY", "APR", "YTD", "MTD", "QTD", "TTM", "NAV", "AUM",
    "HOME", "LOAN", "BANK", "BOND", "CASH", "DEBT", "FUND", "GAIN",
    "GOLD", "REIT", "RISK", "SAFE", "SAVE", "SPAC", "SWAP", "WAGE",
    "BEAR", "BULL", "BUMP", "BURN", "BUST", "CHIP", "CORE", "COST",
    "DATA", "DROP", "DUMP", "EARN", "EDGE", "FARE", "FEAR", "FIRM",
    "FLAT", "FLOW", "FOOD", "FUEL", "HIKE", "JOBS", "JUMP", "JUST",
    "LAND", "LEAD", "LEAN", "LEVY", "LIEN", "MISS", "PARE", "PEAK",
    "POLL", "PORT", "PURE", "PUSH", "RACE", "RAID", "RALLY", "RANK",
    "REPO", "RULE", "RUSH", "SEED", "SINK", "SLIP", "SLOW", "SNAP",
    "SOAR", "SOLD", "SPAN", "SPEC", "SPIN", "SPOT", "SPUR", "STAY",
    "STEM", "STOCK", "SURGE", "SWEEP", "SWING", "TECH", "TERM",
    "TICK", "TIER", "TOLL", "TRIM", "UNIT", "VETO", "VOID", "WARN",
    "WARY", "WEAK", "WRAP", "YIELD",
    # News / article words
    "AMID", "EYES", "FACE", "FILE", "FORM", "HITS", "MOVE", "NEAR",
    "NEWS", "PAYS", "PUTS", "SEES", "SETS", "TAPS", "TOPS", "WINS",
    "ABOVE", "AHEAD", "BELOW", "EARLY", "EXTRA", "FINAL", "GIVEN",
    "LATER", "LEAST", "LEVEL", "LOCAL", "LOWER", "MAJOR", "MIGHT",
    "NEVER", "OTHER", "OUTER", "POINT", "POWER", "PRESS", "PRICE",
    "PRIOR", "QUICK", "QUITE", "RANGE", "RAPID", "READY", "RIGHT",
    "ROUND", "SHARP", "SHORT", "SINCE", "SMALL", "SOLID", "SOUTH",
    "SPENT", "SPOKE", "START", "STATE", "THEIR", "THERE", "THESE",
    "THINK", "THREE", "TIMES", "TODAY", "TOTAL", "TRADE", "UNDER",
    "UNION", "UNTIL", "UPPER", "USING", "VALUE", "WATCH", "WHICH",
    "WHILE", "WHOLE", "WORLD", "WORSE", "WORST", "WORTH", "WOULD",
    # Organizations / abbreviations that look like tickers
    "NATO", "CNBC", "NBC", "CBS", "ABC", "CNN", "BBC", "PBS", "NPR",
    "GOP", "DNC", "NFL", "NBA", "NHL", "MLB", "FIFA", "UEFA", "NCAA",
    "OPEC", "ASEAN", "EU", "UN", "WHO", "CDC", "NIH", "USDA",
    "EVP", "SVP", "AVP", "VP", "MD", "CD", "DVD", "USB", "CPU", "GPU",
    "RAM", "ROM", "SSD", "HDD", "LED", "LCD", "PDF", "URL", "HTML",
    "FOMC", "FDIC", "CFPB", "OCC", "FINRA", "SIPC", "CFTC",
    "MSCI", "FTSE", "DAX", "IBEX", "NIFTY", "HANG",
    # Common false-positive tickers from financial news
    "FEOC", "NBP", "GTC", "OTC", "ADR", "ADS",
    "SHS", "PFD", "DEP", "SER", "SUV", "RSI", "CEO",
    "USD", "UST", "BPS", "PCT", "YOY", "MOM", "QOQ", "DCF", "EBIT",
    "WACC", "ROE", "ROI", "ROA", "EPS", "FFO", "AFFO",
    "GAAP", "EBITDA", "CAPEX", "SGA", "COGS", "FCF", "OCF",
    "MACD", "RSI", "SMA", "EMA", "ATH", "ATL", "DMA",
}

TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b')

# Company name → ticker mapping for resolving names in headlines
COMPANY_TO_TICKER = {
    "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN", "alphabet": "GOOGL",
    "google": "GOOGL", "meta": "META", "facebook": "META", "nvidia": "NVDA",
    "tesla": "TSLA", "netflix": "NFLX", "adobe": "ADBE", "salesforce": "CRM",
    "amd": "AMD", "intel": "INTC", "qualcomm": "QCOM", "broadcom": "AVGO",
    "cisco": "CSCO", "oracle": "ORCL", "ibm": "IBM", "uber": "UBER",
    "airbnb": "ABNB", "spotify": "SPOT", "snap": "SNAP", "pinterest": "PINS",
    "palantir": "PLTR", "snowflake": "SNOW", "datadog": "DDOG", "crowdstrike": "CRWD",
    "cloudflare": "NET", "shopify": "SHOP", "block": "SQ", "square": "SQ",
    "paypal": "PYPL", "coinbase": "COIN", "robinhood": "HOOD", "sofi": "SOFI",
    "arm": "ARM", "rivian": "RIVN", "lucid": "LCID", "nio": "NIO",
    "disney": "DIS", "warner": "WBD", "paramount": "PARA", "comcast": "CMCSA",
    "boeing": "BA", "lockheed": "LMT", "raytheon": "RTX", "northrop": "NOC",
    "jpmorgan": "JPM", "goldman": "GS", "morgan stanley": "MS", "bofa": "BAC",
    "bank of america": "BAC", "wells fargo": "WFC", "citigroup": "C", "citi": "C",
    "visa": "V", "mastercard": "MA", "american express": "AXP", "amex": "AXP",
    "walmart": "WMT", "target": "TGT", "costco": "COST", "home depot": "HD",
    "starbucks": "SBUX", "mcdonald": "MCD", "mcdonalds": "MCD", "chipotle": "CMG",
    "coca-cola": "KO", "pepsi": "PEP", "pepsico": "PEP", "procter": "PG",
    "johnson & johnson": "JNJ", "pfizer": "PFE", "moderna": "MRNA", "eli lilly": "LLY",
    "lilly": "LLY", "abbvie": "ABBV", "merck": "MRK", "amgen": "AMGN",
    "unitedhealth": "UNH", "chevron": "CVX", "exxon": "XOM", "exxonmobil": "XOM",
    "conocophillips": "COP", "caterpillar": "CAT", "deere": "DE", "3m": "MMM",
    "honeywell": "HON", "general electric": "GE", "ford": "F", "general motors": "GM",
    "figma": "FIGM", "td bank": "TD", "blackstone": "BX", "kkr": "KKR",
    "dell": "DELL", "hp": "HPQ", "micron": "MU", "applied materials": "AMAT",
    "lam research": "LRCX", "marvell": "MRVL", "synopsys": "SNPS", "cadence": "CDNS",
    "servicenow": "NOW", "workday": "WDAY", "twilio": "TWLO", "okta": "OKTA",
    "zscaler": "ZS", "palo alto": "PANW", "fortinet": "FTNT", "mongodb": "MDB",
    "elastic": "ESTC", "confluent": "CFLT", "hashicorp": "HCP",
    "docusign": "DOCU", "hubspot": "HUBS", "atlassian": "TEAM",
    "zoom": "ZM", "doordash": "DASH", "instacart": "CART", "lyft": "LYFT",
    "draftkings": "DKNG", "roblox": "RBLX", "unity software": "U", "roku": "ROKU",
    "toast": "TOST", "duolingo": "DUOL", "reddit": "RDDT",
    "cvs": "CVS", "cvs health": "CVS", "walgreens": "WBA",
    "evercommerce": "EVCM", "chewy": "CHWY", "domo": "DOMO",
    "generac": "GNRC", "nano nuclear": "NNE",
    "blackstone secured": "BXSL", "bxsl": "BXSL",
    "target hospitality": "TH", "hims": "HIMS", "hims & hers": "HIMS",
    "carvana": "CVNA", "affirm": "AFRM", "upstart": "UPST",
    "lemonade": "LMND", "marqeta": "MQ", "bill.com": "BILL", "bill": "BILL",
    "samsara": "IOT", "c3.ai": "AI", "bigbear.ai": "BBAI",
    "soundhound": "SOUN", "archer": "ACHR", "joby": "JOBY",
    "super micro": "SMCI", "supermicro": "SMCI",
    "celsius": "CELH", "clorox": "CLX", "kraft": "KHC", "kraft heinz": "KHC",
    "general mills": "GIS", "kellogg": "K", "hershey": "HSY",
    "estee lauder": "EL", "ralph lauren": "RL", "tapestry": "TPR",
    "burlington": "BURL", "ross": "ROST", "tjx": "TJX",
    "constellation": "STZ", "molson": "TAP", "anheuser": "BUD",
    "vertex": "VRTX", "regeneron": "REGN", "gilead": "GILD",
    "biogen": "BIIB", "illumina": "ILMN", "intuitive": "ISRG",
    "dexcom": "DXCM", "edwards": "EW", "stryker": "SYK",
    "medtronic": "MDT", "boston scientific": "BSX", "abbott": "ABT",
    "thermo fisher": "TMO", "danaher": "DHR", "becton": "BDX",
    "progressive": "PGR", "allstate": "ALL", "travelers": "TRV",
    "chubb": "CB", "aon": "AON", "marsh": "MMC",
    "charles schwab": "SCHW", "schwab": "SCHW", "fidelity": "FNF",
    "t-mobile": "TMUS", "verizon": "VZ", "at&t": "T",
    # Additional mappings for U/D parsing
    "fedex": "FDX", "five below": "FIVE", "totalenergies": "TTE",
    "dollar tree": "DLTR", "semtech": "SMTC", "spyre": "SYRE",
    "gulfport": "GPOR", "gulfport energy": "GPOR",
    "waterbridge": "WTBR", "heartflow": "HFLO",
    "dakota gold": "DC", "atlas lithium": "ATLX",
    "cal-maine": "CALM", "cal-maine foods": "CALM",
    "koppers": "KOP", "weatherford": "WFRD",
    "first cash": "FCFS", "first cash financial": "FCFS",
    "willis lease": "WLFC", "eton": "ETON",
    "relmada": "RLMD", "trevi": "TRVI", "mcewan mining": "MUX",
    "arvinas": "ARVN", "bridgebio": "BBIO", "protagonist": "PTGX",
    "sailpoint": "SAIL", "edgewise": "EWTX",
    "darden": "DRI", "corning": "GLW",
    "jabil": "JBL", "lennar": "LEN",
    "lululemon": "LULU", "docusign": "DOCU",
    "academy sports": "ASO", "carmax": "KMX",
    "scholar rock": "SRRK", "archrock": "AROC",
    "crescent energy": "CRGY", "diamondback": "FANG",
    "diamondback energy": "FANG", "devon energy": "DVN",
    "dominion energy": "D", "cubesmart": "CUBE",
    "sherwin-williams": "SHW", "sherwin williams": "SHW",
    "rocket lab": "RKLB", "coreweave": "CRWV",
    "installed building": "IBP", "brightspring": "BTSG",
    "kinder morgan": "KMI", "entergy": "ETR",
    "zillow": "ZG", "monte rosa": "GLUE",
    "rhythm": "RYTM", "rhythm pharmaceuticals": "RYTM",
    "ardent health": "ARDT", "armada hoffler": "AHRT",
    "sequans": "SQNS", "usio": "USIO",
    "stoke therapeutics": "STOK", "bicycle therapeutics": "BCYC",
    "fastenal": "FAST", "dht holdings": "DHT", "topbuild": "BLD",
    "ovid": "OVID", "ovid therapeutics": "OVID",
    "larimar": "LRMR", "signet": "SIG", "signet jewelers": "SIG",
    "natural gas services": "NGS", "williams-sonoma": "WSM",
    "envela": "ELA", "h world": "HTHT", "jazz": "JAZZ",
    "jazz pharmaceuticals": "JAZZ",
    "funko": "FNKO", "sarepta": "SRPT", "xp inc": "XP",
    "ppl": "PPL", "newmark": "NMRK", "moelis": "MC",
    "invitation homes": "INVH", "cousins properties": "CUZ",
    "array technologies": "ARRY", "first solar": "FSLR",
}


def extract_ticker_from_name(text: str) -> str | None:
    """Try to find a stock ticker by matching company names in the text."""
    text_lower = text.lower()
    # Strip financial "target" phrases to avoid "target" → TGT false positives.
    # Preserves standalone "Target" (the company), e.g. "Target reports earnings".
    text_lower = re.sub(
        r'\bprice\s+target\b'
        r'|\btarget\s+price\b'
        r'|\btarget\s*(?:raised|lowered|cut|bumped|set|hiked|increased|decreased)\b'
        r'|\b(?:raises?|lowers?|cuts?|sets?|hikes?|increases?|decreases?)\s+(?:(?:stock|price)\s+)*target\b'
        r'|\btarget\s+(?:to|of|at|:)\s*\$',
        '', text_lower
    )
    # Try multi-word names first (longer matches are more specific)
    for name, ticker in sorted(COMPANY_TO_TICKER.items(), key=lambda x: -len(x[0])):
        # Use word boundary matching to avoid partial matches (e.g., "arm" in "warming")
        if re.search(r'\b' + re.escape(name) + r'\b', text_lower):
            return ticker
    return None


# Analyst firm names that should NOT be treated as stock subjects.
# These appear in titles as the FIRM doing the rating, not the company being rated.
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
    "hsbc", "ubs", "citi", "citigroup",
}


def _extract_ud_subject_ticker(title: str, summary: str) -> str:
    """Extract the stock ticker that is the SUBJECT of the upgrade/downgrade.

    Key insight: in "[Firm] upgrades [Subject]", text BEFORE the verb is the firm.
    In "[Subject] receives upgrade from [Firm]", text BEFORE receives is the subject.
    We must NOT return firm names (Goldman, BofA, etc.) as the subject ticker.
    """
    text = title + " " + summary

    # Pattern 0: Extract explicit parenthetical tickers like (AAPL), (NYSE:SMTC), (NASDAQ:RYTM)
    m = re.search(r'\((?:NYSE|NASDAQ|NYSEARCA)?:?([A-Z]{1,5})\)', title)
    if m:
        candidate = m.group(1)
        if candidate not in TICKER_EXCLUSIONS:
            return candidate

    # Pattern 0b: "[TICKER]: Firm raises/lowers..." or "[TICKER] Stock:" or "[TICKER] Analyst"
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
            # Try extracting ticker from the subject text
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

    # Pattern 3b: Skip "Reaches Analyst Target Price" — not a real U/D
    if re.search(r'(?:reaches?|hits?|crosses?)\s+(?:above\s+|below\s+)?(?:analyst\s+|average\s+)*(?:target\s*(?:price)?|price\s+target)', title, re.IGNORECASE):
        # These are "stock hits analyst price target" articles, not upgrades
        # Extract the company/ticker at start of title instead
        m = re.match(r'^([\w\.\s&-]+?)\s+(?:reaches?|hits?|crosses?)', title, re.IGNORECASE)
        if m:
            subj = m.group(1).strip()
            # Try as ticker first (e.g., "GSBD Crosses...")
            if subj.isupper() and len(subj) <= 5 and subj not in TICKER_EXCLUSIONS:
                return subj
            mapped = extract_ticker_from_name(subj)
            if mapped:
                return mapped

    # Pattern 4: "...on [TICKER/Company]..." or "...for [TICKER/Company]..."
    # But NOT "price target on" — skip if preceded by "target"
    m = re.search(r'(?<!target\s)\b(?:on|for)\s+([A-Z]{1,5})\b', title)
    if m:
        candidate = m.group(1)
        if candidate not in TICKER_EXCLUSIONS:
            return candidate

    # Pattern 5: Try company name mapping — but SKIP firm names
    action_split = re.split(r'\b(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?|raises?|lowers?|cuts?)\b', title, maxsplit=1, flags=re.IGNORECASE)
    if len(action_split) == 2:
        after_verb = action_split[1]
        # Remove ALL forms of "target" to avoid "target" → TGT
        clean = re.sub(r'\btarget\s+price\b|\b(?:stock\s+)?(?:price\s+)?target\b', '', after_verb, flags=re.IGNORECASE)
        mapped = extract_ticker_from_name(clean)
        if mapped:
            return mapped
    # Fallback: try full title but exclude known firm names and all forms of "target"
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

    # Pattern 6: Try regex tickers from title — but filter out "TARGET" false positives
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


def _extract_ud_firm(title: str, summary: str, subject_ticker: str) -> str:
    """Extract the analyst firm from a U/D headline.

    Avoids confusing the stock subject with the firm name.
    """
    # Known analyst firms to look for
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
    text = title + " " + summary
    text_lower = text.lower()

    # Check for known firm names
    for firm in sorted(KNOWN_FIRMS, key=len, reverse=True):
        if firm.lower() in text_lower:
            return firm

    # Try regex patterns to extract firm
    firm_patterns = [
        # "Goldman upgrades AAPL" / "BofA Securities reiterates..."
        r'^([\w\.\s&]+?)\s+(?:upgrades?|downgrades?|initiates?|reiterates?|maintains?|raises?|lowers?|cuts?)\s',
        # "...upgraded by Goldman" / "...at Morgan Stanley"
        r'(?:upgraded|downgraded|initiated|reiterated)\s+(?:by|at)\s+([\w\.\s&]+?)(?:\s*[,;:\-\(]|$)',
        # "after Morgan Stanley upgrades"
        r'after\s+([\w\.\s&]+?)\s+(?:upgrades?|downgrades?)',
    ]
    # Resolve subject_ticker back to company name to exclude it
    subject_names = set()
    for name, ticker in COMPANY_TO_TICKER.items():
        if ticker == subject_ticker:
            subject_names.add(name.lower())
    subject_names.add(subject_ticker.lower())

    # Words that should never appear in a firm name
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
            # Reject candidates containing common noise words
            if any(nw in cand_lower for nw in noise_words):
                continue
            return candidate

    return ""

CATEGORY_KEYWORDS = {
    Category.EARNINGS: [
        "earnings", "eps", "revenue", "quarterly results", "beats estimates",
        "misses estimates", "quarterly report", "fiscal quarter", "guidance",
        "profit", "loss report", "income report",
    ],
    Category.UPGRADE: [
        "upgrade", "upgrades", "upgraded",
        "raised to buy", "raised to overweight", "raised to outperform",
        "raises price target", "raises target", "raised target",
        "raises stock price target", "stock price target to",
        "price target raised", "target raised", "target bumped",
        "initiates coverage", "initiates with buy", "initiates with overweight",
        "initiated with buy", "initiated with overweight",
        "maintains buy", "maintains overweight", "maintains outperform",
        "reiterates buy", "reiterates overweight", "reiterates outperform",
        "reiterates stock rating at buy",
        "reiterates stock rating", "reiterates stock",
        "stock rating, holds",
        "receives a buy", "receives an upgrade",
        "overweight rating", "outperform rating", "buy rating",
        "top analyst calls",
        "analyst upgrades", "sa analyst upgrades",
    ],
    Category.DOWNGRADE: [
        "downgrade", "downgrades", "downgraded",
        "cut to sell", "cut to underweight", "cut to underperform",
        "lowers price target", "lowers target", "lowered target",
        "price target lowered", "target lowered", "target cut",
        "cuts stock price target", "stock price target cut",
        "initiates with sell", "initiates with underweight",
        "initiated with sell", "initiated with underweight",
        "maintains sell", "maintains underweight", "maintains underperform",
        "reiterates sell", "reiterates underweight", "reiterates underperform",
        "receives a downgrade", "receives a sell",
        "underweight rating", "underperform rating", "sell rating",
        "analyst downgrades", "sa analyst downgrades",
    ],
    Category.MACRO: [
        "fed ", "federal reserve", "interest rate", "inflation", "cpi",
        "ppi", "gdp", "jobs report", "unemployment", "fomc", "powell",
        "treasury", "yield", "economic data", "nonfarm", "rate cut",
        "rate hike", "monetary policy",
    ],
    Category.FDA: [
        "fda", "drug approval", "clinical trial", "phase 3", "phase 2",
        "pdufa", "biologic", "therapeutic",
    ],
    Category.MA: [
        "acquire", "acquisition", "merger", "buyout", "takeover",
        "deal to buy", "bid for", "merge with",
    ],
    Category.IPO: [
        "ipo", "initial public offering", "direct listing", "spac",
        "goes public", "debut",
    ],
    Category.INSIDER: [
        "insider", "insider buying", "insider selling", "form 4",
        "officer buys", "director sells",
    ],
    Category.DIVIDEND: [
        "dividend", "ex-dividend", "payout", "distribution",
        "special dividend",
    ],
    Category.FILING: [
        "8-k", "10-k", "10-q", "sec filing", "13f", "13d", "proxy statement",
    ],
    Category.CRYPTO: [
        "bitcoin", "ethereum", "cryptocurrency", "crypto market",
        "crypto currency", "blockchain", "defi", "altcoin", "stablecoin",
    ],
}


def extract_tickers(text: str) -> list[str]:
    matches = TICKER_PATTERN.findall(text)
    tickers, seen = [], set()
    for m in matches:
        if m not in TICKER_EXCLUSIONS and m not in seen:
            tickers.append(m)
            seen.add(m)
    return tickers[:10]


def _detect_ud_action(title: str, summary: str) -> str | None:
    """Detect upgrade/downgrade action with context-aware logic.

    Instead of just checking if 'upgrade'/'downgrade' appear anywhere,
    analyze the sentence structure to determine the actual action.
    """
    text_lower = (title + " " + summary).lower()
    title_lower = title.lower()

    # Skip generic aggregator titles that list both (e.g., "SA analyst upgrades and downgrades")
    generic_patterns = [
        r'\bupgrades?\s+(?:and|&|/)\s+downgrades?\b',
        r'\bdowngrades?\s+(?:and|&|/)\s+upgrades?\b',
        r'\banalyst\s+(?:upgrades?\s+(?:and|&|/)\s+downgrades?|ratings?)\b',
        r'\bstock\s+upgrades?\s+(?:and|&|/)\s+downgrades?\b',
    ]
    is_generic = any(re.search(p, title_lower) for p in generic_patterns)

    if is_generic:
        specific_up = re.search(r'\b(?:receives?|gets?|given)\s+(?:an?\s+)?(?:upgrade|buy|overweight|outperform)\b', text_lower)
        specific_dn = re.search(r'\b(?:receives?|gets?|given)\s+(?:an?\s+)?(?:downgrade|sell|underweight|underperform)\b', text_lower)
        if specific_up and not specific_dn:
            return "upgrade"
        if specific_dn and not specific_up:
            return "downgrade"
        return "mixed"

    upgrade_verbs = [
        r'\bupgrades?\b', r'\bupgraded\b',
        r'\braised\s+to\s+(?:buy|overweight|outperform)\b',
        r'\braises?\s+(?:price\s+)?target\b', r'\btarget\s+raised\b',
        r'\binitiates?\s+(?:with\s+)?(?:buy|overweight|outperform)\b',
        r'\binitiated\s+(?:with\s+)?(?:buy|overweight|outperform)\b',
        r'\breceives?\s+(?:an?\s+)?upgrade\b',
        r'\bgets?\s+(?:an?\s+)?upgrade\b',
        r'\bbuy\s+rating\b', r'\boverweight\s+rating\b', r'\boutperform\s+rating\b',
    ]
    downgrade_verbs = [
        r'\bdowngrades?\b', r'\bdowngraded\b',
        r'\bcut\s+to\s+(?:sell|underweight|underperform|hold|neutral)\b',
        r'\blowers?\s+(?:price\s+)?target\b', r'\btarget\s+(?:lowered|cut)\b',
        r'\binitiates?\s+(?:with\s+)?(?:sell|underweight|underperform)\b',
        r'\binitiated\s+(?:with\s+)?(?:sell|underweight|underperform)\b',
        r'\breceives?\s+(?:an?\s+)?downgrade\b',
        r'\bgets?\s+(?:an?\s+)?downgrade\b',
        r'\bsell\s+rating\b', r'\bunderweight\s+rating\b', r'\bunderperform\s+rating\b',
    ]

    has_up = any(re.search(p, title_lower) for p in upgrade_verbs)
    has_dn = any(re.search(p, title_lower) for p in downgrade_verbs)

    if has_up and not has_dn:
        return "upgrade"
    if has_dn and not has_up:
        return "downgrade"
    if has_up and has_dn:
        return "mixed"

    # Fall back to summary
    has_up_s = any(re.search(p, text_lower) for p in upgrade_verbs)
    has_dn_s = any(re.search(p, text_lower) for p in downgrade_verbs)

    if has_up_s and not has_dn_s:
        return "upgrade"
    if has_dn_s and not has_up_s:
        return "downgrade"
    if has_up_s and has_dn_s:
        return "mixed"

    if re.search(r'\binitiat(?:es?|ed)\b', text_lower):
        return "initiated"
    if re.search(r'\b(?:reiterates?|maintains?)\b', text_lower):
        return "reiterated"
    if re.search(r'\braises?\b.*\b(?:target|price)\b', text_lower):
        return "upgrade"
    if re.search(r'\blowers?\b.*\b(?:target|price)\b', text_lower):
        return "downgrade"
    if re.search(r'\b(?:overweight|outperform|buy)\s+rating\b', text_lower):
        return "upgrade"
    if re.search(r'\b(?:underweight|underperform|sell)\s+rating\b', text_lower):
        return "downgrade"

    return None


def _kw_match(text: str, keyword: str) -> bool:
    """Match keyword with word boundaries for short keywords to avoid false positives."""
    if len(keyword) <= 4:
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
    return keyword in text


def categorize(title: str, summary: str, feed_category: str) -> Category:
    text = (title + " " + summary).lower()
    # Feed-level overrides
    if feed_category == "upgrades_downgrades":
        action = _detect_ud_action(title, summary)
        if action in ("downgrade", "lowers_pt"):
            return Category.DOWNGRADE
        if action in ("upgrade", "initiated", "raises_pt"):
            return Category.UPGRADE
        # For mixed/other, still categorize as upgrade so it shows in U/D tab
        return Category.UPGRADE
    if feed_category == "fda":
        return Category.FDA
    if feed_category == "filings":
        return Category.FILING
    if feed_category == "earnings":
        return Category.EARNINGS
    # Check UPGRADE/DOWNGRADE first (higher priority than other categories)
    has_up = any(_kw_match(text, kw) for kw in CATEGORY_KEYWORDS[Category.UPGRADE])
    has_dn = any(_kw_match(text, kw) for kw in CATEGORY_KEYWORDS[Category.DOWNGRADE])
    if has_up and has_dn:
        return Category.UPGRADE  # Mixed articles show under upgrades
    if has_dn:
        return Category.DOWNGRADE
    if has_up:
        return Category.UPGRADE
    # Then other categories
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if cat in (Category.UPGRADE, Category.DOWNGRADE):
            continue  # already checked
        if any(_kw_match(text, kw) for kw in keywords):
            return cat
    return Category.GENERAL


def parse_published_date(entry: dict) -> datetime:
    for date_field in ("published", "updated", "created"):
        raw = entry.get(date_field, "")
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except (ValueError, TypeError):
                pass
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
    return datetime.now(timezone.utc)


def clean_html(raw: str) -> str:
    if not raw:
        return ""
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)[:500]


def _entry_id(feed: Feed, url: str, title: str, summary: str) -> str:
    """Stable per-item id.

    URL alone is not unique on structured feeds — every Nasdaq halt links to the
    same page, and an untitled item would collapse into one row. Those feeds key
    off the item's own text instead, which stays deterministic across refreshes.
    """
    if url and "halt" not in feed.name.lower():
        return hashlib.md5(url.encode()).hexdigest()
    return hashlib.md5(f"{feed.name}|{title}|{summary[:120]}".encode()).hexdigest()


def parse_entry(entry: dict, feed: Feed) -> Article:
    title = entry.get("title", "No title")
    url = entry.get("link", "")
    summary = clean_html(entry.get("summary", entry.get("description", "")))
    published = parse_published_date(entry)
    category = categorize(title, summary, feed.category)
    tickers = extract_tickers(title + " " + summary)
    # Aggregators link to the original publisher, so an item may name its own
    # source. Crediting Reuters rather than the aggregator is what lets source
    # authority scoring mean anything.
    source = entry.get("_source") or feed.name
    return Article(
        id=_entry_id(feed, url, title, summary),
        title=title, url=url, source=source,
        published=published, category=category,
        tickers=tickers, summary=summary,
        ticker_hint=entry.get("_ticker_hint", ""),
    )


def parse_upgrade_downgrade(article: Article) -> UpgradeDowngrade | None:
    text = article.title + " " + article.summary
    text_lower = text.lower()

    action = _detect_ud_action(article.title, article.summary)
    if action is None:
        return None

    # Extract the SUBJECT ticker (the stock being upgraded/downgraded)
    ticker = _extract_ud_subject_ticker(article.title, article.summary)

    # Extract the analyst firm (separate from the subject)
    firm = _extract_ud_firm(article.title, article.summary, ticker)

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

    return UpgradeDowngrade(
        ticker=ticker, firm=firm, action=action,
        old_rating=old_rating, new_rating=new_rating,
        price_target=price_target, published=article.published,
        source_url=article.url, source=article.source,
    )


# ══════════════════════════════════════════════════════════════════════
#  Database — SQLite cache
# ══════════════════════════════════════════════════════════════════════

DB_DIR = ROOT / "data"
DB_PATH = DB_DIR / "newsagent.db"


def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
            source TEXT NOT NULL, published TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tickers TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL,
            ticker_hint TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS upgrades_downgrades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL, firm TEXT NOT NULL, action TEXT NOT NULL,
            old_rating TEXT DEFAULT '', new_rating TEXT DEFAULT '',
            price_target TEXT DEFAULT '', published TEXT NOT NULL,
            source_url TEXT DEFAULT '', source TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS custom_feeds (
            name TEXT PRIMARY KEY, url TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS discord_routes (
            category TEXT PRIMARY KEY,
            webhook_url TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            fail_count INTEGER NOT NULL DEFAULT 0,
            disabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS discord_sent (
            article_id TEXT PRIMARY KEY,
            category TEXT,
            sent_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published DESC);
        CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
        CREATE INDEX IF NOT EXISTS idx_ud_published ON upgrades_downgrades(published DESC);
        CREATE INDEX IF NOT EXISTS idx_discord_sent_at ON discord_sent(sent_at DESC);
    """)
    _add_missing_columns(conn, "articles", {"ticker_hint": "TEXT NOT NULL DEFAULT ''"})
    init_catalyst_tables(conn)
    conn.commit()


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Additive migration for databases created before a column existed."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, spec in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")
            logger.info("migrated %s: added column %s", table, name)


def prune_old_articles(conn: sqlite3.Connection, days: int = 7) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn.execute("DELETE FROM articles WHERE published < ?", (cutoff,))
    conn.execute("DELETE FROM upgrades_downgrades WHERE published < ?", (cutoff,))
    conn.commit()


# ── Discord routes (per-category webhook config; the backend service delivers) ──

# Hex colors mirror models.CATEGORY_COLORS so a test embed matches the UI badge.
_DISCORD_COLORS = {
    "general": 0x9E9E9E, "earnings": 0xFFD700, "upgrade": 0x00C853,
    "downgrade": 0xFF1744, "macro": 0x2979FF, "fda": 0xAA00FF,
    "m&a": 0xFF9100, "ipo": 0x00E5FF, "insider": 0xFF6D00,
    "dividend": 0x76FF03, "filing": 0x8D6E63, "crypto": 0xF4511E,
    "tech": 0x7C4DFF,
}


def get_discord_routes(conn) -> dict[str, dict]:
    return {r["category"]: dict(r) for r in conn.execute("SELECT * FROM discord_routes").fetchall()}


def save_discord_route(conn, category: str, webhook_url: str, enabled: bool = True) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO discord_routes (category, webhook_url, enabled, fail_count, disabled, updated_at) "
        "VALUES (?, ?, ?, 0, 0, ?)",
        (category, webhook_url.strip(), int(enabled), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def set_discord_route_enabled(conn, category: str, enabled: bool) -> None:
    conn.execute("UPDATE discord_routes SET enabled = ? WHERE category = ?", (int(enabled), category))
    conn.commit()


def delete_discord_route(conn, category: str) -> None:
    conn.execute("DELETE FROM discord_routes WHERE category = ?", (category,))
    conn.commit()


def discord_test_send(webhook_url: str, category: str = "general") -> tuple[bool, str]:
    """Synchronously POST a test embed so the user can confirm a webhook works."""
    color = _DISCORD_COLORS.get(category, _DISCORD_COLORS["general"])
    payload = {
        "username": "NewsAgent Squawk",
        "embeds": [{
            "title": f"✅ NewsAgent connected — {category}",
            "description": "This channel will now receive NewsAgent market news for this category.",
            "color": color,
        }],
    }
    try:
        resp = httpx.post(webhook_url.strip(), json=payload, timeout=10)
        if resp.status_code in (200, 204):
            return True, "Test message delivered"
        if resp.status_code in (401, 404):
            return False, f"Invalid or deleted webhook ({resp.status_code})"
        if resp.status_code == 429:
            return False, "Rate limited (429) — try again shortly"
        return False, f"Discord returned {resp.status_code}"
    except Exception as e:
        return False, str(e)[:120]


def insert_article(conn: sqlite3.Connection, article: Article) -> bool:
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO articles (id,title,url,source,published,category,tickers,summary,fetched_at,ticker_hint) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (article.id, article.title, article.url, article.source,
             article.published.isoformat(), article.category.value,
             json.dumps(article.tickers), article.summary, article.fetched_at.isoformat(),
             article.ticker_hint),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.IntegrityError:
        return False


def insert_upgrade_downgrade(conn: sqlite3.Connection, ud: UpgradeDowngrade) -> None:
    # Deduplicate by ticker+firm+action+published date
    exists = conn.execute(
        "SELECT 1 FROM upgrades_downgrades WHERE ticker=? AND firm=? AND action=? AND published LIKE ?",
        (ud.ticker, ud.firm, ud.action, ud.published.strftime("%Y-%m-%d") + "%"),
    ).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO upgrades_downgrades (ticker,firm,action,old_rating,new_rating,price_target,published,source_url,source) VALUES (?,?,?,?,?,?,?,?,?)",
        (ud.ticker, ud.firm, ud.action, ud.old_rating, ud.new_rating,
         ud.price_target, ud.published.isoformat(), ud.source_url, ud.source),
    )
    conn.commit()


def _parse_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def get_articles(conn, limit=100, category=None, ticker=None, search=None, hours=48) -> list[Article]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q, p = "SELECT * FROM articles WHERE published >= ?", [cutoff]
    if category and category != "all":
        q += " AND category = ?"; p.append(category)
    if ticker:
        q += " AND tickers LIKE ?"; p.append(f'%"{ticker}"%')
    if search:
        s = search.strip()
        q += " AND (title LIKE ? OR summary LIKE ? OR tickers LIKE ? COLLATE NOCASE)"
        p.extend([f"%{s}%", f"%{s}%", f'%"{s.upper()}"%'])
    q += " ORDER BY published DESC LIMIT ?"; p.append(limit)
    rows = conn.execute(q, p).fetchall()
    return [Article(
        id=r["id"], title=r["title"], url=r["url"], source=r["source"],
        published=_parse_dt(r["published"]),
        category=Category(r["category"]) if r["category"] in Category._value2member_map_ else Category.GENERAL,
        tickers=json.loads(r["tickers"]), summary=r["summary"],
        fetched_at=_parse_dt(r["fetched_at"]),
    ) for r in rows]


def get_upgrades_downgrades(conn, limit=100, ticker=None, search=None, hours=48) -> list[UpgradeDowngrade]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q, p = "SELECT * FROM upgrades_downgrades WHERE published >= ?", [cutoff]
    if ticker:
        q += " AND ticker = ?"; p.append(ticker.upper())
    if search:
        s = search.strip()
        q += " AND (ticker LIKE ? OR firm LIKE ? OR action LIKE ? COLLATE NOCASE)"
        p.extend([f"%{s}%", f"%{s}%", f"%{s}%"])
    q += " ORDER BY published DESC LIMIT ?"; p.append(limit)
    return [UpgradeDowngrade(
        ticker=r["ticker"], firm=r["firm"], action=r["action"],
        old_rating=r["old_rating"], new_rating=r["new_rating"],
        price_target=r["price_target"], published=_parse_dt(r["published"]),
        source_url=r["source_url"], source=r["source"],
    ) for r in conn.execute(q, p).fetchall()]


def reprocess_upgrades_downgrades(conn: sqlite3.Connection) -> int:
    """Re-parse all upgrade/downgrade articles with the improved parser."""
    conn.execute("DELETE FROM upgrades_downgrades")
    conn.commit()
    articles = get_articles(conn, limit=1000, category="upgrade")
    articles += get_articles(conn, limit=1000, category="downgrade")
    count = 0
    for article in articles:
        ud = parse_upgrade_downgrade(article)
        if ud and ud.ticker != "N/A":
            insert_upgrade_downgrade(conn, ud)
            count += 1
    # Also reprocess general articles from U/D feeds
    all_arts = get_articles(conn, limit=2000)
    for article in all_arts:
        if article.category.value in ("upgrade", "downgrade"):
            continue  # already processed
        ud = parse_upgrade_downgrade(article)
        if ud and ud.ticker != "N/A":
            insert_upgrade_downgrade(conn, ud)
            count += 1
    return count


def get_article_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) as c FROM articles").fetchone()["c"]


def get_source_counts(conn) -> dict[str, int]:
    return {r["source"]: r["c"] for r in conn.execute(
        "SELECT source, COUNT(*) as c FROM articles GROUP BY source ORDER BY c DESC"
    ).fetchall()}


def get_articles_by_ticker(conn, limit_per_ticker: int = 10) -> dict[str, list[Article]]:
    """Get recent articles grouped by ticker symbol."""
    rows = conn.execute(
        "SELECT * FROM articles WHERE tickers != '[]' ORDER BY published DESC LIMIT 2000"
    ).fetchall()
    by_ticker: dict[str, list[Article]] = {}
    for r in rows:
        art = Article(
            id=r["id"], title=r["title"], url=r["url"], source=r["source"],
            published=_parse_dt(r["published"]),
            category=Category(r["category"]) if r["category"] in Category._value2member_map_ else Category.GENERAL,
            tickers=json.loads(r["tickers"]), summary=r["summary"],
            fetched_at=_parse_dt(r["fetched_at"]),
        )
        for t in art.tickers[:3]:
            if t not in TICKER_EXCLUSIONS:
                if t not in by_ticker:
                    by_ticker[t] = []
                if len(by_ticker[t]) < limit_per_ticker:
                    by_ticker[t].append(art)
    return dict(sorted(by_ticker.items(), key=lambda x: -len(x[1])))


def get_all_tickers(conn) -> list[str]:
    """Get all unique tickers from articles, sorted by frequency."""
    rows = conn.execute(
        "SELECT tickers FROM articles WHERE tickers != '[]' ORDER BY published DESC LIMIT 5000"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        for t in json.loads(r["tickers"]):
            if t not in TICKER_EXCLUSIONS:
                counts[t] = counts.get(t, 0) + 1
    return sorted(counts.keys(), key=lambda t: -counts[t])


def save_custom_feed(conn, name, url, category, enabled):
    conn.execute("INSERT OR REPLACE INTO custom_feeds (name,url,category,enabled) VALUES (?,?,?,?)",
                 (name, url, category, int(enabled)))
    conn.commit()


def get_custom_feeds(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM custom_feeds").fetchall()]


def delete_custom_feed(conn, name):
    conn.execute("DELETE FROM custom_feeds WHERE name = ?", (name,))
    conn.commit()


def toggle_custom_feed(conn, name, enabled):
    conn.execute("UPDATE custom_feeds SET enabled = ? WHERE name = ?", (int(enabled), name))
    conn.commit()


# ══════════════════════════════════════════════════════════════════════
#  Feed management
# ══════════════════════════════════════════════════════════════════════

def load_default_feeds() -> list[Feed]:
    path = ROOT / "config" / "default_feeds.toml"
    if not path.exists():
        return []
    data = toml.load(str(path))
    return [Feed(name=f["name"], url=f["url"], category=f.get("category", "general"),
                 enabled=f.get("enabled", True)) for f in data.get("feeds", [])]


def load_custom_feeds_from_db() -> list[Feed]:
    conn = get_connection(); init_db(conn)
    rows = get_custom_feeds(conn); conn.close()
    return [Feed(name=r["name"], url=r["url"], category=r.get("category", "general"),
                 enabled=bool(r.get("enabled", 1))) for r in rows]


def load_all_feeds() -> list[Feed]:
    return load_default_feeds() + load_custom_feeds_from_db()


def load_settings() -> dict:
    path = ROOT / "config" / "settings.toml"
    if not path.exists():
        return {"general": {"refresh_interval": 15, "max_articles": 500, "prune_after_days": 7}}
    return toml.load(str(path))


# ══════════════════════════════════════════════════════════════════════
#  Fetcher — RSS engine + background refresh thread
# ══════════════════════════════════════════════════════════════════════

_fetch_lock = threading.Lock()
_last_fetch_time: datetime | None = None
_fetch_errors: dict[str, str] = {}


def get_last_fetch_time() -> datetime | None:
    return _last_fetch_time


def get_fetch_errors() -> dict[str, str]:
    return dict(_fetch_errors)


# SEC rejects terse or browser-spoofing agents with a 403; it wants a
# descriptive string identifying the requester.
SEC_USER_AGENT = "NewsAgent/1.0 (open-source market news aggregator; contact via repo)"
DEFAULT_USER_AGENT = "NewsAgent/1.0"


def feed_user_agent(url: str) -> str:
    return SEC_USER_AGENT if "sec.gov" in url else DEFAULT_USER_AGENT


def _items_to_entries(items) -> list[dict]:
    """Adapt NewsItem objects to the entry shape `parse_entry` consumes."""
    return [
        {
            "title": i.title, "link": i.url, "summary": i.summary,
            "published": i.published.isoformat(),
            "_source": i.source, "_ticker_hint": i.ticker_hint,
        }
        for i in items
    ]


def fetch_feed(feed: Feed, timeout: float = 20.0) -> list[dict]:
    # Sources without a feed get a purpose-built adapter but the same interface.
    if "finviz" in feed.name.lower():
        try:
            entries = _items_to_entries(sources_mod.fetch_finviz_news(limit=100))
            if entries:
                _fetch_errors.pop(feed.name, None)
            return entries
        except Exception as e:
            _fetch_errors[feed.name] = str(e)[:200]
            logger.warning(f"Error fetching {feed.name}: {str(e)[:100]}")
            return []
    try:
        headers = {
            "User-Agent": feed_user_agent(feed.url),
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(feed.url, headers=headers)
            resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Parse error: {parsed.bozo_exception}")
        _fetch_errors.pop(feed.name, None)
        return parsed.entries
    except Exception as e:
        _fetch_errors[feed.name] = str(e)[:200]
        logger.warning(f"Error fetching {feed.name}: {str(e)[:100]}")
        return []


# ══════════════════════════════════════════════════════════════════════
#  Catalyst engine wiring
# ══════════════════════════════════════════════════════════════════════

# Grok reads X, where a halt or a leak often surfaces before any wire carries
# it. Off unless XAI_API_KEY is set; the interval keeps the spend bounded.
GROK_SQUAWK_ENABLED = os.getenv("GROK_SQUAWK_ENABLED", "true").lower() in ("1", "true", "yes")
GROK_SQUAWK_INTERVAL = float(os.getenv("GROK_SQUAWK_INTERVAL", "120"))
GROK_SQUAWK_WINDOW_MINUTES = int(os.getenv("GROK_SQUAWK_WINDOW_MINUTES", "30"))
# Per-ticker fan-out is heavier than a feed poll, so it runs on its own cadence.
TICKER_FANOUT_INTERVAL = float(os.getenv("TICKER_FANOUT_INTERVAL", "90"))
TICKER_FANOUT_MAX = int(os.getenv("TICKER_FANOUT_MAX", "10"))


def store_news_items(items, feed_name: str, category: str = "general") -> int:
    """Persist NewsItems from a non-RSS source. Returns how many were new."""
    if not items:
        return 0
    pseudo_feed = Feed(name=feed_name, url="", category=category, enabled=True)
    conn = get_connection()
    try:
        init_db(conn)
        stored = 0
        for entry in _items_to_entries(items):
            try:
                if insert_article(conn, parse_entry(entry, pseudo_feed)):
                    stored += 1
            except Exception as exc:
                logger.debug("could not store item from %s: %s", feed_name, exc)
        return stored
    finally:
        conn.close()


def focus_tickers(limit: int = TICKER_FANOUT_MAX) -> list[str]:
    """Which symbols deserve a dedicated sweep right now.

    Watchlist first — those are the ones the user is actually trading — then the
    tickers already carrying the highest-scoring catalysts, since a live story
    is exactly where extra sourcing pays off.
    """
    picks: list[str] = []
    try:
        # Reachable only from a Streamlit script run; the refresher thread has
        # no session context, and falls through to the catalyst board instead.
        watchlist = st.session_state.get("watchlist", []) or []
    except Exception:
        watchlist = []
    for ticker in watchlist:
        if ticker and ticker not in picks:
            picks.append(ticker)
    if len(picks) < limit:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ticker FROM catalysts WHERE ticker != '' AND published >= ? "
                "ORDER BY score DESC LIMIT ?",
                ((datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(), limit * 2),
            ).fetchall()
            for row in rows:
                if row[0] not in picks:
                    picks.append(row[0])
                if len(picks) >= limit:
                    break
        except Exception as exc:
            logger.debug("focus ticker lookup failed: %s", exc)
        finally:
            conn.close()
    return picks[:limit]


_catalyst_engine: CatalystEngine | None = None
_catalyst_lock = threading.Lock()
_last_catalyst_run: datetime | None = None
_last_catalyst_counts: tuple[int, int] = (0, 0)

# Company aliases the SEC file spells differently from the newswires.
CATALYST_NAME_ALIASES = dict(COMPANY_TO_TICKER)


def get_catalyst_engine() -> CatalystEngine:
    """Lazily build the engine; the SEC ticker universe loads once per process."""
    global _catalyst_engine
    if _catalyst_engine is None:
        with _catalyst_lock:
            if _catalyst_engine is None:
                _catalyst_engine = CatalystEngine(DB_DIR, extra_names=CATALYST_NAME_ALIASES)
    return _catalyst_engine


def refresh_catalysts(hours: float = 48, with_quotes: bool = True) -> tuple[int, int]:
    """Re-derive catalysts from the cached articles and persist the ranking.

    Runs after each feed fetch. Quotes are attached only for the top-ranked
    tickers so a refresh costs a bounded number of requests regardless of how
    much news arrived.
    """
    global _last_catalyst_run, _last_catalyst_counts
    conn = get_connection()
    try:
        init_catalyst_tables(conn)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = conn.execute(
            "SELECT id, title, summary, source, url, published, ticker_hint FROM articles "
            "WHERE published >= ? ORDER BY published DESC LIMIT 2000",
            (cutoff,),
        ).fetchall()
        articles = [
            {"id": r[0], "title": r[1], "summary": r[2], "source": r[3], "url": r[4],
             "published": r[5], "ticker_hint": r[6]}
            for r in rows
        ]
        catalysts = get_catalyst_engine().run(articles, with_quotes=with_quotes)
        counts = upsert_catalysts(conn, catalysts)
        # Keep the board equal to this scan's output — see prune_stale_catalysts.
        prune_stale_catalysts(conn, [c.id for c in catalysts], hours)
        _last_catalyst_run = datetime.now(timezone.utc)
        _last_catalyst_counts = counts
        return counts
    except Exception as exc:
        logger.warning("catalyst refresh failed: %s", exc)
        return (0, 0)
    finally:
        conn.close()


def get_last_catalyst_run() -> datetime | None:
    return _last_catalyst_run


# Feeds are fetched concurrently: sequentially, one slow wire (or a 20s timeout)
# would stretch a cycle past the refresh interval and the refresher would hold
# the fetch lock permanently, starving the UI thread that renders the first page.
FETCH_WORKERS = 8


def fetch_all_feeds(feeds: list[Feed], blocking: bool = True) -> int:
    """Fetch every enabled feed and store new articles. Returns the new count.

    With `blocking=False` a fetch already in flight is left to finish rather
    than queueing a second one behind it.
    """
    global _last_fetch_time
    if not _fetch_lock.acquire(blocking=blocking):
        return 0
    try:
        enabled = [f for f in feeds if f.enabled]
        with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, max(1, len(enabled)))) as pool:
            fetched = list(zip(enabled, pool.map(fetch_feed, enabled)))

        conn = get_connection(); init_db(conn); new_count = 0
        for feed, entries in fetched:
            for entry in entries:
                try:
                    article = parse_entry(entry, feed)
                    if insert_article(conn, article):
                        new_count += 1
                        # Parse U/D from articles categorized as upgrade/downgrade,
                        # or from feeds that are specifically for analyst ratings
                        if article.category.value in ("upgrade", "downgrade") or feed.category == "upgrades_downgrades":
                            ud = parse_upgrade_downgrade(article)
                            if ud and ud.ticker != "N/A":
                                insert_upgrade_downgrade(conn, ud)
                except Exception as e:
                    logger.warning(f"Parse error from {feed.name}: {e}")
            feed.last_fetched = datetime.now(timezone.utc)
        conn.close()
        _last_fetch_time = datetime.now(timezone.utc)
        return new_count
    finally:
        _fetch_lock.release()


class FeedRefresher:
    """Tiered background refresh.

    Sources are not equally fast. The wires, SEC and the halt tape are where
    catalysts originate; general market news mostly re-reports them minutes
    later. Polling everything on one interval makes the fast sources queue
    behind the slow ones, so each tier runs at its own cadence and only the
    tiers that are due are fetched on a given pass.
    """

    def __init__(self, feeds: list[Feed], interval: int = 15):
        self.feeds = feeds
        self.interval = interval
        self._running = False
        self._scheduler = fanout_mod.TieredScheduler()
        self._last_grok = 0.0
        self._last_ticker_fanout = 0.0

    def start(self):
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._running = False

    def _feeds_for(self, tiers) -> list[Feed]:
        wanted = set(tiers)
        return [f for f in self.feeds if fanout_mod.tier_for(f.name, f.category) in wanted]

    def _run(self):
        while self._running:
            try:
                due = self._scheduler.due()
                if due:
                    batch = self._feeds_for(due)
                    new = fetch_all_feeds(batch, blocking=False) if batch else 0
                    for tier in due:
                        self._scheduler.mark(tier)
                    if new > 0:
                        names = "+".join(t.value for t in due)
                        logger.info(f"Fetched {new} new articles ({names})")

                self._maybe_grok_squawk()
                self._maybe_ticker_fanout()

                # Rescore every cycle, not only when articles arrive: recency
                # decays and quotes go stale even on a quiet feed.
                fresh, updated = refresh_catalysts()
                if fresh:
                    logger.info(f"Detected {fresh} new catalysts ({updated} rescored)")
            except Exception as e:
                logger.error(f"Refresh error: {e}")
            time.sleep(max(2.0, min(self.interval, self._scheduler.seconds_until_next())))

    def _maybe_grok_squawk(self) -> None:
        """Pull breaking events off X. Skipped entirely without an API key."""
        if not GROK_SQUAWK_ENABLED or not grok_mod.available():
            return
        if time.monotonic() - self._last_grok < GROK_SQUAWK_INTERVAL:
            return
        self._last_grok = time.monotonic()
        try:
            items = grok_mod.fetch_squawk(minutes=GROK_SQUAWK_WINDOW_MINUTES)
            if items:
                stored = store_news_items(items, "Grok Squawk", "general")
                if stored:
                    logger.info(f"Grok squawk: {stored} new events from X")
        except Exception as e:
            logger.warning(f"Grok squawk failed: {e}")

    def _maybe_ticker_fanout(self) -> None:
        """Pull every angle on the symbols that currently matter."""
        if time.monotonic() - self._last_ticker_fanout < TICKER_FANOUT_INTERVAL:
            return
        self._last_ticker_fanout = time.monotonic()
        try:
            tickers = focus_tickers()
            if not tickers:
                return
            items = fanout_mod.fanout_tickers(tickers, limit_per_source=15)
            stored = store_news_items(items, "Ticker Fan-out", "general")
            if stored:
                logger.info(f"Fan-out over {len(tickers)} tickers: {stored} new items")
        except Exception as e:
            logger.warning(f"Ticker fan-out failed: {e}")

    def update_feeds(self, feeds):
        self.feeds = feeds


# ══════════════════════════════════════════════════════════════════════
#  UI — CSS + Components
# ══════════════════════════════════════════════════════════════════════

DARK_CSS = """
<style>
    /* ═══════════════════════════════════════════════════════════════
       NewsAgent Premium Dark Theme — Bloomberg-inspired terminal UI
       ═══════════════════════════════════════════════════════════════ */

    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

    :root {
        --bg-primary: #07080a;
        --bg-secondary: #0c0d10;
        --bg-elevated: #111318;
        --bg-hover: #161820;
        --border-subtle: #1c1e26;
        --border-medium: #252833;
        --border-accent: #2d3140;
        --text-primary: #e8eaf0;
        --text-secondary: #9ba1b0;
        --text-muted: #5c6375;
        --text-dim: #3d4255;
        --accent-red: #ff3b4e;
        --accent-red-glow: rgba(255,59,78,0.15);
        --accent-green: #00d68f;
        --accent-green-dim: rgba(0,214,143,0.12);
        --accent-blue: #0ea5e9;
        --accent-blue-dim: rgba(14,165,233,0.10);
        --accent-gold: #f5c542;
        --accent-gold-dim: rgba(245,197,66,0.10);
        --accent-purple: #a78bfa;
        --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
        --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
        --radius-sm: 4px;
        --radius-md: 8px;
        --radius-lg: 12px;
        --radius-xl: 16px;
    }

    /* ── Global ── */
    .stApp {
        background-color: var(--bg-primary) !important;
        color: var(--text-primary);
        font-family: var(--font-sans);
    }
    #MainMenu {visibility:hidden;} footer {visibility:hidden;} header {visibility:hidden;}

    /* ── Logo / Brand ── */
    .newsagent-logo {
        font-size: 1.6rem;
        font-weight: 900;
        font-family: var(--font-sans);
        background: linear-gradient(135deg, #ff3b4e 0%, #ff6b7a 50%, #ff3b4e 100%);
        background-size: 200% 200%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.5px;
        filter: drop-shadow(0 0 20px var(--accent-red-glow));
        animation: logo-shimmer 4s ease-in-out infinite;
    }
    .newsagent-logo span {
        background: linear-gradient(135deg, #5c6375, #3d4255);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 500;
        font-size: 0.85rem;
        letter-spacing: 2px;
        text-transform: uppercase;
    }
    @keyframes logo-shimmer {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }

    /* ── Pulse — live indicator ── */
    .pulse {
        display: inline-block;
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: var(--accent-green);
        margin-right: 8px;
        position: relative;
        animation: pulse-glow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        box-shadow: 0 0 8px var(--accent-green-dim);
    }
    .pulse::before {
        content: '';
        position: absolute;
        inset: -4px;
        border-radius: 50%;
        background: var(--accent-green);
        opacity: 0;
        animation: pulse-ring 2s cubic-bezier(0, 0, 0.2, 1) infinite;
    }
    @keyframes pulse-glow {
        0%, 100% { opacity: 1; box-shadow: 0 0 8px rgba(0,214,143,0.4); }
        50% { opacity: 0.6; box-shadow: 0 0 4px rgba(0,214,143,0.2); }
    }
    @keyframes pulse-ring {
        0% { transform: scale(0.8); opacity: 0.6; }
        80%, 100% { transform: scale(2); opacity: 0; }
    }

    /* ── Article Cards ── */
    .article-card {
        padding: 10px 16px;
        border-bottom: 1px solid var(--border-subtle);
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        display: flex;
        align-items: baseline;
        gap: 10px;
        flex-wrap: wrap;
        line-height: 1.6;
        position: relative;
    }
    .article-card::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 2px;
        background: transparent;
        transition: background 0.2s ease;
        border-radius: 0 2px 2px 0;
    }
    .article-card:hover {
        background: linear-gradient(90deg, var(--bg-hover) 0%, transparent 100%);
        border-bottom-color: var(--border-medium);
    }
    .article-card:hover::before {
        background: var(--accent-blue);
        box-shadow: 0 0 8px var(--accent-blue-dim);
    }

    /* Time stamp */
    .article-time {
        color: var(--text-dim);
        font-size: 0.74rem;
        font-family: var(--font-mono);
        min-width: 44px;
        flex-shrink: 0;
        font-weight: 500;
    }

    /* Ticker badge — glass effect */
    .ticker-badge {
        background: linear-gradient(135deg, rgba(14,165,233,0.08) 0%, rgba(14,165,233,0.04) 100%);
        color: var(--accent-blue);
        padding: 2px 9px;
        border-radius: var(--radius-sm);
        font-size: 0.73rem;
        font-weight: 700;
        font-family: var(--font-mono);
        margin-right: 4px;
        border: 1px solid rgba(14,165,233,0.15);
        letter-spacing: 0.6px;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        transition: all 0.15s ease;
    }
    .ticker-badge:hover {
        background: linear-gradient(135deg, rgba(14,165,233,0.15) 0%, rgba(14,165,233,0.08) 100%);
        border-color: rgba(14,165,233,0.3);
        box-shadow: 0 0 12px rgba(14,165,233,0.1);
    }

    /* Category tag — pill style */
    .cat-tag {
        padding: 2px 10px;
        border-radius: 100px;
        font-size: 0.64rem;
        font-weight: 700;
        margin-left: 6px;
        white-space: nowrap;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        font-family: var(--font-sans);
        transition: all 0.15s ease;
    }

    /* Article title */
    .article-title {
        color: var(--text-primary);
        font-size: 0.86rem;
        line-height: 1.45;
        text-decoration: none;
        flex: 1;
        min-width: 0;
        font-weight: 400;
        transition: color 0.15s ease;
    }
    .article-title:hover {
        color: #fff;
        text-decoration: underline;
        text-decoration-color: var(--border-accent);
        text-underline-offset: 3px;
        text-decoration-thickness: 1px;
    }

    /* Source badge */
    .source-badge {
        color: var(--text-dim);
        font-size: 0.68rem;
        margin-left: 8px;
        white-space: nowrap;
        flex-shrink: 0;
        font-weight: 500;
    }

    /* ── Relative time badge ── */
    .age-badge {
        color: var(--text-muted);
        font-size: 0.66rem;
        font-family: var(--font-mono);
        margin: 0 4px;
        white-space: nowrap;
        font-weight: 500;
    }

    /* ── U/D Rows — refined grid ── */
    .ud-row {
        display: grid;
        grid-template-columns: 52px 56px auto;
        align-items: center;
        padding: 8px 12px;
        border-bottom: 1px solid var(--border-subtle);
        gap: 8px;
        font-size: 0.82rem;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
    }
    .ud-row::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 2px;
        background: transparent;
        transition: background 0.2s ease;
    }
    .ud-row:hover {
        background: linear-gradient(90deg, var(--bg-hover) 0%, transparent 100%);
    }
    .ud-ticker {
        font-weight: 800;
        font-size: 0.9rem;
        font-family: var(--font-mono);
        letter-spacing: 0.3px;
    }
    .ud-action-upgrade { color: var(--accent-green); font-weight: 700; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.5px; }
    .ud-action-downgrade { color: var(--accent-red); font-weight: 700; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.5px; }
    .ud-action-mixed { color: var(--accent-gold); font-weight: 700; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.5px; }
    .ud-detail {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }
    .ud-firm {
        color: var(--text-secondary);
        font-size: 0.78rem;
        font-weight: 500;
    }
    .ud-rating {
        color: var(--text-primary);
        font-size: 0.78rem;
        font-weight: 500;
        background: var(--bg-elevated);
        padding: 1px 8px;
        border-radius: 100px;
        border: 1px solid var(--border-subtle);
    }
    .ud-pt {
        color: var(--accent-gold);
        font-weight: 700;
        font-size: 0.82rem;
        font-family: var(--font-mono);
        text-shadow: 0 0 12px var(--accent-gold-dim);
    }

    /* ── Column Headers — gradient underline ── */
    .col-header {
        font-weight: 800;
        font-size: 0.88rem;
        padding: 10px 12px;
        margin-bottom: 4px;
        border-bottom: none;
        font-family: var(--font-sans);
        letter-spacing: 0.3px;
        position: relative;
    }
    .col-header::after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 12px;
        right: 12px;
        height: 2px;
        border-radius: 2px;
    }
    .col-header-up {
        color: var(--accent-green);
        background: linear-gradient(180deg, rgba(0,214,143,0.06) 0%, transparent 100%);
        border-radius: var(--radius-md) var(--radius-md) 0 0;
    }
    .col-header-up::after { background: linear-gradient(90deg, var(--accent-green), transparent); }
    .col-header-dn {
        color: var(--accent-red);
        background: linear-gradient(180deg, rgba(255,59,78,0.06) 0%, transparent 100%);
        border-radius: var(--radius-md) var(--radius-md) 0 0;
    }
    .col-header-dn::after { background: linear-gradient(90deg, var(--accent-red), transparent); }
    .col-header-mix {
        color: var(--accent-gold);
        background: linear-gradient(180deg, rgba(245,197,66,0.06) 0%, transparent 100%);
        border-radius: var(--radius-md) var(--radius-md) 0 0;
    }
    .col-header-mix::after { background: linear-gradient(90deg, var(--accent-gold), transparent); }

    /* ── Stats — glassmorphism cards ── */
    .stat-box {
        background: linear-gradient(135deg, var(--bg-elevated) 0%, var(--bg-secondary) 100%);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        padding: 1rem 1.2rem;
        text-align: center;
        margin-bottom: 8px;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }
    .stat-box:hover {
        border-color: var(--border-medium);
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    .stat-number {
        font-size: 1.6rem;
        font-weight: 800;
        color: #fff;
        font-family: var(--font-mono);
        letter-spacing: -0.5px;
    }
    .stat-label {
        font-size: 0.72rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 4px;
        font-weight: 600;
    }

    /* ── Tabs — modern pill style ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        background: linear-gradient(180deg, var(--bg-secondary) 0%, var(--bg-elevated) 100%);
        border-radius: var(--radius-lg);
        padding: 4px;
        border: 1px solid var(--border-subtle);
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.2);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 9px 16px;
        font-size: 0.80rem;
        color: var(--text-muted);
        border-radius: var(--radius-md);
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        white-space: nowrap;
        font-weight: 600;
        font-family: var(--font-sans);
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: var(--text-secondary);
        background: rgba(255,255,255,0.03);
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, var(--bg-hover) 0%, var(--bg-elevated) 100%) !important;
        color: #fff !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05);
        border: 1px solid var(--border-medium);
    }
    .stTabs [data-baseweb="tab-highlight"] { display: none; }
    .stTabs [data-baseweb="tab-border"] { display: none; }

    /* ── Streamlit Widget Overrides ── */
    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div {
        background-color: var(--bg-elevated) !important;
        border-color: var(--border-medium) !important;
        border-radius: var(--radius-md) !important;
        font-family: var(--font-sans) !important;
    }
    [data-baseweb="select"] > div:focus-within,
    [data-baseweb="input"] > div:focus-within {
        border-color: var(--accent-blue) !important;
        box-shadow: 0 0 0 2px rgba(14,165,233,0.15) !important;
    }
    div[data-baseweb="popover"] > div {
        background-color: var(--bg-elevated) !important;
        border: 1px solid var(--border-medium) !important;
        border-radius: var(--radius-md) !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4) !important;
    }
    div[data-baseweb="menu"] {
        background-color: var(--bg-elevated) !important;
    }
    div[data-baseweb="menu"] li:hover {
        background-color: var(--bg-hover) !important;
    }

    /* ── Watchlist Chips — glass pills ── */
    .watchlist-chip {
        display: inline-block;
        background: linear-gradient(135deg, rgba(14,165,233,0.10) 0%, rgba(14,165,233,0.04) 100%);
        color: var(--accent-blue);
        padding: 4px 12px;
        border-radius: 100px;
        font-size: 0.78rem;
        font-weight: 700;
        margin: 2px 4px;
        font-family: var(--font-mono);
        border: 1px solid rgba(14,165,233,0.15);
        letter-spacing: 0.5px;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        transition: all 0.2s ease;
    }
    .watchlist-chip:hover {
        background: linear-gradient(135deg, rgba(14,165,233,0.18) 0%, rgba(14,165,233,0.08) 100%);
        border-color: rgba(14,165,233,0.3);
        box-shadow: 0 0 16px rgba(14,165,233,0.12);
        transform: translateY(-1px);
    }

    /* ── Scrollable U/D column ── */
    .ud-scroll {
        max-height: 70vh;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--border-medium) transparent;
    }
    .ud-scroll::-webkit-scrollbar { width: 5px; }
    .ud-scroll::-webkit-scrollbar-track { background: transparent; }
    .ud-scroll::-webkit-scrollbar-thumb {
        background: var(--border-medium);
        border-radius: 10px;
    }
    .ud-scroll::-webkit-scrollbar-thumb:hover {
        background: var(--border-accent);
    }

    /* ── Refresh / Status Bar — glassmorphism ── */
    .refresh-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        background: linear-gradient(135deg, var(--bg-elevated) 0%, var(--bg-secondary) 100%);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        margin-bottom: 12px;
        font-size: 0.75rem;
        color: var(--text-muted);
        font-family: var(--font-sans);
        font-weight: 500;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        box-shadow: 0 2px 12px rgba(0,0,0,0.15);
    }
    .refresh-dot {
        display: inline-block;
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--accent-green);
        margin-right: 8px;
        animation: pulse-glow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        box-shadow: 0 0 8px rgba(0,214,143,0.4);
    }

    /* ── Expander tweaks ── */
    .streamlit-expanderHeader {
        font-size: 0.86rem !important;
        font-family: var(--font-sans) !important;
    }
    div[data-testid="stExpander"] {
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-md) !important;
        margin-bottom: 6px;
        background: var(--bg-secondary) !important;
        overflow: hidden;
        transition: border-color 0.2s ease;
    }
    div[data-testid="stExpander"]:hover {
        border-color: var(--border-medium) !important;
    }

    /* ═══ Breaking News Panel — urgent glassmorphism ═══ */
    .breaking-wrap {
        border-left: 2px solid rgba(255,59,78,0.20);
        padding-left: 0;
        border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
    }
    .breaking-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 14px;
        background: linear-gradient(135deg, rgba(255,59,78,0.08) 0%, var(--bg-elevated) 100%);
        border: 1px solid rgba(255,59,78,0.15);
        border-radius: var(--radius-lg);
        margin-bottom: 10px;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
    }
    .breaking-dot {
        width: 9px; height: 9px; border-radius: 50%;
        background: var(--accent-red);
        animation: pulse-glow-red 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        box-shadow: 0 0 10px rgba(255,59,78,0.5);
        flex-shrink: 0;
        position: relative;
    }
    .breaking-dot::before {
        content: '';
        position: absolute;
        inset: -3px;
        border-radius: 50%;
        background: var(--accent-red);
        opacity: 0;
        animation: pulse-ring-red 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;
    }
    @keyframes pulse-glow-red {
        0%, 100% { opacity: 1; box-shadow: 0 0 10px rgba(255,59,78,0.5); }
        50% { opacity: 0.5; box-shadow: 0 0 4px rgba(255,59,78,0.2); }
    }
    @keyframes pulse-ring-red {
        0% { transform: scale(0.8); opacity: 0.5; }
        80%, 100% { transform: scale(2.2); opacity: 0; }
    }
    .breaking-title {
        font-weight: 900; font-size: 0.80rem;
        color: var(--accent-red); letter-spacing: 1.5px;
        text-transform: uppercase;
        font-family: var(--font-sans);
    }
    .breaking-count {
        color: var(--text-dim); font-size: 0.66rem;
        margin-left: auto; white-space: nowrap;
        flex-shrink: 0;
        font-family: var(--font-mono);
        font-weight: 500;
    }
    .breaking-scroll {
        max-height: calc(100vh - 200px);
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: rgba(255,59,78,0.15) transparent;
    }
    .breaking-scroll::-webkit-scrollbar { width: 3px; }
    .breaking-scroll::-webkit-scrollbar-track { background: transparent; }
    .breaking-scroll::-webkit-scrollbar-thumb {
        background: rgba(255,59,78,0.2);
        border-radius: 10px;
    }
    .breaking-item {
        padding: 10px 14px;
        border-bottom: 1px solid rgba(255,59,78,0.06);
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        line-height: 1.45;
        position: relative;
    }
    .breaking-item::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 2px;
        background: transparent;
        transition: background 0.2s ease;
    }
    .breaking-item:hover {
        background: linear-gradient(90deg, rgba(255,59,78,0.04) 0%, transparent 100%);
    }
    .breaking-item:hover::before {
        background: var(--accent-red);
    }
    .breaking-item-time {
        color: rgba(255,59,78,0.45); font-size: 0.68rem;
        font-family: var(--font-mono);
        display: block; margin-bottom: 3px;
        font-weight: 500;
    }
    .breaking-item-title {
        color: var(--text-primary); font-size: 0.80rem;
        text-decoration: none; line-height: 1.4;
        font-weight: 400;
        transition: color 0.15s ease;
    }
    .breaking-item-title:hover { color: #fff; }
    .breaking-item-meta {
        display: flex; align-items: center; gap: 6px;
        margin-top: 5px;
    }
    .breaking-item-ticker {
        background: linear-gradient(135deg, rgba(255,59,78,0.10) 0%, rgba(255,59,78,0.04) 100%);
        color: #ff6b7a;
        padding: 1px 7px; border-radius: var(--radius-sm);
        font-size: 0.68rem; font-weight: 700;
        font-family: var(--font-mono);
        border: 1px solid rgba(255,59,78,0.15);
        letter-spacing: 0.3px;
    }
    .breaking-item-cat {
        font-size: 0.62rem; font-weight: 700;
        padding: 1px 7px; border-radius: 100px;
        text-transform: uppercase; letter-spacing: 0.4px;
        font-family: var(--font-sans);
    }
    .breaking-item-src {
        color: var(--text-dim); font-size: 0.64rem;
        margin-left: auto;
        font-weight: 500;
    }

    /* ═══ U/D Quality Grades — refined badges ═══ */
    .ud-grade {
        display: inline-block;
        padding: 1px 7px;
        border-radius: 100px;
        font-size: 0.66rem;
        font-weight: 800;
        font-family: var(--font-mono);
        margin-left: 6px;
        letter-spacing: 0.5px;
        transition: all 0.15s ease;
    }
    .ud-grade-a-plus {
        background: linear-gradient(135deg, rgba(0,214,143,0.15) 0%, rgba(0,214,143,0.06) 100%);
        color: var(--accent-green);
        border: 1px solid rgba(0,214,143,0.25);
    }
    .ud-grade-a {
        background: linear-gradient(135deg, rgba(14,165,233,0.15) 0%, rgba(14,165,233,0.06) 100%);
        color: var(--accent-blue);
        border: 1px solid rgba(14,165,233,0.25);
    }
    .ud-grade-b {
        background: linear-gradient(135deg, rgba(245,197,66,0.15) 0%, rgba(245,197,66,0.06) 100%);
        color: var(--accent-gold);
        border: 1px solid rgba(245,197,66,0.25);
    }
    .ud-grade-c {
        background: linear-gradient(135deg, rgba(92,99,117,0.15) 0%, rgba(92,99,117,0.06) 100%);
        color: var(--text-muted);
        border: 1px solid rgba(92,99,117,0.25);
    }

    /* ═══ Earnings Cards — elevated glass cards ═══ */
    .earnings-card {
        padding: 14px 18px;
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        margin-bottom: 8px;
        background: linear-gradient(135deg, var(--bg-elevated) 0%, var(--bg-secondary) 100%);
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        position: relative;
        overflow: hidden;
    }
    .earnings-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent);
    }
    .earnings-card:hover {
        border-color: var(--border-medium);
        box-shadow: 0 4px 24px rgba(0,0,0,0.25);
        transform: translateY(-1px);
    }
    .earnings-card-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;
    }
    .earnings-ticker {
        font-weight: 800;
        font-size: 1.05rem;
        color: var(--accent-blue);
        font-family: var(--font-mono);
        letter-spacing: 0.3px;
        text-shadow: 0 0 16px var(--accent-blue-dim);
    }
    .earnings-time {
        color: var(--text-muted);
        font-size: 0.72rem;
        font-family: var(--font-mono);
        font-weight: 500;
    }
    .earnings-title {
        color: var(--text-secondary);
        font-size: 0.82rem;
        text-decoration: none;
        line-height: 1.4;
        transition: color 0.15s ease;
    }
    .earnings-title:hover { color: #fff; }
    .earnings-metrics {
        display: flex;
        gap: 12px;
        margin-top: 8px;
        flex-wrap: wrap;
    }
    .earnings-metric {
        font-size: 0.74rem;
        font-family: var(--font-mono);
        font-weight: 600;
        padding: 2px 8px;
        border-radius: var(--radius-sm);
        background: rgba(255,255,255,0.03);
    }
    .earnings-beat {
        color: var(--accent-green) !important;
        background: var(--accent-green-dim) !important;
        border: 1px solid rgba(0,214,143,0.15);
    }
    .earnings-miss {
        color: var(--accent-red) !important;
        background: var(--accent-red-glow) !important;
        border: 1px solid rgba(255,59,78,0.15);
    }
    .earnings-neutral {
        color: var(--text-secondary);
    }
    .earnings-src {
        color: var(--text-dim);
        font-size: 0.66rem;
        margin-left: auto;
        font-weight: 500;
    }

    /* ── Mobile Responsive ── */
    @media (max-width: 768px) {
        /* Force Streamlit columns to stack vertically */
        div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }

        /* Logo */
        .newsagent-logo {
            font-size: 1.15rem !important;
        }

        /* Tabs — horizontal scroll instead of wrap */
        .stTabs [data-baseweb="tab-list"] {
            gap: 2px !important;
            overflow-x: auto !important;
            flex-wrap: nowrap !important;
            -webkit-overflow-scrolling: touch;
            padding-bottom: 4px !important;
        }
        .stTabs [data-baseweb="tab"] {
            font-size: 0.68rem !important;
            padding: 6px 10px !important;
            white-space: nowrap !important;
        }

        /* Article cards — more compact */
        .article-card {
            padding: 8px 10px !important;
            gap: 6px !important;
        }
        .article-time {
            font-size: 0.65rem !important;
            min-width: 38px !important;
        }
        .article-title {
            font-size: 0.80rem !important;
        }
        .article-src {
            font-size: 0.58rem !important;
        }

        /* Ticker & category badges — smaller */
        .ticker-badge {
            font-size: 0.60rem !important;
            padding: 1px 5px !important;
        }
        .cat-tag {
            font-size: 0.56rem !important;
            padding: 1px 5px !important;
        }

        /* U/D rows — single column layout */
        .ud-row {
            grid-template-columns: 1fr !important;
            gap: 4px !important;
            padding: 8px 10px !important;
        }
        .ud-detail {
            gap: 6px !important;
        }

        /* Column headers */
        .col-header {
            font-size: 0.70rem !important;
            padding: 6px 10px !important;
        }

        /* Stat boxes — compact */
        .stat-box {
            padding: 8px 10px !important;
        }
        .stat-box .stat-num {
            font-size: 1.3rem !important;
        }
        .stat-box .stat-label {
            font-size: 0.58rem !important;
        }

        /* Refresh bar — stack */
        .refresh-bar {
            flex-direction: column !important;
            gap: 3px !important;
            font-size: 0.66rem !important;
            padding: 6px 10px !important;
        }

        /* Breaking news — compact */
        .breaking-header {
            font-size: 0.70rem !important;
            padding: 8px 10px !important;
        }
        .breaking-item {
            padding: 6px 8px !important;
            font-size: 0.78rem !important;
        }
        .breaking-item-title {
            font-size: 0.78rem !important;
        }
        .breaking-scroll {
            max-height: 50vh !important;
        }

        /* Earnings cards */
        .earnings-card {
            padding: 8px 10px !important;
        }
        .earnings-metrics {
            gap: 6px !important;
        }
        .earnings-metric {
            font-size: 0.72rem !important;
        }

        /* Watchlist chips */
        .watchlist-chip {
            font-size: 0.66rem !important;
            padding: 2px 7px !important;
        }

        /* Touch-friendly buttons */
        .stButton > button {
            min-height: 44px !important;
            padding: 8px 16px !important;
            font-size: 0.80rem !important;
        }

        /* Inputs — larger touch targets */
        .stTextInput input, .stSelectbox select {
            min-height: 44px !important;
            font-size: 0.85rem !important;
        }

        /* Scrollable containers — shorter on mobile */
        .ud-scroll {
            max-height: 55vh !important;
        }
    }

    /* ── Tablet (769-1024px) ── */
    @media (min-width: 769px) and (max-width: 1024px) {
        .newsagent-logo {
            font-size: 1.35rem !important;
        }
        .article-card {
            padding: 8px 12px !important;
        }
        .stTabs [data-baseweb="tab"] {
            font-size: 0.72rem !important;
            padding: 7px 12px !important;
        }
    }

    /* ── Global scrollbar ── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb {
        background: var(--border-medium);
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb:hover { background: var(--border-accent); }

    /* ── Streamlit button overrides ── */
    .stButton > button {
        background: var(--bg-elevated) !important;
        border: 1px solid var(--border-medium) !important;
        color: var(--text-secondary) !important;
        border-radius: var(--radius-md) !important;
        font-family: var(--font-sans) !important;
        font-weight: 600 !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover {
        background: var(--bg-hover) !important;
        border-color: var(--border-accent) !important;
        color: var(--text-primary) !important;
        box-shadow: 0 2px 12px rgba(0,0,0,0.2) !important;
    }

    /* ── Sidebar styling ── */
    section[data-testid="stSidebar"] {
        background: var(--bg-secondary) !important;
        border-right: 1px solid var(--border-subtle) !important;
    }
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: var(--text-muted) !important;
        font-size: 0.72rem !important;
        text-transform: uppercase !important;
        letter-spacing: 1.5px !important;
        font-weight: 700 !important;
        font-family: var(--font-sans) !important;
    }

    /* ── Divider ── */
    hr {
        border-color: var(--border-subtle) !important;
    }

    /* ── Toast / notifications ── */
    div[data-testid="stToast"] {
        background: var(--bg-elevated) !important;
        border: 1px solid var(--border-medium) !important;
        border-radius: var(--radius-lg) !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4) !important;
    }

    /* ── Form styling ── */
    div[data-testid="stForm"] {
        background: var(--bg-secondary) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-lg) !important;
        padding: 1rem !important;
    }

    /* ═══════════════════════════════════════════════════════════════
       Catalyst Board — ranked, scored, price-confirmed events
       ═══════════════════════════════════════════════════════════════ */

    .cat-card {
        display: flex;
        gap: 12px;
        padding: 11px 14px 11px 12px;
        border-bottom: 1px solid var(--border-subtle);
        border-left: 2px solid var(--cat-accent, var(--border-medium));
        transition: background 0.18s ease, border-color 0.18s ease;
        align-items: flex-start;
    }
    .cat-card:hover {
        background: linear-gradient(90deg, var(--bg-hover) 0%, transparent 90%);
        border-bottom-color: var(--border-medium);
    }

    /* Score chip — the headline number */
    .cat-score {
        flex: 0 0 auto;
        width: 42px;
        text-align: center;
        font-family: var(--font-mono);
        font-weight: 800;
        font-size: 1.02rem;
        line-height: 1;
        padding: 7px 0 6px;
        border-radius: var(--radius-md);
        border: 1px solid var(--cat-accent, var(--border-medium));
        background: var(--cat-accent-dim, rgba(255,255,255,0.03));
        color: var(--cat-accent, var(--text-secondary));
        cursor: help;
    }
    .cat-score small {
        display: block;
        font-size: 0.5rem;
        font-weight: 600;
        letter-spacing: 0.8px;
        color: var(--text-dim);
        margin-top: 3px;
        text-transform: uppercase;
    }

    .cat-body { flex: 1 1 auto; min-width: 0; }

    .cat-meta {
        display: flex;
        align-items: center;
        gap: 7px;
        flex-wrap: wrap;
        margin-bottom: 4px;
    }
    .cat-ticker {
        font-family: var(--font-mono);
        font-weight: 800;
        font-size: 0.82rem;
        letter-spacing: 0.7px;
        color: var(--text-primary);
    }
    .cat-ticker.none { color: var(--text-dim); font-weight: 600; }

    .cat-type {
        padding: 2px 9px;
        border-radius: 100px;
        font-size: 0.62rem;
        font-weight: 700;
        letter-spacing: 0.6px;
        text-transform: uppercase;
        white-space: nowrap;
    }

    /* Price confirmation */
    .cat-move {
        font-family: var(--font-mono);
        font-size: 0.74rem;
        font-weight: 700;
        padding: 1px 7px;
        border-radius: var(--radius-sm);
    }
    .cat-move.up   { color: var(--accent-green); background: var(--accent-green-dim); }
    .cat-move.down { color: var(--accent-red);   background: var(--accent-red-glow); }
    .cat-move.flat { color: var(--text-muted);   background: rgba(255,255,255,0.03); }

    .cat-rvol {
        font-family: var(--font-mono);
        font-size: 0.68rem;
        font-weight: 600;
        color: var(--accent-gold);
        background: var(--accent-gold-dim);
        padding: 1px 6px;
        border-radius: var(--radius-sm);
    }
    .cat-confirmed {
        font-size: 0.58rem;
        font-weight: 800;
        letter-spacing: 0.9px;
        color: var(--accent-green);
        border: 1px solid rgba(0,214,143,0.28);
        background: var(--accent-green-dim);
        padding: 1px 6px;
        border-radius: var(--radius-sm);
    }

    .cat-spacer { flex: 1 1 auto; }
    .cat-when {
        font-family: var(--font-mono);
        font-size: 0.68rem;
        color: var(--text-dim);
        white-space: nowrap;
    }

    .cat-headline {
        display: block;
        color: var(--text-primary);
        font-size: 0.88rem;
        line-height: 1.45;
        text-decoration: none;
        font-weight: 450;
    }
    .cat-headline:hover { color: var(--accent-blue); }

    .cat-facts {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-top: 5px;
    }
    .cat-fact {
        font-family: var(--font-mono);
        font-size: 0.66rem;
        color: var(--text-muted);
        background: rgba(255,255,255,0.025);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-sm);
        padding: 1px 7px;
    }
    .cat-fact.sources { color: var(--accent-blue); border-color: rgba(14,165,233,0.18); }

    .cat-empty {
        text-align: center;
        color: var(--text-muted);
        padding: 2.4rem 1rem;
        font-size: 0.86rem;
        line-height: 1.7;
    }
    .cat-empty b { color: var(--text-secondary); font-weight: 600; }

    /* Board summary strip */
    .cat-summary {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin: 2px 0 8px;
    }
    .cat-kpi {
        flex: 1 1 90px;
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-md);
        background: var(--bg-secondary);
        padding: 7px 10px;
    }
    .cat-kpi-value {
        font-family: var(--font-mono);
        font-size: 1.1rem;
        font-weight: 800;
        color: var(--text-primary);
        line-height: 1.1;
    }
    .cat-kpi-label {
        font-size: 0.6rem;
        letter-spacing: 0.8px;
        text-transform: uppercase;
        color: var(--text-dim);
        font-weight: 600;
        margin-top: 2px;
    }

    @media (max-width: 768px) {
        .cat-card { padding: 9px 10px 9px 9px; gap: 9px; }
        .cat-score { width: 36px; font-size: 0.9rem; }
        .cat-headline { font-size: 0.82rem; }
        .cat-when { display: none; }
    }


    /* ═══════════════════════════════════════════════════════════════
       Squawk tape — chronological, latency-first catalyst stream
       ═══════════════════════════════════════════════════════════════ */

    .squawk-row {
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 7px 12px;
        border-bottom: 1px solid var(--border-subtle);
        border-left: 2px solid var(--sq-accent, transparent);
        font-size: 0.85rem;
        line-height: 1.5;
        transition: background 0.15s ease;
    }
    .squawk-row:hover { background: var(--bg-hover); }
    .squawk-row.fresh {
        background: linear-gradient(90deg, rgba(255,59,78,0.06) 0%, transparent 70%);
    }

    /* Age is the headline metric on a squawk tape, so it leads the row. */
    .squawk-age {
        flex: 0 0 auto;
        min-width: 46px;
        text-align: right;
        font-family: var(--font-mono);
        font-size: 0.72rem;
        font-weight: 700;
        color: var(--text-dim);
    }
    .squawk-age.hot  { color: var(--accent-red); }
    .squawk-age.warm { color: var(--accent-gold); }

    .squawk-ticker {
        flex: 0 0 auto;
        min-width: 52px;
        font-family: var(--font-mono);
        font-weight: 800;
        font-size: 0.8rem;
        letter-spacing: 0.6px;
        color: var(--text-primary);
    }
    .squawk-ticker.none { color: var(--text-dim); font-weight: 600; }

    .squawk-tag {
        flex: 0 0 auto;
        padding: 1px 7px;
        border-radius: 100px;
        font-size: 0.59rem;
        font-weight: 700;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        white-space: nowrap;
    }
    .squawk-headline {
        flex: 1 1 auto;
        min-width: 0;
        color: var(--text-primary);
        text-decoration: none;
    }
    .squawk-headline:hover { color: var(--accent-blue); }
    .squawk-move {
        flex: 0 0 auto;
        font-family: var(--font-mono);
        font-size: 0.72rem;
        font-weight: 700;
    }
    .squawk-move.up { color: var(--accent-green); }
    .squawk-move.down { color: var(--accent-red); }
    .squawk-src {
        flex: 0 0 auto;
        font-size: 0.65rem;
        color: var(--text-dim);
        font-family: var(--font-mono);
        white-space: nowrap;
    }
    .squawk-src.primary { color: var(--accent-blue); }

    .latency-bar {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 8px;
    }
    .latency-chip {
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-md);
        background: var(--bg-secondary);
        padding: 5px 10px;
        font-size: 0.68rem;
        color: var(--text-muted);
        font-family: var(--font-mono);
    }
    .latency-chip b { color: var(--text-primary); font-weight: 700; }

    @media (max-width: 768px) {
        .squawk-row { padding: 6px 8px; gap: 7px; font-size: 0.79rem; }
        .squawk-src { display: none; }
    }

</style>
"""


def _esc(text: str) -> str:
    return html_mod.escape(text, quote=True)


_SOURCE_SHORT = {
    "Investing.com News": "Investing",
    "MarketWatch Top Stories": "MarketWatch",
    "CNBC Top News": "CNBC",
    "Benzinga News": "Benzinga",
    "Nasdaq Original Content": "Nasdaq",
    "Yahoo Finance News": "Yahoo",
    "Seeking Alpha": "SeekingAlpha",
    "Seeking Alpha News": "SeekingAlpha",
    "Google News - Analyst Upgrades": "GNews",
    "Google News - Stock Upgrades Downgrades": "GNews",
}


def _short_source(name: str) -> str:
    if name in _SOURCE_SHORT:
        return _SOURCE_SHORT[name]
    # Fuzzy match common sources
    nl = name.lower()
    if "seeking" in nl:
        return "SeekingAlpha"
    if "yahoo" in nl:
        return "Yahoo"
    if "nasdaq" in nl:
        return "Nasdaq"
    return name[:14]


def _render_article_html(a: Article) -> str:
    ts = _format_time(a.published, "%H:%M")
    rel = _relative_time(a.published)
    tickers = "".join(f'<span class="ticker-badge">{_esc(t)}</span>' for t in a.tickers[:3])
    cc = CATEGORY_COLORS.get(a.category, "#6b7394")
    cat = f'<span class="cat-tag" style="background:{cc}14;color:{cc};border:1px solid {cc}28">{a.category.value.upper()}</span>'
    rel_html = f'<span class="age-badge">{rel}</span>' if rel else ""
    src = _short_source(a.source)
    return (f'<div class="article-card"><span class="article-time">{ts}</span>{rel_html} {tickers}'
            f'<a href="{_esc(a.url)}" target="_blank" class="article-title">{_esc(a.title)}</a> '
            f'{cat} <span class="source-badge">{_esc(src)}</span></div>')


# ── Noise filter — aggressively remove non-trading content ──

# Hard-block patterns: always skip these
_NOISE_PATTERNS = [
    # Personal finance / lifestyle
    r"(?i)\b(?:husband|wife|divorce|wedding|marriage|dating|romance)\b",
    r"(?i)\b(?:horoscope|zodiac|astrology|celebrity gossip)\b",
    r"(?i)\b(?:recipe|cookbook|diet plan|weight loss tips)\b",
    r"(?i)\b(?:sports score|nfl draft|nba playoff|world cup|super bowl)\b",
    # Form 4 / Form 144 SEC filings (keep in Catalysts only)
    r"(?i)^form\s+(?:4|144)\s",
    # Minor insider transactions (sells in shares/stock)
    r"(?i)\bsells?\s+\$[\d,.]+\s*(?:k|m|million|thousand)?\s+(?:in\s+)?(?:shares|stock|class\s+[a-z])\b",
    # "X director/officer/CFO/CEO sells shares worth $Y"
    r"(?i)\b(?:director|officer|counsel|cpo|cfo|coo|cto|ceo|svp|evp|vp|president)\b.*\bsells?\b.*\b(?:shares?|stock|million)\b",
    # Foreign market open/close predictions
    r"(?i)^(?:malaysia|japan|australia|india|hong kong|singapore|south korea|korea|taiwan|europe|china)\s+shares?\s+(?:tipped|may|set|expected|poised)\b",
    # Vague clickbait
    r"(?i)^(?:ask an advisor|it.s complicated|dear moneyist)\b",
    # Generic "notable" technical signals with no context
    r"(?i)^notable\s+(?:two hundred|200|fifty|50)\s+day\s+moving\s+average",
    r"(?i)^(?:oversold conditions|rsi alert|relative strength alert)\b",
    r"(?i)\b(?:becomes oversold|enters oversold|now oversold)\b",
    # Generic "Wex Breaks Below" / "Cross" technical noise
    r"(?i)^(?:\w+\s+)?breaks?\s+(?:below|above)\s+\d+-day\s+moving\s+average",
    # Board/director resignations and appointments (low trading value)
    r"(?i)\b(?:resigns?|resignation)\b.*\b(?:board|director)\b",
    r"(?i)\b(?:replaces?|retains?)\b.*\b(?:independent\s+)?auditor\b",
    # Generic foreign market summaries
    r"(?i)^(?:south\s+)?korea\s+shares\b",
    # Insider BUYS of minor amounts
    r"(?i)\bbuys?\b.*\bshares?\s+worth\s+\$[\d,.]+[kmKM]?\b",
    # "X sells $Y in stock/shares" — any insider sell
    r"(?i)\bsells?\s+\$[\d,.]+(?:k|m)?\s+in\s+(?:shares|stock)\b",
    r"(?i)\bsells?\s+\$[\d,.]+\s+(?:million|thousand)\s+in\s+(?:shares|stock)\b",
    # "director/officer sells shares after option exercise"
    r"(?i)\bsells?\b.*\bafter\s+option\s+exercise\b",
    # "Musk's motives" / trial / lawsuit noise (not trading-relevant)
    r"(?i)\b(?:trial|lawsuit|deposition|subpoena)\b.*\b(?:nears?\s+end|begins?|filed)\b",
    # "Why X Stock Zoomed/Soared/Tanked" clickbait without substance
    r"(?i)^why\s+\w+\s+stock\s+(?:zoomed|soared|tanked|plunged|crashed|spiked|surged)\b",
    # Generic "Stock Market Today" filler
    r"(?i)^stock\s+market\s+today[,:]",
]
_NOISE_RES = [re.compile(p) for p in _NOISE_PATTERNS]

# Soft-block: skip unless article has a ticker or is a categorized event
_SOFTBLOCK_PATTERNS = [
    r"(?i)\bappoints?\b.*\b(?:as\s+)?(?:president|director|board|chairman|advisor)\b",
    r"(?i)\b(?:names|hires|taps)\b.*\b(?:new\s+)?(?:ceo|cfo|coo|cto|president|director)\b",
]
_SOFTBLOCK_RES = [re.compile(p) for p in _SOFTBLOCK_PATTERNS]


_TOP_SOURCES = {"CNBC", "MarketWatch", "Yahoo", "Benzinga", "SeekingAlpha"}


def _is_noise(title: str, category: str = "general", has_ticker: bool = False, source: str = "") -> bool:
    """Return True if this article should be filtered from the Live Feed."""
    # Hard blocks — always skip
    if any(p.search(title) for p in _NOISE_RES):
        return True
    # Soft blocks — skip only if no ticker AND general category
    if category == "general" and not has_ticker:
        if any(p.search(title) for p in _SOFTBLOCK_RES):
            return True
    return False


def render_articles(articles: list[Article], filtered: bool = True):
    if not articles:
        st.markdown('<div style="text-align:center;color:#555;padding:2rem">No articles yet. Feeds loading...</div>', unsafe_allow_html=True)
        return
    # Deduplicate + optionally filter noise
    seen_titles, deduped = set(), []
    for a in articles:
        key = a.title.strip().lower()[:80]
        if key in seen_titles:
            continue
        if filtered and _is_noise(a.title, a.category.value, bool(a.tickers), a.source):
            continue
        seen_titles.add(key)
        deduped.append(a)
    st.markdown("\n".join(_render_article_html(a) for a in deduped), unsafe_allow_html=True)


def _render_ud_html(ud: UpgradeDowngrade, show_grade: bool = True) -> str:
    rel = _relative_time(ud.published)
    action = ud.action.lower()
    if action in ("upgrade", "initiated", "raises_pt"):
        tc = "#00d68f"
    elif action in ("downgrade", "lowers_pt"):
        tc = "#ff3b4e"
    else:
        tc = "#f5c542"
    # Build detail line: firm + rating + PT + grade
    details = []
    if ud.firm:
        details.append(f'<span class="ud-firm">{_esc(ud.firm)}</span>')
    if ud.old_rating and ud.new_rating:
        details.append(f'<span class="ud-rating">{_esc(ud.old_rating)} → {_esc(ud.new_rating)}</span>')
    elif ud.new_rating:
        details.append(f'<span class="ud-rating">{_esc(ud.new_rating)}</span>')
    if ud.price_target:
        details.append(f'<span class="ud-pt">{_esc(ud.price_target)}</span>')
    if show_grade:
        g = grade_ud(ud)
        details.append(_grade_html(g))
    detail_html = " ".join(details) if details else ""
    rel_html = f'<span class="age-badge">{rel}</span>' if rel else ""
    return (f'<div class="ud-row">'
            f'<span class="ud-ticker" style="color:{tc}">{_esc(ud.ticker)}</span>'
            f'{rel_html}'
            f'<div class="ud-detail">{detail_html}</div>'
            f'</div>')


def render_uds(uds: list[UpgradeDowngrade], scrollable: bool = False):
    if not uds:
        st.markdown('<div style="text-align:center;color:#555;padding:2rem">No upgrades/downgrades yet.</div>', unsafe_allow_html=True)
        return
    html = "\n".join(_render_ud_html(u) for u in uds)
    if scrollable:
        html = f'<div class="ud-scroll">{html}</div>'
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
#  Catalyst Board rendering
# ══════════════════════════════════════════════════════════════════════

# Score bands. The colour answers "do I need to look at this right now?"
_SCORE_BANDS = (
    (80, "#ff3b4e", "rgba(255,59,78,0.10)", "CRITICAL"),
    (65, "#f5c542", "rgba(245,197,66,0.10)", "HIGH"),
    (50, "#0ea5e9", "rgba(14,165,233,0.10)", "NOTABLE"),
    (0,  "#5c6375", "rgba(255,255,255,0.03)", "LOW"),
)


def score_band(score: float) -> tuple[str, str, str]:
    for threshold, color, dim, label in _SCORE_BANDS:
        if score >= threshold:
            return color, dim, label
    return _SCORE_BANDS[-1][1:]


def _score_tooltip(c: dict) -> str:
    """Human-readable derivation, shown on hover over the score chip."""
    parts = c.get("score_parts") or {}
    if not parts:
        return f"Impact score {c.get('score', 0)}"
    base = parts.get("base", 0)
    order = ("detection", "ticker", "source", "recency", "corroboration", "size", "price")
    names = {
        "detection": "match confidence", "ticker": "ticker certainty",
        "source": "source authority", "recency": "freshness",
        "corroboration": "corroboration", "size": "float sensitivity",
        "price": "price confirmation",
    }
    lines = [f"{c.get('label', 'Catalyst')} base impact {base:g}"]
    lines += [f"x {parts[k]:g} {names[k]}" for k in order if k in parts]
    lines.append(f"= {c.get('score', 0):g} / 100")
    return "  ".join(lines)


def _render_catalyst_html(c: dict) -> str:
    score = float(c.get("score") or 0)
    color, dim, band = score_band(score)
    type_color = c.get("color") or "#8b93b0"
    ticker = c.get("ticker") or ""

    move_html = ""
    change = c.get("change_pct")
    if change is not None:
        cls = "up" if change > 0.05 else ("down" if change < -0.05 else "flat")
        move_html = f'<span class="cat-move {cls}">{change:+.2f}%</span>'
    rvol = c.get("rel_volume") or 0
    rvol_html = f'<span class="cat-rvol">{rvol:.1f}x vol</span>' if rvol >= 1.5 else ""
    confirmed_html = '<span class="cat-confirmed">CONFIRMED</span>' if c.get("confirmed") else ""

    published = _parse_dt(c["published"]) if isinstance(c.get("published"), str) else c.get("published")
    when = f'{_format_time(published, "%H:%M")} · {_relative_time(published)}' if published else ""

    facts = []
    n_sources = int(c.get("source_count") or 1)
    if n_sources > 1:
        facts.append(f'<span class="cat-fact sources">{n_sources} sources</span>')
    headline = c.get("headline", "")
    for key, value in (c.get("facts") or {}).items():
        # Filing form and company already read in the headline for SEC items.
        if key in ("company", "filing") or str(value) in headline:
            continue
        text = str(value)
        if key == "items":
            extra = text.split(", ")
            text = ", ".join(extra[:3]) + (f" +{len(extra) - 3}" if len(extra) > 3 else "")
        facts.append(f'<span class="cat-fact">{_esc(text)}</span>')
    sources = c.get("sources") or []
    if sources:
        facts.append(f'<span class="cat-fact">{_esc(_short_source(sources[0].get("source", "")))}</span>')
    if c.get("company") and ticker and c["company"][:20].lower() not in headline.lower():
        facts.append(f'<span class="cat-fact">{_esc(c["company"][:36])}</span>')

    ticker_html = (
        f'<span class="cat-ticker">{_esc(ticker)}</span>' if ticker
        else '<span class="cat-ticker none">MARKET</span>'
    )
    return (
        f'<div class="cat-card" style="--cat-accent:{color};--cat-accent-dim:{dim}">'
        f'<div class="cat-score" title="{_esc(_score_tooltip(c))}">{score:.0f}<small>{band}</small></div>'
        f'<div class="cat-body">'
        f'<div class="cat-meta">{ticker_html}'
        f'<span class="cat-type" style="background:{type_color}14;color:{type_color};'
        f'border:1px solid {type_color}30">{_esc(c.get("label", ""))}</span>'
        f'{move_html}{rvol_html}{confirmed_html}'
        f'<span class="cat-spacer"></span><span class="cat-when">{when}</span></div>'
        f'<a href="{_esc(c.get("url") or "#")}" target="_blank" class="cat-headline">'
        f'{_esc(c.get("headline", ""))}</a>'
        f'<div class="cat-facts">{"".join(facts)}</div>'
        f'</div></div>'
    )


def render_catalysts(catalysts: list[dict], empty_hint: str = "") -> None:
    if not catalysts:
        st.markdown(
            f'<div class="cat-empty"><b>No catalysts match these filters.</b><br>{empty_hint}</div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown("\n".join(_render_catalyst_html(c) for c in catalysts), unsafe_allow_html=True)


def render_catalyst_kpis(stats: dict) -> None:
    tiles = (
        ("Events (24h)", stats.get("total", 0)),
        ("High impact", stats.get("high_impact", 0)),
        ("Price confirmed", stats.get("confirmed", 0)),
        ("Tickers", stats.get("tickers", 0)),
    )
    st.markdown(
        '<div class="cat-summary">'
        + "".join(
            f'<div class="cat-kpi"><div class="cat-kpi-value">{value}</div>'
            f'<div class="cat-kpi-label">{label}</div></div>'
            for label, value in tiles
        )
        + "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════
#  Squawk tape — the fastest catalyst information, newest first
# ══════════════════════════════════════════════════════════════════════

# Sources that originate news rather than re-report it. Something arriving from
# one of these is as early as a free feed can be.
PRIMARY_SOURCE_HINTS = (
    "sec", "edgar", "fda", "halt", "business wire", "businesswire",
    "pr newswire", "prnewswire", "globenewswire", "stocktitan", "accesswire",
    "grok squawk",
)


def _is_primary_source(source: str) -> bool:
    lowered = (source or "").lower()
    return any(hint in lowered for hint in PRIMARY_SOURCE_HINTS)


def _age_label(published: datetime) -> tuple[str, str]:
    """Compact age plus a heat class — seconds matter on a squawk tape."""
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - published).total_seconds()))
    if seconds < 60:
        return f"{seconds}s", "hot"
    if seconds < 3600:
        return f"{seconds // 60}m", "warm" if seconds < 900 else ""
    if seconds < 86400:
        return f"{seconds // 3600}h", ""
    return f"{seconds // 86400}d", ""


def _render_squawk_row(c: dict) -> str:
    published = _parse_dt(c["published"]) if isinstance(c.get("published"), str) else c.get("published")
    age, heat = _age_label(published) if published else ("", "")
    ticker = c.get("ticker") or ""
    type_color = c.get("color") or "#8b93b0"

    move = ""
    change = c.get("change_pct")
    if change is not None and abs(change) >= 0.05:
        move = f'<span class="squawk-move {"up" if change > 0 else "down"}">{change:+.1f}%</span>'

    sources = c.get("sources") or []
    source_name = _short_source(sources[0].get("source", "")) if sources else ""
    n = int(c.get("source_count") or 1)
    if n > 1:
        source_name = f"{source_name}+{n - 1}"
    primary = " primary" if sources and _is_primary_source(sources[0].get("source", "")) else ""

    return (
        f'<div class="squawk-row{" fresh" if heat == "hot" else ""}" style="--sq-accent:{type_color}55">'
        f'<span class="squawk-age {heat}">{age}</span>'
        f'<span class="squawk-ticker{"" if ticker else " none"}">{_esc(ticker) if ticker else "—"}</span>'
        f'<span class="squawk-tag" style="background:{type_color}18;color:{type_color}">'
        f'{_esc(c.get("label", ""))}</span>'
        f'<a class="squawk-headline" href="{_esc(c.get("url") or "#")}" target="_blank">'
        f'{_esc(c.get("headline", ""))}</a>'
        f'{move}'
        f'<span class="squawk-src{primary}">{_esc(source_name)}</span>'
        f'</div>'
    )


def render_squawk(catalysts: list[dict]) -> None:
    if not catalysts:
        st.markdown(
            '<div class="cat-empty"><b>Tape is quiet.</b><br>'
            'Nothing has cleared the filter in this window.</div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown("\n".join(_render_squawk_row(c) for c in catalysts), unsafe_allow_html=True)


def source_latency_stats(conn, hours: float = 6) -> dict:
    """How fast each tier is actually delivering, measured on stored events."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT source, COUNT(*) n FROM articles WHERE published >= ? GROUP BY source ORDER BY n DESC",
        (cutoff,),
    ).fetchall()
    primary = sum(r[1] for r in rows if _is_primary_source(r[0]))
    total = sum(r[1] for r in rows) or 1
    newest = conn.execute(
        "SELECT MAX(published) FROM articles WHERE published <= ?",
        (datetime.now(timezone.utc).isoformat(),),
    ).fetchone()[0]
    freshest = 0
    if newest:
        try:
            freshest = max(0, int((datetime.now(timezone.utc) - _parse_dt(newest)).total_seconds()))
        except Exception:
            freshest = 0
    return {
        "sources": len(rows),
        "items": total,
        "primary_pct": round(primary / total * 100),
        "freshest_seconds": freshest,
    }


def render_latency_bar(stats: dict, grok_on: bool) -> None:
    grok_label = "on" if grok_on else "off (set XAI_API_KEY)"
    st.markdown(
        '<div class="latency-bar">'
        f'<span class="latency-chip">newest item <b>{stats["freshest_seconds"]}s</b> ago</span>'
        f'<span class="latency-chip">from primary sources <b>{stats["primary_pct"]}%</b></span>'
        f'<span class="latency-chip">live sources <b>{stats["sources"]}</b></span>'
        f'<span class="latency-chip">items (6h) <b>{stats["items"]}</b></span>'
        f'<span class="latency-chip">Grok X-search <b>{grok_label}</b></span>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_grok_panel() -> None:
    """Ask Grok what is moving a name, using live X and web search.

    RSS can only carry what someone already published; a halt or a leak usually
    shows up on X first. This is the manual version of that lookup — the
    automatic one runs in the refresher when a key is configured.
    """
    configured = grok_mod.available()
    label = "🤖 Ask Grok — why is a stock moving?" if configured else "🤖 Ask Grok (needs XAI_API_KEY)"
    with st.expander(label, expanded=False):
        if not configured:
            st.caption(
                "Set `XAI_API_KEY` in your environment to enable live X and web search. "
                "Grok reads posts and articles as they appear, which is usually ahead of "
                "any RSS feed. Everything else on this page works without it."
            )
            return

        c1, c2, c3 = st.columns([2, 2, 4])
        with c1:
            ticker = st.text_input("Ticker", placeholder="e.g. NVDA", max_chars=6,
                                   key="grok_ticker", label_visibility="collapsed").upper().strip()
        with c2:
            asked = st.button("Explain the move", key="grok_go", use_container_width=True)
        with c3:
            if st.button("Sweep X for breaking events now", key="grok_sweep", use_container_width=True):
                with st.spinner("Searching X and the web..."):
                    items = grok_mod.fetch_squawk(
                        minutes=GROK_SQUAWK_WINDOW_MINUTES, respect_throttle=False
                    )
                    stored = store_news_items(items, "Grok Squawk", "general")
                    refresh_catalysts(with_quotes=False)
                st.success(f"{len(items)} events found, {stored} new on the tape.")

        if asked and ticker:
            with st.spinner(f"Asking Grok about {ticker}..."):
                answer = grok_mod.explain_move(ticker, 0.0, respect_throttle=False)
            if answer.ok:
                st.markdown(answer.text)
                if answer.citations:
                    st.caption("Sources: " + " · ".join(
                        f"[{_short_source(sources_mod.source_for_url(u, 'link'))}]({u})"
                        for u in answer.citations[:6]
                    ))
            else:
                st.warning(f"Grok could not answer: {answer.error}")
        elif asked:
            st.info("Enter a ticker first.")


def render_stat(label, value):
    st.markdown(f'<div class="stat-box"><div class="stat-number">{value}</div><div class="stat-label">{label}</div></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
#  U/D Quality Grading
# ══════════════════════════════════════════════════════════════════════

def grade_ud(ud: UpgradeDowngrade) -> str:
    """Grade analyst action quality: A+ (best) to C (incomplete)."""
    score = 0
    if ud.ticker and ud.ticker != "N/A":
        score += 1
    if ud.firm:
        score += 1
    if ud.new_rating:
        score += 1
    if ud.price_target:
        score += 1
    if ud.action and ud.action not in ("mixed", "reiterated"):
        score += 1
    if score >= 5:
        return "A+"
    if score >= 4:
        return "A"
    if score >= 3:
        return "B"
    return "C"


def _grade_html(grade: str) -> str:
    css = {"A+": "a-plus", "A": "a", "B": "b", "C": "c"}.get(grade, "c")
    return f'<span class="ud-grade ud-grade-{css}">{grade}</span>'


# ══════════════════════════════════════════════════════════════════════
#  Earnings Result Parsing
# ══════════════════════════════════════════════════════════════════════

_EPS_PATTERN = re.compile(
    r'(?:(?:Non-GAAP|GAAP)?\s*EPS\s+(?:of\s+)?\$?([-]?[\d.]+))'
    r'|(?:EPS:\s*\$?([-]?[\d.]+))',
    re.IGNORECASE,
)
_REVENUE_PATTERN = re.compile(
    r'revenue\s+(?:of\s+)?\$?([\d,.]+)\s*(B|M|K)?',
    re.IGNORECASE,
)
_BEAT_MISS_PATTERN = re.compile(
    r'\b(beats?|misses?|missed|topped|exceeded|fell short|in[- ]line)\b',
    re.IGNORECASE,
)


@dataclass
class EarningsResult:
    ticker: str
    title: str
    url: str
    source: str
    published: datetime
    eps: str = ""
    revenue: str = ""
    beat_miss: str = ""  # "beat", "miss", "inline", ""


def parse_earnings_from_article(a: Article) -> EarningsResult | None:
    """Extract earnings data from an earnings-categorized article."""
    if a.category != Category.EARNINGS:
        return None
    text = a.title + " " + a.summary

    # Extract ticker
    ticker = a.tickers[0] if a.tickers else ""
    if not ticker:
        ticker = extract_ticker_from_name(a.title) or ""

    # Extract EPS
    eps = ""
    m = _EPS_PATTERN.search(text)
    if m:
        val = m.group(1) or m.group(2)
        if val:
            eps = f"${val}"

    # Extract revenue
    revenue = ""
    m = _REVENUE_PATTERN.search(text)
    if m:
        val = m.group(1)
        suffix = (m.group(2) or "").upper()
        revenue = f"${val}{suffix}"

    # Detect beat/miss
    beat_miss = ""
    text_lower = text.lower()
    if any(w in text_lower for w in ["beats", "beat", "topped", "exceeded"]):
        beat_miss = "beat"
    elif any(w in text_lower for w in ["misses", "miss", "missed", "fell short"]):
        beat_miss = "miss"
    elif "in-line" in text_lower or "in line" in text_lower:
        beat_miss = "inline"

    # Only return if we extracted something useful
    if eps or revenue or beat_miss or ticker:
        return EarningsResult(
            ticker=ticker, title=a.title, url=a.url,
            source=a.source, published=a.published,
            eps=eps, revenue=revenue, beat_miss=beat_miss,
        )
    return None


def get_earnings_results(conn, hours: int = 48) -> list[EarningsResult]:
    """Get parsed earnings results from recent articles."""
    arts = get_articles(conn, limit=500, category="earnings", hours=hours)
    results = []
    seen = set()
    for a in arts:
        er = parse_earnings_from_article(a)
        if er:
            key = er.title.strip().lower()[:60]
            if key not in seen:
                seen.add(key)
                results.append(er)
    return results


def get_earnings_by_ticker(results: list[EarningsResult]) -> dict[str, list[EarningsResult]]:
    """Group earnings results by ticker."""
    by_ticker: dict[str, list[EarningsResult]] = {}
    for er in results:
        t = er.ticker or "N/A"
        if t not in by_ticker:
            by_ticker[t] = []
        by_ticker[t].append(er)
    return by_ticker


# Breaking news categories — high-impact for stock trading
BREAKING_CATEGORIES = {"earnings", "upgrade", "downgrade", "macro", "m&a", "fda", "ipo"}


def get_breaking_articles(conn, hours: float = 2.0, limit: int = 30) -> list[Article]:
    """Get high-impact articles from the last N hours for the breaking news feed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q = "SELECT * FROM articles WHERE published >= ? ORDER BY published DESC LIMIT ?"
    rows = conn.execute(q, (cutoff, limit * 3)).fetchall()
    arts = []
    for r in rows:
        cat_val = r["category"]
        cat = Category(cat_val) if cat_val in Category._value2member_map_ else Category.GENERAL
        arts.append(Article(
            id=r["id"], title=r["title"], url=r["url"], source=r["source"],
            published=_parse_dt(r["published"]), category=cat,
            tickers=json.loads(r["tickers"]), summary=r["summary"],
            fetched_at=_parse_dt(r["fetched_at"]),
        ))
    # Filter: prioritize high-impact categories, then include recent general news
    breaking = [a for a in arts if a.category.value in BREAKING_CATEGORIES]
    general_recent = [a for a in arts if a.category.value not in BREAKING_CATEGORIES]
    # Combine: all breaking + fill with recent general up to limit
    result = breaking + general_recent
    # Deduplicate + noise filter
    seen, deduped = set(), []
    for a in result:
        key = a.title.strip().lower()[:80]
        if key in seen or _is_noise(a.title, a.category.value, bool(a.tickers), a.source):
            continue
        seen.add(key)
        deduped.append(a)
    return deduped[:limit]


def _render_breaking_item(a: Article) -> str:
    rel = _relative_time(a.published)
    ts = _format_time(a.published, "%H:%M")
    tickers = "".join(f'<span class="breaking-item-ticker">{_esc(t)}</span>' for t in a.tickers[:2])
    cc = CATEGORY_COLORS.get(a.category, "#6b7394")
    cat_html = ""
    if a.category != Category.GENERAL:
        cat_html = f'<span class="breaking-item-cat" style="background:{cc}14;color:{cc};border:1px solid {cc}22">{a.category.value.upper()}</span>'
    src = _short_source(a.source)
    return (
        f'<div class="breaking-item">'
        f'<span class="breaking-item-time">{ts} · {rel}</span>'
        f'<a href="{_esc(a.url)}" target="_blank" class="breaking-item-title">{_esc(a.title)}</a>'
        f'<div class="breaking-item-meta">{tickers} {cat_html} <span class="breaking-item-src">{_esc(src)}</span></div>'
        f'</div>'
    )


def render_breaking_news(articles: list[Article]):
    if not articles:
        st.markdown(
            '<div class="breaking-wrap">'
            '<div class="breaking-header">'
            '<span class="breaking-dot"></span>'
            '<span class="breaking-title">Breaking</span>'
            '<span class="breaking-count">No recent</span>'
            '</div></div>',
            unsafe_allow_html=True,
        )
        return
    count = len(articles)
    html = "\n".join(_render_breaking_item(a) for a in articles)
    st.markdown(
        f'<div class="breaking-wrap">'
        f'<div class="breaking-header">'
        f'<span class="breaking-dot"></span>'
        f'<span class="breaking-title">Breaking</span>'
        f'<span class="breaking-count">{count} · 2h</span>'
        f'</div>'
        f'<div class="breaking-scroll">{html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════
#  Main App
# ══════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="NewsAgent", page_icon="📡", layout="wide", initial_sidebar_state="collapsed")
st.markdown(DARK_CSS, unsafe_allow_html=True)

settings = load_settings()
REFRESH = settings.get("general", {}).get("refresh_interval", 15)
MAX_ART = settings.get("general", {}).get("max_articles", 500)
PRUNE = settings.get("general", {}).get("prune_after_days", 7)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = []
if "refresher_started" not in st.session_state:
    st.session_state.refresher_started = False
if "user_tz" not in st.session_state:
    st.session_state.user_tz = "America/New_York"

conn = get_connection()
init_db(conn)
prune_old_articles(conn, PRUNE)

feeds = load_all_feeds()

if not st.session_state.refresher_started:
    # Do an initial synchronous fetch so articles are available immediately
    # Only the fast tiers on the critical path — the slower aggregators land on
    # the next background pass rather than delaying the first paint.
    _startup_tiers = {fanout_mod.Tier.FLASH, fanout_mod.Tier.FAST}
    fetch_all_feeds(
        [f for f in feeds if fanout_mod.tier_for(f.name, f.category) in _startup_tiers],
        blocking=False,
    )
    prune_catalysts(conn, PRUNE)
    # Quotes are skipped on the first pass so the board paints immediately; the
    # background refresher attaches them (and rescores) moments later.
    refresh_catalysts(with_quotes=False)
    r = FeedRefresher(feeds, interval=REFRESH)
    r.start()
    st.session_state.refresher_started = True
    st.session_state.refresher = r

# ── Header
c1, c2, c3 = st.columns([2, 4, 2])
with c1:
    st.markdown('<div class="newsagent-logo"><span class="pulse"></span>NewsAgent <span>LIVE</span></div>', unsafe_allow_html=True)
with c2:
    if st.session_state.watchlist:
        st.markdown(" ".join(f'<span class="watchlist-chip">{t}</span>' for t in st.session_state.watchlist), unsafe_allow_html=True)
with c3:
    now_local = _to_local(datetime.now(timezone.utc))
    st.markdown(
        f'<div style="text-align:right;padding-top:8px">'
        f'<span style="color:#5c6375;font-size:0.80rem;font-family:var(--font-mono,monospace);font-weight:500">'
        f'{now_local.strftime("%H:%M:%S")}</span>'
        f'<span style="color:#3d4255;font-size:0.68rem;margin-left:6px;font-weight:600;letter-spacing:0.5px">{_tz_abbrev()}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ── Sidebar
with st.sidebar:
    st.markdown("### Timezone")
    tz_labels = list(TIMEZONE_OPTIONS.keys())
    tz_values = list(TIMEZONE_OPTIONS.values())
    current_idx = tz_values.index(st.session_state.user_tz) if st.session_state.user_tz in tz_values else 0
    selected_tz_label = st.selectbox(
        "Display timezone",
        tz_labels,
        index=current_idx,
        key="tz_selector",
        label_visibility="collapsed",
    )
    new_tz = TIMEZONE_OPTIONS[selected_tz_label]
    if new_tz != st.session_state.user_tz:
        st.session_state.user_tz = new_tz
        st.rerun()
    st.caption(f"Current: {_to_local(datetime.now(timezone.utc)).strftime('%H:%M:%S %Z')}")
    st.divider()
    st.markdown("### Watchlist")
    new_t = st.text_input("Add ticker", placeholder="e.g. AAPL", max_chars=5, key="nt").upper().strip()
    if new_t and st.button("Add", key="add_t"):
        if new_t not in st.session_state.watchlist:
            st.session_state.watchlist.append(new_t)
            st.rerun()
    for i, t in enumerate(st.session_state.watchlist):
        c1, c2 = st.columns([3, 1])
        c1.markdown(f'<span class="watchlist-chip">{t}</span>', unsafe_allow_html=True)
        if c2.button("X", key=f"rm_{i}"):
            st.session_state.watchlist.pop(i); st.rerun()
    st.divider()
    st.markdown("### Stats")
    _cstats = catalyst_stats(conn, hours=24)
    render_stat("Catalysts (24h)", _cstats.get("total", 0))
    render_stat("High Impact", _cstats.get("high_impact", 0))
    render_stat("Articles Cached", get_article_count(conn))
    sc = get_source_counts(conn)
    if sc:
        render_stat("Active Sources", len(sc))
    lf = get_last_fetch_time()
    if lf:
        st.caption(f"Last fetch: {_format_time(lf, '%H:%M:%S')} {_tz_abbrev()}")
    errs = get_fetch_errors()
    if errs:
        with st.expander(f"Feed Errors ({len(errs)})"):
            for n, e in errs.items():
                st.caption(f"**{n}**: {e[:80]}")

# ── Main layout: Tabs (left) + Breaking News (right)
main_col, breaking_col = st.columns([3, 1], gap="medium")


@st.fragment(run_every=timedelta(seconds=REFRESH))
def frag_live():
    fc = get_connection()
    c1, c2, c3 = st.columns([5, 2, 2])
    with c1:
        sq = st.text_input("Search", placeholder="Search headlines, tickers, keywords...", label_visibility="collapsed", key="sf")
    with c2:
        sc = st.selectbox("Cat", ["all"] + [c.value for c in Category], key="cf", label_visibility="collapsed")
    with c3:
        st2 = st.selectbox("Ticker", ["All"] + st.session_state.watchlist, key="tf", label_visibility="collapsed")
    tf = st2 if st2 != "All" else None
    # If search looks like a ticker (all uppercase, short), also filter by ticker
    search_ticker = None
    if sq and sq.strip().upper() == sq.strip() and 1 <= len(sq.strip()) <= 5 and sq.strip().isalpha():
        search_ticker = sq.strip().upper()
    arts = get_articles(fc, limit=MAX_ART, category=sc if sc != "all" else None, ticker=tf, search=sq if sq else None)
    # If searching by possible ticker and few results, also try ticker filter
    if search_ticker and len(arts) < 5:
        ticker_arts = get_articles(fc, limit=MAX_ART, category=sc if sc != "all" else None, ticker=search_ticker)
        seen_ids = {a.id for a in arts}
        for a in ticker_arts:
            if a.id not in seen_ids:
                arts.append(a)
        arts.sort(key=lambda a: a.published.replace(tzinfo=timezone.utc) if a.published.tzinfo is None else a.published, reverse=True)
    # Deduplicate count for display (matching render_articles logic)
    seen_t = set()
    dedup_count = 0
    for a in arts:
        k = a.title.strip().lower()[:80]
        if k in seen_t or _is_noise(a.title, a.category.value, bool(a.tickers), a.source):
            continue
        seen_t.add(k)
        dedup_count += 1
    lf = get_last_fetch_time()
    if lf:
        lf_time = _format_time(lf, "%H:%M:%S")
        lf_rel = _relative_time(lf)
        lf_str = f"Last fetch: {lf_time} {_tz_abbrev()} ({lf_rel})"
    else:
        lf_str = "Fetching first batch..."
    st.markdown(
        f'<div class="refresh-bar">'
        f'<span><span class="refresh-dot"></span>{dedup_count} articles (last 48h)</span>'
        f'<span>{lf_str} · auto-refresh {REFRESH}s</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    render_articles(arts)
    fc.close()


@st.fragment(run_every=timedelta(seconds=REFRESH))
def frag_ud():
    fc = get_connection()
    # Refresh indicator
    lf = get_last_fetch_time()
    lf_str = f"{_format_time(lf, '%H:%M:%S')} {_tz_abbrev()}" if lf else "waiting..."
    st.markdown(f'<div class="refresh-bar"><span><span class="refresh-dot"></span>Auto-refreshing every {REFRESH}s</span><span>Last fetch: {lf_str}</span></div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        tf = st.text_input("Filter by ticker", placeholder="e.g. NVDA", key="udf").upper().strip()
    with c2:
        sq = st.text_input("Search", placeholder="Search firm, ticker, action...", key="ud_search", label_visibility="collapsed")
    with c3:
        if st.button("Reprocess", key="reprocess_ud", help="Re-analyze all articles with improved parser"):
            rc = get_connection()
            n = reprocess_upgrades_downgrades(rc)
            rc.close()
            st.toast(f"Reprocessed {n} analyst actions")
    uds = get_upgrades_downgrades(fc, limit=300, ticker=tf if tf else None, search=sq if sq else None)

    # Split into upgrade / downgrade / mixed
    upgrades = [u for u in uds if u.action in ("upgrade", "initiated", "raises_pt")]
    downgrades = [u for u in uds if u.action in ("downgrade", "lowers_pt")]
    mixed_all = [u for u in uds if u.action not in ("upgrade", "initiated", "raises_pt", "downgrade", "lowers_pt")]

    # Split mixed into "detailed" (has firm/rating/PT) and "unresolved" (bare ticker only)
    mixed_detailed = [u for u in mixed_all if u.firm or u.new_rating or u.price_target]
    mixed_bare = [u for u in mixed_all if not u.firm and not u.new_rating and not u.price_target]

    total = len(uds)
    # Grade counts
    grades = {g: 0 for g in ("A+", "A", "B", "C")}
    for u in uds:
        grades[grade_ud(u)] += 1
    grade_str = " · ".join(f'{_grade_html(g)} {c}' for g, c in grades.items() if c > 0)
    st.markdown(
        f'<div style="color:#555;font-size:0.78rem;padding:4px 0">'
        f'{total} analyst actions · {len(upgrades)} upgrades · {len(downgrades)} downgrades · '
        f'{len(mixed_detailed)} mixed · {grade_str}</div>',
        unsafe_allow_html=True,
    )

    col_up, col_dn, col_mix = st.columns(3)
    with col_up:
        st.markdown(f'<div class="col-header col-header-up">▲ UPGRADES ({len(upgrades)})</div>', unsafe_allow_html=True)
        if upgrades:
            render_uds(upgrades, scrollable=True)
        else:
            st.markdown('<div style="color:#555;font-size:0.82rem;padding:1rem;text-align:center">None yet</div>', unsafe_allow_html=True)
    with col_dn:
        st.markdown(f'<div class="col-header col-header-dn">▼ DOWNGRADES ({len(downgrades)})</div>', unsafe_allow_html=True)
        if downgrades:
            render_uds(downgrades, scrollable=True)
        else:
            st.markdown('<div style="color:#555;font-size:0.82rem;padding:1rem;text-align:center">None yet</div>', unsafe_allow_html=True)
    with col_mix:
        st.markdown(f'<div class="col-header col-header-mix">● MIXED ({len(mixed_detailed)})</div>', unsafe_allow_html=True)
        if mixed_detailed:
            render_uds(mixed_detailed, scrollable=True)
        else:
            st.markdown('<div style="color:#555;font-size:0.82rem;padding:1rem;text-align:center">None yet</div>', unsafe_allow_html=True)

    # Show bare/unresolved entries in a collapsed expander
    if mixed_bare:
        with st.expander(f"Unresolved analyst mentions ({len(mixed_bare)}) — ticker only, no firm/rating details"):
            render_uds(mixed_bare, scrollable=True)

    if not uds:
        st.markdown('<div style="text-align:center;color:#555;padding:3rem 0">No upgrades/downgrades detected yet.<br><span style="font-size:0.8rem">Monitoring analyst feeds...</span></div>', unsafe_allow_html=True)
    fc.close()


@st.fragment(run_every=timedelta(seconds=max(5, REFRESH // 2)))
def frag_squawk():
    """The tape: every catalyst as it lands, newest first, age in seconds."""
    fc = get_connection()

    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    with c1:
        query = st.text_input(
            "Filter tape", placeholder="Ticker, company or headline...",
            label_visibility="collapsed", key="sq_q",
        ).strip()
    with c2:
        window = st.selectbox("Window", ["2h", "6h", "30m", "24h"], key="sq_win", label_visibility="collapsed")
    with c3:
        floor = st.selectbox(
            "Filter", ["Catalysts only", "High impact only", "Everything scored"],
            key="sq_floor", label_visibility="collapsed",
        )
    with c4:
        watch_only = st.checkbox("Watchlist only", key="sq_watch")

    hours = {"30m": 0.5, "2h": 2, "6h": 6, "24h": 24}[window]
    min_score = {"Catalysts only": 25, "High impact only": 60, "Everything scored": 0}[floor]

    render_latency_bar(source_latency_stats(fc, hours=6), grok_mod.available())
    render_grok_panel()

    catalysts = get_catalysts(
        fc, hours=hours, min_score=min_score,
        search=query or None,
        tickers=(st.session_state.watchlist or None) if watch_only else None,
        order="time", limit=200,
    )

    last_run = get_last_catalyst_run()
    scanned = f"{_relative_time(last_run)}" if last_run else "starting..."
    st.markdown(
        f'<div class="refresh-bar">'
        f'<span><span class="refresh-dot"></span>{len(catalysts)} events on the tape · last {window}</span>'
        f'<span>scanned {scanned} · tiers: flash 10s / fast 45s / steady 180s</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    render_squawk(catalysts)
    fc.close()


@st.fragment(run_every=timedelta(seconds=REFRESH))
def frag_cat():
    """Catalyst Board — every detected event, ranked by how much it should move the stock."""
    fc = get_connection()

    group_labels = {
        "All": None,
        "Deals": CatalystGroup.DEAL.value,
        "Clinical": CatalystGroup.CLINICAL.value,
        "Capital": CatalystGroup.CAPITAL.value,
        "Operating": CatalystGroup.OPERATING.value,
        "Legal": CatalystGroup.LEGAL.value,
        "Structural": CatalystGroup.STRUCTURAL.value,
        "Analyst": CatalystGroup.ANALYST.value,
        "Macro": CatalystGroup.MACRO.value,
    }

    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    with c1:
        query = st.text_input(
            "Search catalysts", placeholder="Ticker, company or headline...",
            label_visibility="collapsed", key="cat_q",
        ).strip()
    with c2:
        group_choice = st.selectbox("Type", list(group_labels), key="cat_group", label_visibility="collapsed")
    with c3:
        direction = st.selectbox(
            "Direction", ["Any direction", "bullish", "bearish", "neutral"],
            key="cat_dir", label_visibility="collapsed",
        )
    with c4:
        sort = st.selectbox(
            "Sort", ["Impact score", "Newest first", "Biggest move"],
            key="cat_sort", label_visibility="collapsed",
        )

    f1, f2, f3 = st.columns([3, 2, 2])
    with f1:
        min_score = st.slider("Minimum impact score", 0, 90, 30, step=5, key="cat_min")
    with f2:
        window = st.selectbox("Window", ["24h", "48h", "6h", "7d"], key="cat_hours", label_visibility="collapsed")
    with f3:
        confirmed_only = st.checkbox("Price-confirmed only", key="cat_conf")
        watch_only = st.checkbox("Watchlist only", key="cat_watch")

    hours = {"6h": 6, "24h": 24, "48h": 48, "7d": 168}[window]
    order = {"Impact score": "score", "Newest first": "time", "Biggest move": "move"}[sort]
    watchlist = st.session_state.watchlist if watch_only else None

    render_catalyst_kpis(catalyst_stats(fc, hours=hours))

    catalysts = get_catalysts(
        fc,
        hours=hours,
        min_score=min_score,
        groups=[group_labels[group_choice]] if group_labels[group_choice] else None,
        direction=None if direction == "Any direction" else direction,
        search=query or None,
        tickers=watchlist or None,
        confirmed_only=confirmed_only,
        order=order,
        limit=120,
    )

    last_run = get_last_catalyst_run()
    if last_run:
        status = f"Scanned {_format_time(last_run, '%H:%M:%S')} {_tz_abbrev()} ({_relative_time(last_run)})"
    else:
        status = "Scanning feeds..."
    st.markdown(
        f'<div class="refresh-bar">'
        f'<span><span class="refresh-dot"></span>{len(catalysts)} catalysts · score {min_score}+ · last {window}</span>'
        f'<span>{status}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    render_catalysts(
        catalysts,
        empty_hint="Lower the minimum score, widen the window, or clear the filters above.",
    )
    fc.close()


@st.fragment(run_every=timedelta(seconds=REFRESH * 2))
def frag_by_symbol():
    fc = get_connection()
    all_tickers = get_all_tickers(fc)
    c1, c2 = st.columns([3, 1])
    with c1:
        sym_search = st.text_input("Search symbol", placeholder="Type ticker (e.g. AAPL, NVDA)...", key="sym_search", label_visibility="collapsed").upper().strip()
    with c2:
        max_per = st.selectbox("Articles per symbol", [5, 10, 20, 50], index=1, key="sym_max")
    if sym_search:
        matching = [t for t in all_tickers if sym_search in t]
        if not matching:
            mapped = extract_ticker_from_name(sym_search)
            if mapped:
                matching = [mapped]
    else:
        matching = all_tickers[:30]
    if not matching:
        st.markdown('<div style="color:#555;text-align:center;padding:2rem">No articles with tickers found.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="color:#555;font-size:0.78rem;padding:4px 0">{len(matching)} symbols · showing up to {max_per} articles each</div>', unsafe_allow_html=True)
        by_ticker = get_articles_by_ticker(fc, limit_per_ticker=max_per)
        for ticker in matching:
            arts = by_ticker.get(ticker, [])
            if not arts:
                arts = get_articles(fc, limit=max_per, ticker=ticker)
            if arts:
                ud_count = sum(1 for a in arts if a.category.value in ("upgrade", "downgrade"))
                ud_badge = f" ({ud_count} U/D)" if ud_count else ""
                art_word = "article" if len(arts) == 1 else "articles"
                with st.expander(f"**{ticker}** — {len(arts)} {art_word}{ud_badge}", expanded=False):
                    render_articles(arts)
            else:
                st.markdown(f'<div style="color:#555;font-size:0.82rem;padding:0.3rem 0.8rem">{ticker} — no articles</div>', unsafe_allow_html=True)
    fc.close()


@st.fragment(run_every=timedelta(seconds=REFRESH))
def frag_earnings():
    fc = get_connection()
    results = get_earnings_results(fc, hours=48)
    by_ticker = get_earnings_by_ticker(results)

    lf = get_last_fetch_time()
    lf_str = f"{_format_time(lf, '%H:%M:%S')} {_tz_abbrev()}" if lf else "loading..."
    st.markdown(
        f'<div class="refresh-bar">'
        f'<span><span class="refresh-dot"></span>{len(results)} earnings reports (last 48h)</span>'
        f'<span>Last fetch: {lf_str} · auto-refresh {REFRESH}s</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Filter controls
    c1, c2 = st.columns([3, 1])
    with c1:
        eq = st.text_input("Search ticker or company", placeholder="e.g. AAPL, LULU, Tesla...", key="eq", label_visibility="collapsed")
    with c2:
        ef = st.selectbox("Filter", ["All", "Beats Only", "Misses Only", "Has EPS"], key="ef", label_visibility="collapsed")

    # Apply filters
    filtered = results
    if eq:
        q = eq.strip().upper()
        filtered = [r for r in filtered if q in r.ticker or q.lower() in r.title.lower()]
    if ef == "Beats Only":
        filtered = [r for r in filtered if r.beat_miss == "beat"]
    elif ef == "Misses Only":
        filtered = [r for r in filtered if r.beat_miss == "miss"]
    elif ef == "Has EPS":
        filtered = [r for r in filtered if r.eps]

    if not filtered:
        st.markdown('<div style="text-align:center;color:#555;padding:2rem">No earnings reports matching filter.</div>', unsafe_allow_html=True)
        fc.close()
        return

    # Render earnings cards
    html_parts = []
    for er in filtered:
        ts = _format_time(er.published, "%H:%M")
        rel = _relative_time(er.published)
        src = _short_source(er.source)
        ticker_html = f'<span class="earnings-ticker">{_esc(er.ticker)}</span>' if er.ticker else ""
        # Beat/miss indicator
        if er.beat_miss == "beat":
            bm_html = '<span class="earnings-metric earnings-beat">▲ BEAT</span>'
        elif er.beat_miss == "miss":
            bm_html = '<span class="earnings-metric earnings-miss">▼ MISS</span>'
        elif er.beat_miss == "inline":
            bm_html = '<span class="earnings-metric earnings-neutral">● IN-LINE</span>'
        else:
            bm_html = ""
        # Metrics
        metrics = []
        if er.eps:
            metrics.append(f'<span class="earnings-metric earnings-neutral">EPS {_esc(er.eps)}</span>')
        if er.revenue:
            metrics.append(f'<span class="earnings-metric earnings-neutral">Rev {_esc(er.revenue)}</span>')
        if bm_html:
            metrics.append(bm_html)
        metrics_html = " ".join(metrics)
        html_parts.append(
            f'<div class="earnings-card">'
            f'<div class="earnings-card-header">'
            f'{ticker_html}'
            f'<span class="earnings-time">{ts} · {rel}</span>'
            f'<span class="earnings-src">{_esc(src)}</span>'
            f'</div>'
            f'<a href="{_esc(er.url)}" target="_blank" class="earnings-title">{_esc(er.title)}</a>'
            f'<div class="earnings-metrics">{metrics_html}</div>'
            f'</div>'
        )
    st.markdown("\n".join(html_parts), unsafe_allow_html=True)

    # By-ticker summary
    tickers_with_data = {t: ers for t, ers in by_ticker.items() if t and t != "N/A" and len(ers) >= 2}
    if tickers_with_data:
        st.markdown(f'<div style="color:#555;font-size:0.78rem;padding:8px 0 4px">Stocks with multiple earnings mentions:</div>', unsafe_allow_html=True)
        for t, ers in sorted(tickers_with_data.items(), key=lambda x: -len(x[1])):
            beats = sum(1 for e in ers if e.beat_miss == "beat")
            misses = sum(1 for e in ers if e.beat_miss == "miss")
            badge = ""
            if beats:
                badge += f' <span class="earnings-beat">▲{beats}</span>'
            if misses:
                badge += f' <span class="earnings-miss">▼{misses}</span>'
            with st.expander(f"**{t}** — {len(ers)} reports{badge}", expanded=False):
                for er in ers:
                    cols = []
                    if er.eps:
                        cols.append(f"EPS {er.eps}")
                    if er.revenue:
                        cols.append(f"Rev {er.revenue}")
                    if er.beat_miss:
                        cols.append(er.beat_miss.upper())
                    detail = " · ".join(cols) if cols else ""
                    st.markdown(f"- [{er.title}]({er.url}) {detail}")
    fc.close()


@st.fragment(run_every=timedelta(seconds=REFRESH))
def frag_all_news():
    fc = get_connection()
    c1, c2, c3 = st.columns([5, 2, 2])
    with c1:
        sq = st.text_input("Search", placeholder="Search all news...", label_visibility="collapsed", key="an_sf")
    with c2:
        sc = st.selectbox("Cat", ["all"] + [c.value for c in Category], key="an_cf", label_visibility="collapsed")
    with c3:
        st2 = st.selectbox("Ticker", ["All"] + st.session_state.watchlist, key="an_tf", label_visibility="collapsed")
    tf = st2 if st2 != "All" else None
    arts = get_articles(fc, limit=MAX_ART, category=sc if sc != "all" else None, ticker=tf, search=sq if sq else None)
    # Deduplicate count (no noise filter)
    seen_t = set()
    ct = 0
    for a in arts:
        k = a.title.strip().lower()[:80]
        if k not in seen_t:
            seen_t.add(k)
            ct += 1
    lf = get_last_fetch_time()
    lf_str = f"Last fetch: {_format_time(lf, '%H:%M:%S')} {_tz_abbrev()}" if lf else "Fetching..."
    st.markdown(
        f'<div class="refresh-bar">'
        f'<span><span class="refresh-dot"></span>{ct} articles — unfiltered (last 48h)</span>'
        f'<span>{lf_str} · auto-refresh {REFRESH}s</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    render_articles(arts, filtered=False)
    fc.close()


@st.fragment(run_every=timedelta(seconds=REFRESH))
def frag_breaking():
    fc = get_connection()
    breaking_arts = get_breaking_articles(fc, hours=2.0, limit=25)
    render_breaking_news(breaking_arts)
    fc.close()


# ── Render layout
with main_col:
    tab0, tab1, tab2, tab6, tab3, tab5, tab7, tab4, tab8 = st.tabs(["🔊 Squawk", "📰 Live Feed", "📊 U/D Ratings", "💰 Earnings", "⚡ Catalyst Board", "🏷️ Symbols", "📋 All News", "📡 Feeds", "🤖 Discord"])
    with tab0:
        frag_squawk()
    with tab1:
        frag_live()
    with tab2:
        frag_ud()
    with tab6:
        frag_earnings()
    with tab3:
        frag_cat()
    with tab5:
        frag_by_symbol()
    with tab7:
        frag_all_news()
    with tab4:
        st.markdown("### Default Feeds")
        custom_names = {cf.name for cf in load_custom_feeds_from_db()}
        dfeeds = [f for f in feeds if f.name not in custom_names]
        errs = get_fetch_errors()
        for f in dfeeds:
            er = errs.get(f.name)
            c1, c2 = st.columns([4, 1])
            with c1:
                icon = "🔴" if er else ("🟢" if f.enabled else "⚪")
                st.markdown(f"{icon} **{f.name}**  \n`{f.url}`")
            with c2:
                st.markdown(f"*{f.category}*")
            if er:
                st.caption(f"Error: {er[:100]}")
        st.divider()
        st.markdown("### Custom Feeds")
        cfs = load_custom_feeds_from_db()
        if cfs:
            for cf in cfs:
                c1, c2, c3 = st.columns([3, 1, 1])
                with c1:
                    st.markdown(f"**{cf.name}**  \n`{cf.url}`")
                with c2:
                    ns = st.checkbox("Enabled", value=cf.enabled, key=f"cft_{cf.name}")
                    if ns != cf.enabled:
                        cn = get_connection(); toggle_custom_feed(cn, cf.name, ns); cn.close(); st.rerun()
                with c3:
                    if st.button("Remove", key=f"cfd_{cf.name}"):
                        cn = get_connection(); delete_custom_feed(cn, cf.name); cn.close(); st.rerun()
        else:
            st.caption("No custom feeds added yet.")
        st.divider()
        st.markdown("### Add Custom Feed")
        with st.form("add_feed"):
            c1, c2 = st.columns(2)
            with c1:
                fn = st.text_input("Feed Name", placeholder="My Custom Feed")
            with c2:
                fc = st.selectbox("Category", ["general", "upgrades_downgrades", "fda", "filings", "crypto"])
            fu = st.text_input("RSS URL", placeholder="https://example.com/feed.xml")
            if st.form_submit_button("Add Feed"):
                if fn and fu:
                    cn = get_connection(); save_custom_feed(cn, fn, fu, fc, True); cn.close()
                    st.success(f"Added: {fn}")
                    if hasattr(st.session_state, "refresher"):
                        st.session_state.refresher.update_feeds(load_all_feeds())
                    st.rerun()
                else:
                    st.error("Fill in both name and URL.")
    with tab8:
        st.markdown("### 🤖 Discord Integration")
        st.caption(
            "Push market news to Discord, routed by category. In Discord: "
            "**Channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL**, "
            "then paste one URL per category below. New articles are delivered to each "
            "channel as they arrive (last 30 min only, so you never get a backlog flood)."
        )

        dconn = get_connection()
        routes = get_discord_routes(dconn)
        dconn.close()
        cats = [c.value for c in Category]
        configured = sum(1 for c in cats if routes.get(c, {}).get("webhook_url"))
        disabled_ct = sum(1 for c in cats if routes.get(c, {}).get("disabled"))

        s1, s2, s3 = st.columns(3)
        with s1:
            render_stat("Categories Routed", configured)
        with s2:
            render_stat("Total Categories", len(cats))
        with s3:
            render_stat("Auto-Disabled", disabled_ct)

        if disabled_ct:
            st.warning(
                f"{disabled_ct} route(s) auto-disabled after repeated delivery failures "
                "(deleted webhook?). Re-save the webhook URL to re-enable."
            )

        st.divider()
        for cat in cats:
            r = routes.get(cat, {})
            url = r.get("webhook_url", "")
            if r.get("disabled"):
                badge = "🔴"
            elif url and r.get("enabled"):
                badge = "🟢"
            elif url:
                badge = "🟡"
            else:
                badge = "⚪"
            with st.expander(f"{badge}  {cat}", expanded=False):
                new_url = st.text_input(
                    "Webhook URL",
                    value=url,
                    key=f"dc_url_{cat}",
                    placeholder="https://discord.com/api/webhooks/...",
                    type="password",
                )
                b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
                with b1:
                    if st.button("Save", key=f"dc_save_{cat}"):
                        if new_url.strip():
                            cn = get_connection(); save_discord_route(cn, cat, new_url, True); cn.close()
                            st.success("Saved"); st.rerun()
                        else:
                            st.error("Enter a webhook URL")
                with b2:
                    if st.button("Test", key=f"dc_test_{cat}"):
                        target = new_url.strip() or url
                        if target:
                            ok, msg = discord_test_send(target, cat)
                            (st.success if ok else st.error)(msg)
                        else:
                            st.error("Enter a webhook URL first")
                with b3:
                    if url and st.button("Remove", key=f"dc_del_{cat}"):
                        cn = get_connection(); delete_discord_route(cn, cat); cn.close(); st.rerun()
                with b4:
                    if url:
                        en = st.checkbox("Enabled", value=bool(r.get("enabled")), key=f"dc_en_{cat}")
                        if en != bool(r.get("enabled")):
                            cn = get_connection(); set_discord_route_enabled(cn, cat, en); cn.close(); st.rerun()
                        if r.get("fail_count"):
                            st.caption(f"⚠️ {r.get('fail_count')} recent delivery failure(s)")

        st.divider()
        st.caption(
            "Tip: leave a category unset and its articles route to your **general** webhook "
            "(if set). Delivery is performed by the backend service — it must be running "
            "(`uvicorn backend.main:app`). Webhook URLs are stored locally and never committed."
        )

with breaking_col:
    frag_breaking()

conn.close()
