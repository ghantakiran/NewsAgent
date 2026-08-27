"""Catalyst detection — turn a headline into typed, evidenced events.

Each rule is a compiled regex plus a confidence multiplier. Rules run against
the headline first (full weight) and the summary second (discounted), because a
catalyst that only shows up in body text is usually background, not the news.

Detection deliberately errs toward *typed* over *many*: a headline normally
yields one or two catalyst types, and `engine` keeps the highest-impact one as
the primary while retaining the rest as secondary tags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .types import CatalystType as CT

SUMMARY_DISCOUNT = 0.72

# Hedging language — a rumoured catalyst is still tradeable but less certain.
_SPECULATIVE_RE = re.compile(
    r"(?i)\b(could|may|might|reportedly|rumou?r|rumou?red|speculation|is said to|"
    r"people familiar|weighing|mulling|in talks|potential(?:ly)?|possible)\b"
)
# Listicles, explainers and promos that borrow catalyst vocabulary.
_OPINION_RE = re.compile(
    r"(?i)(^\s*(?:why|how|what|should|is|are|can|will|here'?s|top|best|\d+\s+(?:top|best|great|cheap|stocks?))\b"
    r"|\b(?:stocks? to (?:buy|watch|own|consider)|best stocks?|top \d+ stocks?|motley fool|"
    r"prediction|forecast for 20\d\d|is it (?:too late|time)|worth buying|better buy|"
    r"my top pick|dividend king|penny stocks?)\b)"
)
_MONEY = r"\$\s?[\d,]+(?:\.\d+)?\s?(?:million|billion|trillion|[MBK])?"


def _r(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# ── Rules, roughly ordered by how decisive the phrasing is ────────────
# (type, pattern, confidence)
RULES: list[tuple[CT, re.Pattern[str], float]] = [
    # ── Deals / control ──
    (CT.BUYOUT_TARGET, _r(r"\b(?:agrees?|agreed) to be acquired\b"), 1.0),
    # Also catches "could be acquired by" / "is in talks to be acquired by";
    # `speculation_factor` is what discounts a rumour, not a missing rule.
    (CT.BUYOUT_TARGET, _r(r"\bbe(?:ing)? acquired by\b"), 0.9),
    (CT.BUYOUT_TARGET, _r(r"\b(?:agrees?|agreed) to (?:a )?(?:merger|be taken private|sell itself)\b"), 1.0),
    (CT.BUYOUT_TARGET, _r(r"\b(?:takeover|buyout|acquisition|takeover) (?:bid|offer|proposal) for\b"), 0.95),
    (CT.BUYOUT_TARGET, _r(r"\b(?:go(?:es|ing)? private|taken private|take[- ]private (?:deal|transaction))\b"), 0.9),
    (CT.BUYOUT_TARGET, _r(r"\btender offer (?:to acquire|for all)\b"), 0.9),
    (CT.BUYOUT_TARGET, _r(r"\ball[- ]cash (?:deal|transaction|acquisition|merger)\b"), 0.85),
    (CT.BUYOUT_TARGET, _r(r"\bdefinitive (?:merger )?agreement\b"), 0.8),
    (CT.ACQUIRER, _r(r"\b(?:to acquire|acquires?|acquired|agrees? to (?:buy|acquire)|to purchase)\b.{0,60}" + _MONEY), 0.95),
    (CT.ACQUIRER, _r(r"\b(?:to acquire|acquires?|completes? (?:the )?acquisition of)\b"), 0.8),
    (CT.MERGER_TERMINATED, _r(r"\b(?:terminates?|terminated|calls? off|abandons?|scraps?) (?:the |its )?(?:merger|deal|acquisition|takeover)\b"), 1.0),
    (CT.MERGER_TERMINATED, _r(r"\b(?:merger|deal|acquisition) (?:collapses?|falls? apart|terminated|blocked)\b"), 1.0),
    (CT.STRATEGIC_REVIEW, _r(r"\bstrategic (?:alternatives|options|review)\b"), 1.0),
    (CT.STRATEGIC_REVIEW, _r(r"\b(?:explor(?:es|ing)|considering|weighing|reviewing) (?:a |the )?(?:sale|potential sale|options)\b"), 0.9),
    (CT.SPINOFF, _r(r"\bspin[- ]?off\b|\bspins? off\b|\bplans? to separate\b|\bseparate into two\b"), 0.9),
    (CT.ACTIVIST_STAKE, _r(r"\b(?:elliott|starboard|icahn|trian|jana partners|third point|pershing square|engine capital|land ?&? ?buildings|sachem head|politan)\b"), 0.9),
    (CT.ACTIVIST_STAKE, _r(r"\b(?:activist (?:investor|stake|position|campaign)|schedule 13d|13d filing|proxy fight|nominates? (?:\w+ )?directors)\b"), 0.9),
    (CT.ACTIVIST_STAKE, _r(r"\b(?:builds?|discloses?|takes?|reveals?) (?:a |an )?[\d.]+% (?:stake|position)\b"), 0.85),

    # ── Clinical / regulatory ──
    (CT.FDA_APPROVAL, _r(r"\bfda approves?\b|\bapproved by the fda\b|\breceives? (?:us )?fda approval\b"), 1.0),
    (CT.FDA_APPROVAL, _r(r"\bfda (?:grants?|issues?) (?:full |accelerated |marketing )?approval\b"), 1.0),
    (CT.FDA_APPROVAL, _r(r"\b(?:approval|approves?) (?:of|for) .{0,40}\b(?:therapy|treatment|drug|indication|candidate)\b"), 0.8),
    (CT.FDA_APPROVAL, _r(r"\b510\(k\) clearance\b|\bce mark(?:ing)? (?:approval|granted)\b|\bema approv\w+"), 0.85),
    (CT.FDA_REJECTION, _r(r"\bcomplete response letter\b|\breceives? (?:a )?crl\b"), 1.0),
    (CT.FDA_REJECTION, _r(r"\bfda (?:rejects?|declines?|refuses? to (?:file|approve))\b|\bnot approvable\b"), 1.0),
    (CT.CLINICAL_POSITIVE, _r(r"\b(?:met|meets|achieved|achieves) (?:its |the )?(?:co-)?primary endpoint\b"), 1.0),
    (CT.CLINICAL_POSITIVE, _r(r"\bpositive (?:top-?line |pivotal |interim |phase [123]\w* )?(?:results?|data|readout)\b"), 0.95),
    (CT.CLINICAL_POSITIVE, _r(r"\bstatistically significant (?:improvement|reduction|benefit|increase)\b"), 0.9),
    (CT.CLINICAL_NEGATIVE, _r(r"\b(?:failed?|fails?|did not|does not|misses?|missed) to meet\b|\bmissed (?:its )?primary endpoint\b"), 1.0),
    (CT.CLINICAL_NEGATIVE, _r(r"\b(?:trial|study) fail(?:s|ed|ure)\b|\bnegative top-?line\b"), 1.0),
    (CT.CLINICAL_NEGATIVE, _r(r"\bdiscontinu(?:es|ed|ing) (?:the |its )?(?:phase|trial|study|development|program)\b"), 0.9),
    (CT.CLINICAL_HOLD, _r(r"\b(?:partial |full )?clinical hold\b"), 1.0),
    (CT.PDUFA_DATE, _r(r"\bpdufa\b|\bprescription drug user fee\b"), 1.0),
    (CT.PDUFA_DATE, _r(r"\b(?:priority review|breakthrough therapy|fast track|orphan drug|rmat) designation\b"), 0.85),
    (CT.PDUFA_DATE, _r(r"\b(?:accepts?|accepted) .{0,30}\b(?:nda|bla|snda|ind)\b|\bfiles? (?:an? )?(?:nda|bla)\b"), 0.8),

    # ── Capital structure ──
    (CT.OFFERING, _r(r"\bpric(?:es|ed|ing) (?:of )?(?:an? |its )?(?:\$?[\d.,]+ ?(?:million|billion) )?(?:underwritten |registered direct |upsized )?(?:public )?offering\b"), 1.0),
    (CT.OFFERING, _r(r"\bannounces? (?:a |an |its )?(?:proposed |underwritten |registered direct |\$?[\d.,]+ ?(?:million|billion) )*(?:public|common stock|equity|convertible) offering\b"), 1.0),
    (CT.OFFERING, _r(r"\b(?:common stock|secondary|follow-?on|convertible (?:senior )?notes?) offering\b"), 0.9),
    (CT.OFFERING, _r(r"\bprivate placement\b|\bpipe (?:financing|deal)\b|\bdirect offering\b"), 0.85),
    (CT.SHELF_ATM, _r(r"\bat[- ]the[- ]market (?:offering|program|facility)\b|\batm program\b"), 0.95),
    (CT.SHELF_ATM, _r(r"\bshelf registration\b|\bform s-3\b|\bmixed shelf\b|\b424b5\b"), 0.9),
    (CT.BUYBACK, _r(r"\b(?:share |stock )?(?:repurchase|buy-?back) (?:program|plan|authorization)\b"), 1.0),
    (CT.BUYBACK, _r(r"\bauthoriz(?:es|ed) .{0,30}(?:repurchase|buy-?back)\b"), 1.0),
    (CT.DIVIDEND_CUT, _r(r"\b(?:cuts?|slashes?|reduces?|suspends?|eliminates?|omits?) (?:its |the |quarterly )*dividend\b"), 1.0),
    (CT.DIVIDEND_CUT, _r(r"\bdividend (?:cut|suspension|reduction|eliminated|suspended)\b"), 1.0),
    (CT.DIVIDEND_INITIATION, _r(r"\b(?:initiates?|declares? (?:its )?first|announces? (?:its )?first) (?:a )?(?:quarterly |annual )?dividend\b"), 1.0),
    (CT.DIVIDEND_INITIATION, _r(r"\bspecial (?:cash )?dividend\b|\b(?:raises?|increases?|boosts?|hikes?) (?:its )?(?:quarterly )?dividend\b"), 0.9),
    (CT.REVERSE_SPLIT, _r(r"\breverse (?:stock )?split\b|\b1-for-\d+ (?:reverse )?split\b"), 1.0),
    (CT.STOCK_SPLIT, _r(r"\b(?:\d+-for-\d+|forward) (?:stock )?split\b|\bstock split\b|\bsplits? its stock\b"), 0.95),
    (CT.BANKRUPTCY, _r(r"\bchapter (?:7|11|15)\b|\bfil(?:es|ed|ing) for bankruptcy\b|\bbankruptcy protection\b"), 1.0),
    (CT.GOING_CONCERN, _r(r"\bgoing concern\b|\bsubstantial doubt (?:about|regarding)\b"), 1.0),
    (CT.DELISTING, _r(r"\bdelist(?:ing|ed|s)?\b|\bnotice of (?:non-?compliance|deficiency)\b"), 0.95),
    (CT.DELISTING, _r(r"\bminimum bid price requirement\b|\blisting (?:deficiency|standards?) notice\b"), 0.95),
    (CT.IPO_SPAC, _r(r"\b(?:prices?|priced|launches?|files? for) (?:its )?ipo\b|\binitial public offering\b|\bdirect listing\b"), 0.9),
    (CT.IPO_SPAC, _r(r"\bde-?spac\b|\bbusiness combination with\b|\bspac merger\b"), 0.85),

    # ── Operating ──
    (CT.GUIDANCE_RAISE, _r(r"\b(?:raises?|raised|boosts?|lifts?|hikes?|increases?) (?:its |full[- ]year |fy ?\d+ |q[1-4] |20\d\d )*(?:guidance|outlook|forecast|revenue outlook|profit forecast)\b"), 1.0),
    (CT.GUIDANCE_RAISE, _r(r"\bguidance (?:above|tops|ahead of) (?:consensus|estimates|expectations)\b|\bupbeat (?:guidance|outlook|forecast)\b"), 0.95),
    (CT.GUIDANCE_CUT, _r(r"\b(?:cuts?|lowers?|slashes?|trims?|reduces?|withdraws?|suspends?) (?:its |full[- ]year |fy ?\d+ |q[1-4] |20\d\d )*(?:guidance|outlook|forecast)\b"), 1.0),
    (CT.GUIDANCE_CUT, _r(r"\bprofit warning\b|\bwarns? (?:on|of|about) (?:weak|lower|soft|slowing)\b|\bguidance (?:below|misses|short of)\b"), 0.95),
    (CT.EARNINGS_BEAT, _r(r"\b(?:beats?|beat|tops?|topped|surpasses?|exceeds?) (?:on |analysts?'? |wall street'?s? |street )?(?:eps|earnings|revenue|estimates|expectations|forecasts?|consensus)\b"), 0.95),
    (CT.EARNINGS_BEAT, _r(r"\b(?:earnings|eps|revenue|q[1-4]) (?:beat|beats)\b|\bbetter[- ]than[- ]expected (?:results|earnings|revenue)\b"), 0.95),
    (CT.EARNINGS_MISS, _r(r"\b(?:misses?|missed|falls? short of|comes? in below|trails?) (?:on |analysts?'? |wall street'?s? |street )?(?:eps|earnings|revenue|estimates|expectations|forecasts?|consensus)\b"), 0.95),
    (CT.EARNINGS_MISS, _r(r"\b(?:earnings|eps|revenue|q[1-4]) miss\b|\bworse[- ]than[- ]expected (?:results|earnings|loss)\b"), 0.95),
    (CT.EARNINGS_SCHEDULED, _r(r"\bto (?:report|announce|release) .{0,30}\b(?:results|earnings)\b|\bearnings (?:date|call) (?:scheduled|set)\b"), 0.85),
    (CT.EARNINGS_SCHEDULED, _r(r"\bschedules? .{0,25}(?:earnings|conference call|results)\b"), 0.85),
    (CT.CONTRACT_WIN, _r(r"\b(?:awarded|wins?|won|secures?|receives?) (?:a |an |its )?(?:" + _MONEY + r" )?(?:multi-?year )?(?:contract|order|award|tender|purchase order)\b"), 0.95),
    (CT.CONTRACT_WIN, _r(r"\b(?:signs?|enters? into) (?:a |an )?(?:definitive |strategic |multi-?year |exclusive )?(?:agreement|partnership|collaboration|licensing deal) with\b"), 0.8),
    (CT.CONTRACT_WIN, _r(r"\b(?:selected|chosen) by .{0,40}\bto (?:provide|supply|deploy|build)\b"), 0.85),
    (CT.PRODUCT_LAUNCH, _r(r"\b(?:commercial|us|global|nationwide) launch\b|\blaunches? (?:its |the )?(?:new|first|next-gen)\b"), 0.8),
    (CT.PRODUCT_LAUNCH, _r(r"\b(?:unveils?|introduces?|debuts?) (?:its |the )?(?:new|first|next-gen)\b"), 0.75),
    (CT.LAYOFFS, _r(r"\blay ?offs?\b|\bjob cuts\b|\bworkforce reduction\b|\bcuts? \d+%? (?:of )?(?:its )?(?:workforce|jobs|staff|employees)\b"), 0.95),
    (CT.LAYOFFS, _r(r"\brestructuring (?:plan|program|charge)\b"), 0.8),
    (CT.EXEC_CHANGE, _r(r"\b(?:ceo|cfo|coo|chairman|president) (?:steps? down|resigns?|to retire|departs?|out|transition|ousted|fired)\b"), 1.0),
    (CT.EXEC_CHANGE, _r(r"\b(?:names?|appoints?|hires?|taps?) .{0,40}\b(?:as )?(?:new )?(?:ceo|cfo|coo|chief executive|chief financial officer)\b"), 0.95),

    # ── Legal / risk ──
    (CT.SHORT_REPORT, _r(r"\b(?:hindenburg|muddy waters|citron|scorpion capital|culper research|kerrisdale|grizzly research|fuzzy panda|blue orca|wolfpack research|night market research|spruce point|bleecker street)\b"), 1.0),
    (CT.SHORT_REPORT, _r(r"\bshort[- ](?:seller|selling) report\b|\bshort report\b|\bshort seller (?:targets?|alleges?|accuses?)\b"), 1.0),
    (CT.REGULATORY_PROBE, _r(r"\b(?:sec|doj|ftc|cftc|fbi|eu antitrust) (?:investigation|probe|inquiry|subpoena|charges?|sues?)\b"), 1.0),
    (CT.REGULATORY_PROBE, _r(r"\breceives? (?:a )?subpoena\b|\bunder (?:federal )?investigation\b|\bantitrust (?:probe|lawsuit|suit|review)\b"), 0.95),
    (CT.LITIGATION, _r(r"\bclass action\b|\bsecurities fraud (?:lawsuit|class action)\b|\bjury (?:verdict|awards?|finds?)\b"), 0.9),
    (CT.LITIGATION, _r(r"\b(?:patent infringement|files? suit against|sued? by|court (?:rules?|blocks?|orders?))\b"), 0.8),
    (CT.LITIGATION, _r(r"\bagrees? to pay " + _MONEY + r" to (?:settle|resolve)\b|\bsettles? .{0,30}for " + _MONEY), 0.9),
    (CT.RECALL, _r(r"\brecalls?\b|\brecall of\b|\bvoluntary recall\b|\bblack box warning\b|\bfda warning letter\b"), 0.9),
    (CT.RECALL, _r(r"\bwithdraw(?:s|n|ing) .{0,25}from the market\b|\bsafety (?:alert|signal|concerns?)\b"), 0.85),
    (CT.CYBER_INCIDENT, _r(r"\bdata breach\b|\bcyber ?attack\b|\bransomware\b|\bsecurity incident\b|\bhacked?\b"), 0.95),

    # ── Structural / flow ──
    (CT.INDEX_INCLUSION, _r(r"\b(?:join(?:s|ing)?|added to|will replace) .{0,20}\b(?:s&p 500|s&p 400|s&p 600|nasdaq-?100|dow jones industrial)\b"), 1.0),
    (CT.INDEX_INCLUSION, _r(r"\bs&p 500 inclusion\b|\bindex (?:inclusion|addition)\b|\brussell (?:1000|2000) (?:addition|inclusion)\b"), 0.95),
    (CT.INDEX_REMOVAL, _r(r"\b(?:removed from|dropped from|will be replaced in) .{0,20}\b(?:s&p 500|s&p 400|nasdaq-?100|dow)\b"), 1.0),
    (CT.TRADING_HALT, _r(r"\btrading halt(?:ed)?\b|\bhalted (?:for|pending|due to)\b|\bvolatility (?:trading )?halt\b"), 1.0),
    (CT.INSIDER_BUY, _r(r"\binsider (?:buying|purchases?|buys)\b|\binsiders? (?:bought|purchased|are buying)\b"), 0.95),
    (CT.INSIDER_BUY, _r(r"\b(?:ceo|cfo|director|chairman) (?:buys?|bought|purchases?) .{0,25}shares\b"), 0.95),
    (CT.INSIDER_SELL, _r(r"\binsider (?:selling|sales?|sells)\b|\binsiders? (?:sold|are selling)\b"), 0.9),
    (CT.INSIDER_SELL, _r(r"\b(?:ceo|cfo|director|chairman) (?:sells?|sold|unloads?) .{0,25}shares\b"), 0.9),

    # ── Analyst ──
    (CT.ANALYST_UPGRADE, _r(r"\bupgrade[sd]?\b(?! to (?:sell|underweight|underperform))|\b(?:raised|upgraded) to (?:buy|overweight|outperform|strong buy|accumulate|add)\b"), 0.95),
    (CT.ANALYST_DOWNGRADE, _r(r"\bdowngrade[sd]?\b|\b(?:cut|lowered|downgraded) to (?:sell|underweight|underperform|hold|neutral|reduce)\b"), 0.95),
    (CT.PRICE_TARGET_RAISE, _r(r"\b(?:price target|pt) (?:raised|increased|hiked|boosted|lifted)\b|\b(?:raises?|boosts?|hikes?|lifts?) (?:its )?(?:price target|pt)\b"), 0.95),
    (CT.PRICE_TARGET_CUT, _r(r"\b(?:price target|pt) (?:cut|lowered|reduced|slashed|trimmed)\b|\b(?:cuts?|lowers?|slashes?|trims?) (?:its )?(?:price target|pt)\b"), 0.95),
    (CT.INITIATION, _r(r"\binitiat(?:es|ed) (?:coverage|with)\b|\bcoverage initiated\b|\bstarts? coverage\b|\blaunches? coverage\b"), 0.95),

    # ── Macro (no issuer) ──
    (CT.MACRO, _r(r"\b(?:federal reserve|fomc|powell|rate (?:cut|hike|decision)|interest rates?)\b"), 0.9),
    (CT.MACRO, _r(r"\b(?:cpi|ppi|pce|gdp|nonfarm payrolls?|jobs report|unemployment rate|inflation (?:data|report))\b"), 0.9),
    (CT.MACRO, _r(r"\b(?:tariffs?|trade war|opec|treasury yields?|jobless claims)\b"), 0.8),
]

# Feed-level priors: a filing wire tells us the type before we read a word.
SOURCE_TYPE_HINTS: dict[str, CT] = {
    "SEC 8-K Filings": CT.SEC_FILING_8K,
    "SEC Offerings (424B5)": CT.SHELF_ATM,
    "Nasdaq Trading Halts": CT.TRADING_HALT,
}


@dataclass(frozen=True)
class Detection:
    type: CT
    confidence: float
    evidence: str
    in_title: bool

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.type.value}@{self.confidence:.2f}"


def is_opinion(title: str) -> bool:
    """Listicle / explainer / promo headline rather than a reported event."""
    return bool(_OPINION_RE.search(title))


def speculation_factor(text: str) -> float:
    return 0.78 if _SPECULATIVE_RE.search(text) else 1.0


def detect(title: str, summary: str = "", source: str = "") -> list[Detection]:
    """All catalyst types present, strongest confidence first."""
    title = title or ""
    summary = (summary or "")[:600]
    best: dict[CT, Detection] = {}

    def consider(ct: CT, conf: float, evidence: str, in_title: bool) -> None:
        cur = best.get(ct)
        if cur is None or conf > cur.confidence:
            best[ct] = Detection(ct, round(min(conf, 1.0), 3), evidence[:120], in_title)

    spec_factor = speculation_factor(title)
    for ct, pattern, weight in RULES:
        m = pattern.search(title)
        if m:
            consider(ct, weight * spec_factor, m.group(0), True)
            continue
        if summary:
            m = pattern.search(summary)
            if m:
                consider(ct, weight * SUMMARY_DISCOUNT * spec_factor, m.group(0), False)

    hint = SOURCE_TYPE_HINTS.get(source)
    if hint and hint not in best:
        consider(hint, 0.7, f"source:{source}", False)

    # An opinion piece can still name a real catalyst, but we trust it less.
    if is_opinion(title):
        for ct, d in list(best.items()):
            best[ct] = Detection(ct, round(d.confidence * 0.55, 3), d.evidence, d.in_title)

    return sorted(best.values(), key=lambda d: (-d.confidence, d.type.value))


# ── Numeric fact extraction ──────────────────────────────────────────

_DEAL_VALUE_RE = re.compile(
    r"(?i)(?:for|worth|valued at|value of|deal worth|totaling|up to)\s+"
    r"(\$\s?[\d,]+(?:\.\d+)?\s?(?:million|billion|trillion|[MB])\b)"
)
_PT_RE = re.compile(
    r"(?i)(?:price target|pt)\s*(?:of|to|at)?\s*\$\s?([\d,]+(?:\.\d+)?)"
    r"|\bto\s+\$\s?([\d,]+(?:\.\d+)?)\s+from\s+\$\s?([\d,]+(?:\.\d+)?)"
)
_PCT_RE = re.compile(r"(?i)\b(?:up|down|gain(?:s|ed)?|los(?:es|t)|surges?|plunges?|jumps?|falls?|rose|drops?|soars?|sinks?)\s+([\d.]+)\s?%")
_PHASE_RE = re.compile(r"(?i)\bphase\s?(1/2|2/3|[123])\b")
_OFFERING_SIZE_RE = re.compile(
    r"(?i)\$\s?([\d,]+(?:\.\d+)?)\s?(million|billion)\s+(?:underwritten\s+)?"
    r"(?:public\s+)?(?:offering|placement|financing|notes?)"
)
_EPS_RE = re.compile(r"(?i)\beps of \$?(-?[\d.]+)|\bearnings of \$?(-?[\d.]+) (?:per share|a share)")


def _first_group(m: re.Match[str] | None) -> str | None:
    if not m:
        return None
    for g in m.groups():
        if g:
            return g.strip()
    return None


def extract_facts(text: str) -> dict[str, str]:
    """Pull the numbers that make a catalyst concrete (deal size, PT, %, phase)."""
    facts: dict[str, str] = {}
    if v := _first_group(_DEAL_VALUE_RE.search(text)):
        facts["deal_value"] = v
    if v := _first_group(_PT_RE.search(text)):
        facts["price_target"] = f"${v}"
    if v := _first_group(_PCT_RE.search(text)):
        facts["move_pct"] = f"{v}%"
    if v := _first_group(_PHASE_RE.search(text)):
        facts["phase"] = f"Phase {v}"
    if m := _OFFERING_SIZE_RE.search(text):
        facts["offering_size"] = f"${m.group(1)}{'B' if m.group(2).lower() == 'billion' else 'M'}"
    if v := _first_group(_EPS_RE.search(text)):
        facts["eps"] = f"${v}"
    return facts


# ── Digest headlines ─────────────────────────────────────────────────
# Roundups bundle many events into one headline ("SA analyst upgrades/downgrades:
# AMD, DELL, ASAN, UPST"). Scoring them as a single catalyst attributes every
# rating change to whichever ticker happens to be listed first, so they are
# dropped rather than mis-attributed.

_DIGEST_RE = re.compile(
    r"(?i)("
    r"upgrades?\s*/\s*downgrades?|downgrades?\s*/\s*upgrades?"
    r"|\b(?:top|biggest|notable)\s+(?:analyst\s+)?(?:calls|moves|movers|gainers|losers)\b"
    r"|\b(?:analyst|street|wall\s*street)\s+(?:calls|actions|roundup|lunch|breakfast)\b"
    r"|\bstock\s+market\s+today\b|\bmarket\s+(?:wrap|recap|close|open|snapshot)\b"
    r"|\b(?:pre-?market|after-?hours|midday|premarket)\s+(?:movers|movement|update|report)\b"
    r"|\bwhat\s+to\s+watch\b|\bthings?\s+to\s+know\b|\bmovers?\s+and\s+shakers\b"
    r"|\bdaily\s+(?:briefing|roundup|digest)\b|\bstocks?\s+(?:that\s+)?mov(?:ed|ing)\s+the\s+most\b"
    r")"
)
# Three or more comma/slash-separated symbols is a ticker list, not one event.
_TICKER_LIST_RE = re.compile(r"\b[A-Z]{2,5}\b\s*[,/]\s*\b[A-Z]{2,5}\b\s*[,/]\s*\b[A-Z]{2,5}\b")


def is_digest(title: str) -> bool:
    """True when a headline bundles several unrelated events."""
    return bool(_DIGEST_RE.search(title) or _TICKER_LIST_RE.search(title))


# ── Analyst firms ────────────────────────────────────────────────────
# In "Goldman Sachs upgrades Segro", the ticker is Segro's — never Goldman's.
# Firm names are stripped before subject resolution on analyst-type catalysts.

ANALYST_FIRMS: tuple[str, ...] = (
    "goldman sachs", "goldman", "morgan stanley", "jpmorgan chase", "jpmorgan", "jp morgan",
    "bofa securities", "bank of america", "bofa", "citigroup", "citi", "barclays",
    "deutsche bank", "credit suisse", "hsbc", "wells fargo", "raymond james",
    "piper sandler", "jefferies", "td cowen", "cowen", "wolfe research", "bernstein",
    "sanford bernstein", "oppenheimer", "stifel", "needham", "wedbush", "canaccord genuity",
    "canaccord", "rbc capital markets", "rbc capital", "bmo capital markets", "bmo capital",
    "btig", "mizuho", "truist securities", "truist", "evercore isi", "evercore", "keybanc",
    "loop capital", "rosenblatt", "susquehanna", "william blair", "da davidson",
    "robert w baird", "baird", "guggenheim", "craig-hallum", "h.c. wainwright",
    "hc wainwright", "wainwright", "maxim group", "b. riley", "b riley", "roth mkm",
    "roth capital", "lake street", "northland", "ladenburg", "cantor fitzgerald", "cantor",
    "macquarie", "redburn", "new street research", "atlantic equities", "moffettnathanson",
    "bnp paribas", "societe generale", "jmp securities", "leerink", "scotiabank",
    "berenberg", "exane", "phillip securities", "citizens jmp", "melius research",
    "morningstar", "zacks", "seeking alpha", "the motley fool", "argus research",
    "ubs", "nomura", "daiwa", "cfra", "bairds",
)
_FIRM_RE = re.compile(
    r"(?i)\b(?:" + "|".join(re.escape(f) for f in sorted(ANALYST_FIRMS, key=len, reverse=True)) + r")\b"
)
# Tickers of the sell-side firms themselves, which must never be picked up as
# the subject of a rating action they issued.
FIRM_TICKERS = frozenset({
    "GS", "MS", "JPM", "BAC", "C", "BCS", "DB", "UBS", "HSBC", "WFC", "RJF",
    "PIPR", "JEF", "COWN", "OPY", "SF", "CACC", "RY", "BMO", "MFG", "TFC",
    "EVR", "KEY", "SCHW", "NMR", "BNPQY", "SCGLY", "BNS", "MORN", "CFRA",
})


def strip_analyst_firms(text: str) -> str:
    """Blank out sell-side firm names so the rated company is what remains."""
    return _FIRM_RE.sub(" ", text)


# ── SEC 8-K item codes ───────────────────────────────────────────────
# EDGAR's current-filings feed lists the Item numbers a filing reports, e.g.
# "Item 3.01: Notice of Delisting...". Item codes are unambiguous by
# construction, so they outrank anything inferred from prose.

EIGHT_K_ITEMS: dict[str, CT] = {
    "1.01": CT.MATERIAL_AGREEMENT, # entry into a material definitive agreement
    "1.03": CT.BANKRUPTCY,         # bankruptcy or receivership
    "2.01": CT.ACQUIRER,           # completed acquisition/disposition of assets
    "2.02": CT.EARNINGS_RESULTS,   # results of operations and financial condition
    "2.05": CT.LAYOFFS,            # costs associated with exit or disposal
    "3.01": CT.DELISTING,          # notice of delisting / listing deficiency
    "3.02": CT.OFFERING,           # unregistered sales of equity securities
    "4.01": CT.AUDITOR_CHANGE,     # change in certifying accountant
    "4.02": CT.RESTATEMENT,        # non-reliance on previously issued financials
    "5.01": CT.BUYOUT_TARGET,      # change in control of registrant
    "5.02": CT.EXEC_CHANGE,        # departure/election of directors or officers
}
ITEM_LABELS = {
    "1.01": "material agreement signed", "1.03": "bankruptcy or receivership",
    "2.01": "acquisition or disposition completed", "2.02": "quarterly results filed",
    "2.05": "exit or disposal costs", "3.01": "delisting / listing-deficiency notice",
    "3.02": "unregistered equity sale (dilution)", "4.01": "auditor change",
    "4.02": "prior financials not reliable", "5.01": "change in control",
    "5.02": "officer or director departure",
}
_ITEM_RE = re.compile(r"Item\s+(\d\.\d{2})\s*:", re.IGNORECASE)
# Codes so routine they say nothing about the stock (Reg FD, exhibits, other).
_ITEM_NOISE = {"7.01", "8.01", "9.01", "5.03", "5.07"}


def detect_8k_items(summary: str) -> list[Detection]:
    """Catalysts implied by the Item codes on an 8-K."""
    out: list[Detection] = []
    for code in _ITEM_RE.findall(summary or ""):
        ct = EIGHT_K_ITEMS.get(code)
        if ct is not None:
            out.append(Detection(ct, 0.95, f"Item {code}", True))
    if not out and _ITEM_RE.search(summary or ""):
        return []  # only routine items — not news
    return out


# ── Nasdaq trading halts ─────────────────────────────────────────────
# The halt feed's title is the bare symbol and the body is an HTML table.
# A halt is the single fastest signal that something is happening.

_HALT_FIELD_RE = re.compile(r"(?i)<td[^>]*>(.*?)</td>")
_HALT_TAG_RE = re.compile(r"<[^>]+>")
HALT_REASONS = {
    "T1": "News pending", "T2": "News released", "T3": "News and resumption times",
    "T12": "Additional information requested", "H4": "Listing non-compliance",
    "H9": "Not current in filings", "H10": "SEC trading suspension",
    "H11": "Regulatory concern", "D": "Delisted", "M": "Volatility pause",
    "LUDP": "Limit up/limit down pause", "LUDS": "Limit up/limit down straddle",
    "IPO1": "IPO not yet traded", "IPOQ": "IPO release", "MWC1": "Market-wide circuit breaker",
}
# Halts that mean something specific is breaking, not routine plumbing.
MATERIAL_HALT_REASONS = {"T1", "T2", "T12", "H4", "H9", "H10", "H11", "D", "LUDP", "LUDS", "M"}


# Column order of the halt table: date, time, symbol, name, market, reason, ...
_HALT_REASON_COL = 5
# How far past the symbol the reason code can sit once the table is flattened
# (issue name can run several words before the market and reason columns).
_HALT_TEXT_WINDOW = 8


def _halt_code_from_text(text: str, symbol: str) -> str:
    tokens = text.split()
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].strip(",.").upper() != symbol:
            continue
        for token in tokens[i + 1:i + 1 + _HALT_TEXT_WINDOW]:
            candidate = token.strip(",.").upper()
            if candidate in HALT_REASONS:
                return candidate
        break
    return ""


def parse_halt(title: str, summary: str) -> dict[str, str] | None:
    """Extract {symbol, reason_code, reason, market} from a Nasdaq halt item.

    An unrecognised reason code means the table layout changed, so the row is
    dropped rather than published as a bare "Halted" with no explanation.
    """
    symbol = (title or "").strip().upper()
    if not symbol or not symbol.isalpha():
        return None
    cells = [_HALT_TAG_RE.sub("", c).strip() for c in _HALT_FIELD_RE.findall(summary or "")]
    if cells:
        code = ""
        if len(cells) > _HALT_REASON_COL and cells[_HALT_REASON_COL].upper() in HALT_REASONS:
            code = cells[_HALT_REASON_COL].upper()
        else:
            for cell in cells:
                if cell.upper() in HALT_REASONS:
                    code = cell.upper()
                    break
    else:
        # The feed pipeline strips HTML before storage, so the same table arrives
        # as a flat token stream: "... 09:31:00 LGVN Longeveron Inc NASDAQ T1 ...".
        code = _halt_code_from_text(summary or "", symbol)
    if code not in MATERIAL_HALT_REASONS:
        return None
    return {
        "symbol": symbol,
        "reason_code": code,
        "reason": HALT_REASONS[code],
        "market": cells[4] if len(cells) > 4 else "",
    }


# ── Source routing ───────────────────────────────────────────────────

_SEC_TITLE_RE = re.compile(
    r"^\s*(?P<form>[A-Z0-9][A-Z0-9\-/]*)\s+-\s+(?P<company>.+?)\s*"
    r"\(\d{7,10}\)\s*\((?:Filer|Subject|Reporting|Issuer)\)\s*$",
    re.IGNORECASE,
)


def parse_sec_title(title: str) -> tuple[str, str] | None:
    """'8-K - CaliberCos Inc. (0001627282) (Filer)' -> ('8-K', 'CaliberCos Inc.')."""
    m = _SEC_TITLE_RE.match(title or "")
    if not m:
        return None
    return m.group("form").upper(), m.group("company").strip()


def source_kind(source: str) -> str:
    """Which specialised parser a feed needs: '8k', '424b5', 'halt' or ''."""
    s = (source or "").lower()
    if "trading halt" in s or "nasdaqtrader" in s:
        return "halt"
    if "424b5" in s or "offering" in s and "sec" in s:
        return "424b5"
    if "8-k" in s or ("sec" in s and "filing" in s):
        return "8k"
    return ""


# Filers that are pooled vehicles rather than operating companies. Their 8-Ks
# are administrative plumbing (an ETF signs "material agreements" constantly),
# so they never belong on a catalyst board.
_NON_OPERATING_FILER_RE = re.compile(
    r"(?i)\b(etf|etn|exchange[- ]traded|index fund|mutual fund|unit investment trust"
    r"|\bfund\b|\btrust\b|l\.?p\.?$|limited partnership|21shares|ishares|proshares"
    r"|spdr|invesco|vaneck|grayscale|direxion|wisdomtree|bitwise|franklin templeton)\b"
)


def is_non_operating_filer(company: str) -> bool:
    return bool(_NON_OPERATING_FILER_RE.search(company or ""))


def filing_headline(company: str, form: str, item_codes: list[str]) -> str:
    """Readable headline for an EDGAR item that ships as 'FORM - NAME (CIK) (Filer)'."""
    described = [ITEM_LABELS[c] for c in item_codes if c in ITEM_LABELS]
    if described:
        return f"{company} — {described[0]} ({form} Item {item_codes[0]})"
    return f"{company} — {form} filed"


def item_codes(summary: str) -> list[str]:
    return _ITEM_RE.findall(summary or "")
