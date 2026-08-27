"""Ticker extraction, categorization, and company name mapping.

Extracted from app.py lines 183-413 + src/newsagent/parser.py.
This is the enhanced version from app.py with the extended exclusion list
and company-to-ticker mapping.
"""

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from ..models.schemas import Category

# ──────────────────────────────────────────────────────────────
#  Ticker Exclusions — extended list from app.py lines 183-289
# ──────────────────────────────────────────────────────────────

TICKER_EXCLUSIONS = {
    # Single letters
    "A", "B", "C", "D", "E", "G", "H", "I", "J", "K", "L", "M", "N", "O",
    "P", "Q", "R", "S", "U", "W", "X", "Y", "Z",
    # 2-letter common words
    "AM", "PM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "AD", "AG", "AH", "AW", "AX", "EM", "EX", "HA", "HI", "HO",
    "LA", "LO", "MA", "OH", "OW", "OX", "PA", "PI", "RE", "TA",
    # 3-letter common words / abbreviations
    "CEO", "CFO", "COO", "CTO", "FDA", "SEC", "FED", "GDP", "IPO", "ETF",
    "NYSE", "API", "CPI", "PPI", "DOJ", "EPA", "FBI", "CIA", "NSA",
    "IRS", "IMF", "WHO", "CDC", "NIH", "MIT", "IBM", "LLC", "INC", "LTD",
    "AGO", "ACE", "ACT", "ADD", "AGE", "AID", "AIM", "AIR", "ALL", "AND",
    "ANY", "APE", "ARC", "ARE", "ARK", "ART", "ASK", "ATE", "AWE",
    "BAD", "BAG", "BAN", "BAR", "BAT", "BED", "BET", "BID", "BIG", "BIT",
    "BOX", "BOY", "BUS", "BUT", "BUY", "CAB", "CAN", "CAP", "CAR", "COP",
    "CUP", "CUT", "DAD", "DAM", "DAY", "DID", "DIG", "DIP", "DOG", "DOT",
    "DRY", "DUE", "DUG", "EAR", "EAT", "EGG", "END", "ERA", "EVE", "EYE",
    "FAD", "FAN", "FAR", "FAT", "FAX", "FEE", "FEW", "FIG", "FIN",
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
    # Financial / news jargon
    "EST", "PST", "CST", "MST", "UTC", "RSS", "USA", "UK",
    "EV", "TV", "PE", "Q1", "Q2", "Q3", "Q4", "PT", "SA", "RBC", "BUY",
    "IRA", "CAD", "EUR", "GBP", "JPY", "CNY", "AUD", "NZD", "CHF",
    "ESG", "APY", "APR", "YTD", "MTD", "QTD", "TTM", "NAV", "AUM",
    "HOME", "LOAN", "BANK", "BOND", "CASH", "DEBT", "FUND", "GAIN",
    "GOLD", "REIT", "RISK", "SAFE", "SAVE", "SPAC", "SWAP", "WAGE",
    "BEAR", "BULL", "BUMP", "BURN", "BUST", "CHIP", "CORE", "COST",
    "DATA", "DROP", "DUMP", "EARN", "EDGE", "FARE", "FEAR", "FIRM",
    "FLAT", "FLOW", "FOOD", "FUEL", "HIKE", "JOBS", "JUMP",
    "LAND", "LEAD", "LEAN", "LEVY", "LIEN", "MISS", "PARE", "PEAK",
    "POLL", "PORT", "PURE", "RACE", "RAID", "RALLY", "RANK",
    "REPO", "RULE", "RUSH", "SEED", "SINK", "SLIP", "SLOW", "SNAP",
    "SOAR", "SOLD", "SPAN", "SPEC", "SPIN", "SPOT", "SPUR", "STAY",
    "STEM", "STOCK", "SURGE", "SWEEP", "SWING", "TECH", "TERM",
    "TICK", "TIER", "TOLL", "TRIM", "UNIT", "VETO", "VOID", "WARN",
    "WARY", "WEAK", "WRAP", "YIELD",
    # News / article words
    "AMID", "EYES", "FACE", "FILE", "FORM", "HITS", "NEAR",
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
    # Organizations / abbreviations
    "NATO", "CNBC", "NBC", "CBS", "ABC", "CNN", "BBC", "PBS", "NPR",
    "GOP", "DNC", "NFL", "NBA", "NHL", "MLB", "FIFA", "UEFA", "NCAA",
    "OPEC", "ASEAN", "EU", "UN", "USDA",
    "EVP", "SVP", "AVP", "VP", "MD", "CD", "DVD", "USB", "CPU", "GPU",
    "ROM", "SSD", "HDD", "LED", "LCD", "PDF", "URL", "HTML",
    "FOMC", "FDIC", "CFPB", "OCC", "FINRA", "SIPC", "CFTC",
    "MSCI", "FTSE", "DAX", "IBEX", "NIFTY", "HANG",
    # Common false-positive tickers
    "FEOC", "NBP", "GTC", "OTC", "ADR", "ADS",
    "SHS", "PFD", "DEP", "SER", "SUV", "RSI",
    "USD", "UST", "BPS", "PCT", "YOY", "MOM", "QOQ", "DCF", "EBIT",
    "WACC", "ROE", "ROI", "ROA", "EPS", "FFO", "AFFO",
    "GAAP", "EBITDA", "CAPEX", "SGA", "COGS", "FCF", "OCF",
    "MACD", "SMA", "EMA", "ATH", "ATL", "DMA",
    # Financial terms
    "FY",
}

TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b')

# ──────────────────────────────────────────────────────────────
#  Company Name → Ticker Mapping (from app.py lines 294-392)
# ──────────────────────────────────────────────────────────────

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
    "lululemon": "LULU",
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

# ──────────────────────────────────────────────────────────────
#  Category Keywords (enhanced from app.py lines 655-726)
# ──────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────
#  Core extraction functions
# ──────────────────────────────────────────────────────────────

def make_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def extract_tickers(text: str) -> list[str]:
    """Extract stock ticker symbols from text."""
    matches = TICKER_PATTERN.findall(text)
    tickers, seen = [], set()
    for m in matches:
        if m not in TICKER_EXCLUSIONS and m not in seen:
            tickers.append(m)
            seen.add(m)
    return tickers[:10]


def extract_ticker_from_name(text: str) -> str | None:
    """Try to find a stock ticker by matching company names in the text."""
    text_lower = text.lower()
    # Strip financial "target" phrases to avoid "target" → TGT false positives
    text_lower = re.sub(
        r'\bprice\s+target\b'
        r'|\btarget\s+price\b'
        r'|\btarget\s*(?:raised|lowered|cut|bumped|set|hiked|increased|decreased)\b'
        r'|\b(?:raises?|lowers?|cuts?|sets?|hikes?|increases?|decreases?)\s+(?:(?:stock|price)\s+)*target\b'
        r'|\btarget\s+(?:to|of|at|:)\s*\$',
        '', text_lower
    )
    for name, ticker in sorted(COMPANY_TO_TICKER.items(), key=lambda x: -len(x[0])):
        if re.search(r'\b' + re.escape(name) + r'\b', text_lower):
            return ticker
    return None


def _kw_match(text: str, keyword: str) -> bool:
    """Match keyword with word boundaries for short keywords."""
    if len(keyword) <= 4:
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
    return keyword in text


def _detect_ud_action(title: str, summary: str) -> str | None:
    """Detect upgrade/downgrade action with context-aware logic."""
    text_lower = (title + " " + summary).lower()
    title_lower = title.lower()

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


def categorize(title: str, summary: str, feed_category: str) -> Category:
    """Categorize an article based on title, summary, and feed category."""
    text = (title + " " + summary).lower()

    if feed_category == "upgrades_downgrades":
        action = _detect_ud_action(title, summary)
        if action in ("downgrade", "lowers_pt"):
            return Category.DOWNGRADE
        if action in ("upgrade", "initiated", "raises_pt"):
            return Category.UPGRADE
        return Category.UPGRADE
    if feed_category == "fda":
        return Category.FDA
    if feed_category == "filings":
        return Category.FILING
    if feed_category == "earnings":
        return Category.EARNINGS

    has_up = any(_kw_match(text, kw) for kw in CATEGORY_KEYWORDS[Category.UPGRADE])
    has_dn = any(_kw_match(text, kw) for kw in CATEGORY_KEYWORDS[Category.DOWNGRADE])
    if has_up and has_dn:
        return Category.UPGRADE
    if has_dn:
        return Category.DOWNGRADE
    if has_up:
        return Category.UPGRADE

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if cat in (Category.UPGRADE, Category.DOWNGRADE):
            continue
        if any(_kw_match(text, kw) for kw in keywords):
            return cat
    return Category.GENERAL


def parse_published_date(entry: dict) -> datetime:
    """Parse publication date from RSS entry."""
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
    """Strip HTML tags and return plain text."""
    if not raw:
        return ""
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)[:500]


def parse_entry(entry: dict, feed_name: str, feed_category: str) -> dict:
    """Parse a feedparser entry into an article dict."""
    title = entry.get("title", "No title")
    url = entry.get("link", "")
    summary = clean_html(entry.get("summary", entry.get("description", "")))
    published = parse_published_date(entry)
    category = categorize(title, summary, feed_category)
    tickers = extract_tickers(title + " " + summary)

    return {
        "id": make_article_id(url),
        "title": title,
        "url": url,
        "source": feed_name,
        "published": published,
        "category": category.value,
        "tickers": tickers,
        "summary": summary,
    }
