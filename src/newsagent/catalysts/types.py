"""Catalyst taxonomy — the event types NewsAgent scores and ranks.

A *catalyst* is a discrete, dated corporate or regulatory event that changes the
expected value of a stock. This module is the single source of truth for which
events we recognise, how hard each one typically hits, and which way it cuts.

`impact` is the base score (0-100) an event of this type earns before any
source, recency, corroboration, or price-confirmation adjustments are applied
by `engine.score_catalyst`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class CatalystGroup(str, Enum):
    """Coarse buckets used for UI filtering."""

    DEAL = "deal"
    CLINICAL = "clinical"
    CAPITAL = "capital"
    OPERATING = "operating"
    LEGAL = "legal"
    ANALYST = "analyst"
    STRUCTURAL = "structural"
    MACRO = "macro"


class CatalystType(str, Enum):
    # ── Deals / control ──
    BUYOUT_TARGET = "buyout_target"
    ACQUIRER = "acquirer"
    MERGER_TERMINATED = "merger_terminated"
    STRATEGIC_REVIEW = "strategic_review"
    ACTIVIST_STAKE = "activist_stake"
    SPINOFF = "spinoff"

    # ── Clinical / regulatory approval ──
    FDA_APPROVAL = "fda_approval"
    FDA_REJECTION = "fda_rejection"
    CLINICAL_POSITIVE = "clinical_positive"
    CLINICAL_NEGATIVE = "clinical_negative"
    CLINICAL_HOLD = "clinical_hold"
    PDUFA_DATE = "pdufa_date"

    # ── Capital structure ──
    OFFERING = "offering"
    SHELF_ATM = "shelf_atm"
    BUYBACK = "buyback"
    DIVIDEND_INITIATION = "dividend_initiation"
    DIVIDEND_CUT = "dividend_cut"
    STOCK_SPLIT = "stock_split"
    REVERSE_SPLIT = "reverse_split"
    BANKRUPTCY = "bankruptcy"
    GOING_CONCERN = "going_concern"
    IPO_SPAC = "ipo_spac"

    # ── Operating performance ──
    EARNINGS_BEAT = "earnings_beat"
    EARNINGS_MISS = "earnings_miss"
    GUIDANCE_RAISE = "guidance_raise"
    GUIDANCE_CUT = "guidance_cut"
    EARNINGS_SCHEDULED = "earnings_scheduled"
    EARNINGS_RESULTS = "earnings_results"
    CONTRACT_WIN = "contract_win"
    MATERIAL_AGREEMENT = "material_agreement"
    PRODUCT_LAUNCH = "product_launch"
    LAYOFFS = "layoffs"
    EXEC_CHANGE = "exec_change"

    # ── Legal / risk ──
    SHORT_REPORT = "short_report"
    REGULATORY_PROBE = "regulatory_probe"
    LITIGATION = "litigation"
    RECALL = "recall"
    CYBER_INCIDENT = "cyber_incident"
    RESTATEMENT = "restatement"
    AUDITOR_CHANGE = "auditor_change"

    # ── Analyst ──
    ANALYST_UPGRADE = "analyst_upgrade"
    ANALYST_DOWNGRADE = "analyst_downgrade"
    PRICE_TARGET_RAISE = "price_target_raise"
    PRICE_TARGET_CUT = "price_target_cut"
    INITIATION = "initiation"

    # ── Structural / flow ──
    INDEX_INCLUSION = "index_inclusion"
    INDEX_REMOVAL = "index_removal"
    TRADING_HALT = "trading_halt"
    DELISTING = "delisting"
    INSIDER_BUY = "insider_buy"
    INSIDER_SELL = "insider_sell"
    SEC_FILING_8K = "sec_filing_8k"

    # ── Macro ──
    MACRO = "macro"


@dataclass(frozen=True)
class TypeSpec:
    label: str
    impact: int
    direction: Direction
    group: CatalystGroup
    color: str


_C = CatalystGroup
_D = Direction

SPECS: dict[CatalystType, TypeSpec] = {
    CatalystType.BUYOUT_TARGET:       TypeSpec("Buyout Target",      98, _D.BULLISH, _C.DEAL,       "#00e59a"),
    CatalystType.BANKRUPTCY:          TypeSpec("Bankruptcy",         96, _D.BEARISH, _C.CAPITAL,    "#ff2d55"),
    CatalystType.FDA_APPROVAL:        TypeSpec("FDA Approval",       94, _D.BULLISH, _C.CLINICAL,   "#00e59a"),
    CatalystType.FDA_REJECTION:       TypeSpec("FDA Rejection/CRL",  94, _D.BEARISH, _C.CLINICAL,   "#ff2d55"),
    CatalystType.CLINICAL_POSITIVE:   TypeSpec("Trial Success",      90, _D.BULLISH, _C.CLINICAL,   "#00e59a"),
    CatalystType.CLINICAL_NEGATIVE:   TypeSpec("Trial Failure",      90, _D.BEARISH, _C.CLINICAL,   "#ff2d55"),
    CatalystType.CLINICAL_HOLD:       TypeSpec("Clinical Hold",      88, _D.BEARISH, _C.CLINICAL,   "#ff2d55"),
    CatalystType.GOING_CONCERN:       TypeSpec("Going Concern",      88, _D.BEARISH, _C.CAPITAL,    "#ff2d55"),
    CatalystType.MERGER_TERMINATED:   TypeSpec("Deal Terminated",    84, _D.BEARISH, _C.DEAL,       "#ff2d55"),
    CatalystType.SHORT_REPORT:        TypeSpec("Short Report",       84, _D.BEARISH, _C.LEGAL,      "#ff2d55"),
    CatalystType.GUIDANCE_CUT:        TypeSpec("Guidance Cut",       82, _D.BEARISH, _C.OPERATING,  "#ff2d55"),
    CatalystType.RESTATEMENT:         TypeSpec("Restatement",        82, _D.BEARISH, _C.LEGAL,      "#ff2d55"),
    CatalystType.OFFERING:            TypeSpec("Dilutive Offering",  80, _D.BEARISH, _C.CAPITAL,    "#ff2d55"),
    CatalystType.GUIDANCE_RAISE:      TypeSpec("Guidance Raise",     80, _D.BULLISH, _C.OPERATING,  "#00e59a"),
    CatalystType.STRATEGIC_REVIEW:    TypeSpec("Strategic Review",   78, _D.BULLISH, _C.DEAL,       "#00e59a"),
    CatalystType.ACTIVIST_STAKE:      TypeSpec("Activist Stake",     78, _D.BULLISH, _C.DEAL,       "#00e59a"),
    CatalystType.DELISTING:           TypeSpec("Delisting Risk",     78, _D.BEARISH, _C.STRUCTURAL, "#ff2d55"),
    CatalystType.INDEX_INCLUSION:     TypeSpec("Index Inclusion",    76, _D.BULLISH, _C.STRUCTURAL, "#00e59a"),
    CatalystType.TRADING_HALT:        TypeSpec("Trading Halt",       76, _D.NEUTRAL, _C.STRUCTURAL, "#f5c542"),
    CatalystType.SPINOFF:             TypeSpec("Spinoff",            74, _D.BULLISH, _C.DEAL,       "#00e59a"),
    CatalystType.DIVIDEND_CUT:        TypeSpec("Dividend Cut",       74, _D.BEARISH, _C.CAPITAL,    "#ff2d55"),
    CatalystType.REVERSE_SPLIT:       TypeSpec("Reverse Split",      72, _D.BEARISH, _C.CAPITAL,    "#ff2d55"),
    CatalystType.ACQUIRER:            TypeSpec("Acquirer",           70, _D.NEUTRAL, _C.DEAL,       "#8b93b0"),
    CatalystType.REGULATORY_PROBE:    TypeSpec("Regulatory Probe",   70, _D.BEARISH, _C.LEGAL,      "#ff2d55"),
    CatalystType.EARNINGS_MISS:       TypeSpec("Earnings Miss",      68, _D.BEARISH, _C.OPERATING,  "#ff2d55"),
    CatalystType.RECALL:              TypeSpec("Recall/Safety",      66, _D.BEARISH, _C.LEGAL,      "#ff2d55"),
    CatalystType.EARNINGS_BEAT:       TypeSpec("Earnings Beat",      64, _D.BULLISH, _C.OPERATING,  "#00e59a"),
    CatalystType.CONTRACT_WIN:        TypeSpec("Contract Win",       62, _D.BULLISH, _C.OPERATING,  "#00e59a"),
    CatalystType.AUDITOR_CHANGE:      TypeSpec("Auditor Change",     62, _D.BEARISH, _C.LEGAL,      "#ff2d55"),
    CatalystType.EARNINGS_RESULTS:    TypeSpec("Results Filed",      60, _D.NEUTRAL, _C.OPERATING,  "#f5c542"),
    CatalystType.INSIDER_BUY:         TypeSpec("Insider Buying",     60, _D.BULLISH, _C.STRUCTURAL, "#00e59a"),
    CatalystType.CYBER_INCIDENT:      TypeSpec("Cyber Incident",     60, _D.BEARISH, _C.LEGAL,      "#ff2d55"),
    CatalystType.PDUFA_DATE:          TypeSpec("PDUFA Date",         58, _D.NEUTRAL, _C.CLINICAL,   "#f5c542"),
    CatalystType.SHELF_ATM:           TypeSpec("Shelf/ATM",          58, _D.BEARISH, _C.CAPITAL,    "#ff2d55"),
    CatalystType.BUYBACK:             TypeSpec("Buyback",            56, _D.BULLISH, _C.CAPITAL,    "#00e59a"),
    CatalystType.EXEC_CHANGE:         TypeSpec("Exec Change",        54, _D.NEUTRAL, _C.OPERATING,  "#8b93b0"),
    CatalystType.DIVIDEND_INITIATION: TypeSpec("Dividend Initiated", 54, _D.BULLISH, _C.CAPITAL,    "#00e59a"),
    CatalystType.INDEX_REMOVAL:       TypeSpec("Index Removal",      54, _D.BEARISH, _C.STRUCTURAL, "#ff2d55"),
    CatalystType.STOCK_SPLIT:         TypeSpec("Stock Split",        52, _D.BULLISH, _C.CAPITAL,    "#00e59a"),
    CatalystType.LAYOFFS:             TypeSpec("Layoffs",            50, _D.NEUTRAL, _C.OPERATING,  "#f5c542"),
    CatalystType.PRODUCT_LAUNCH:      TypeSpec("Product Launch",     48, _D.BULLISH, _C.OPERATING,  "#00e59a"),
    CatalystType.ANALYST_DOWNGRADE:   TypeSpec("Downgrade",          46, _D.BEARISH, _C.ANALYST,    "#ff2d55"),
    CatalystType.ANALYST_UPGRADE:     TypeSpec("Upgrade",            44, _D.BULLISH, _C.ANALYST,    "#00e59a"),
    CatalystType.LITIGATION:          TypeSpec("Litigation",         44, _D.BEARISH, _C.LEGAL,      "#ff2d55"),
    CatalystType.MATERIAL_AGREEMENT:  TypeSpec("Material Agreement", 44, _D.NEUTRAL, _C.OPERATING,  "#8b93b0"),
    CatalystType.IPO_SPAC:            TypeSpec("IPO/SPAC",           42, _D.NEUTRAL, _C.CAPITAL,    "#8b93b0"),
    CatalystType.INITIATION:          TypeSpec("Initiation",         40, _D.NEUTRAL, _C.ANALYST,    "#8b93b0"),
    CatalystType.MACRO:               TypeSpec("Macro",              40, _D.NEUTRAL, _C.MACRO,      "#5aa9ff"),
    CatalystType.PRICE_TARGET_CUT:    TypeSpec("PT Cut",             36, _D.BEARISH, _C.ANALYST,    "#ff2d55"),
    CatalystType.PRICE_TARGET_RAISE:  TypeSpec("PT Raise",           34, _D.BULLISH, _C.ANALYST,    "#00e59a"),
    CatalystType.INSIDER_SELL:        TypeSpec("Insider Selling",    32, _D.BEARISH, _C.STRUCTURAL, "#ff2d55"),
    CatalystType.EARNINGS_SCHEDULED:  TypeSpec("Earnings Date",      30, _D.NEUTRAL, _C.OPERATING,  "#8b93b0"),
    CatalystType.SEC_FILING_8K:       TypeSpec("8-K Filing",         30, _D.NEUTRAL, _C.STRUCTURAL, "#8b93b0"),
}


def spec(t: CatalystType) -> TypeSpec:
    return SPECS[t]


def label(t: CatalystType) -> str:
    return SPECS[t].label


def all_types_by_impact() -> list[CatalystType]:
    return sorted(SPECS, key=lambda t: -SPECS[t].impact)
