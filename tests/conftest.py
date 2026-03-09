"""
Pytest configuration for Bitvavo Bot tests.

This file is automatically loaded by pytest and sets up the Python path
so that imports from the project root work correctly.
"""
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
