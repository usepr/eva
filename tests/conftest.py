"""Pytest configuration for ATField test suite."""
import sys
from pathlib import Path

# 确保 eva/eva_tui 能被 import
sys.path.insert(0, str(Path(__file__).parent.parent))