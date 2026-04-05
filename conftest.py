import sys
from pathlib import Path

# Ensure repo root is on the path so `scripts/` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
