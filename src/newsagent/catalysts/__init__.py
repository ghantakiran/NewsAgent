"""Catalyst engine — find, score and rank the events that move stocks.

    from newsagent.catalysts import CatalystEngine, init_catalyst_tables, upsert_catalysts

    engine = CatalystEngine(Path("data"))
    catalysts = engine.run(articles)          # detect -> cluster -> quote -> score
    upsert_catalysts(conn, catalysts)
"""

# `detect` stays the module, not the function: engine.py imports it as a
# submodule, and rebinding the name here would shadow it on the package.
from . import detect
from .detect import extract_facts, is_digest
from .engine import Catalyst, CatalystEngine, CatalystSource, score_catalyst
from .market import Quote, QuoteService, quotes
from .store import (
    catalyst_stats,
    get_catalyst,
    get_catalysts,
    init_catalyst_tables,
    mark_alerted,
    pending_alerts,
    prune_catalysts,
    prune_stale_catalysts,
    upsert_catalysts,
)
from .types import SPECS, CatalystGroup, CatalystType, Direction, TypeSpec
from .universe import TickerUniverse, load_universe

__all__ = [
    "SPECS",
    "Catalyst",
    "CatalystEngine",
    "CatalystGroup",
    "CatalystSource",
    "CatalystType",
    "Direction",
    "Quote",
    "QuoteService",
    "TickerUniverse",
    "TypeSpec",
    "catalyst_stats",
    "detect",
    "extract_facts",
    "get_catalyst",
    "get_catalysts",
    "init_catalyst_tables",
    "is_digest",
    "load_universe",
    "mark_alerted",
    "pending_alerts",
    "prune_catalysts",
    "quotes",
    "score_catalyst",
    "upsert_catalysts",
]
