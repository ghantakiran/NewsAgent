"""NewsAgent launcher — run with: streamlit run run.py"""

import sys
from pathlib import Path

# Ensure src/ is on the path
src_path = str(Path(__file__).parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Import the main function and run it
from newsagent import app as _app  # noqa: F401 — Streamlit top-level execution happens on import
