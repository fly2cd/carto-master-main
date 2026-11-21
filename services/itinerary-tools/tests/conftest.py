"""Service tests are self-contained: no carto_core import.

sys.path gets the service directory so the modules import each other by
top-level name exactly as the MCP server does.
"""
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))
