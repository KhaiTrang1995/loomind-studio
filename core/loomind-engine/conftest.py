"""
Root conftest.py — adds src/ to sys.path so test imports work without
installing the package (e.g. `from src.domain.models import ...`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
