"""Make the repository root importable so tests can load the example
plugin in examples/ the same way a user running from the root would."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
