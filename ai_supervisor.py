"""Compatibility shim for legacy imports.

This module now aliases the real :mod:`ai.ai_supervisor` implementation so anything
importing ``ai_supervisor`` from the project root receives the canonical module
object. That keeps monkeypatching (e.g. in unit tests) working as expected.
"""

from importlib import import_module as _import_module
import sys as _sys

_real_module = _import_module("ai.ai_supervisor")

# Ensure ``import ai_supervisor`` returns the real implementation module.
_sys.modules[__name__] = _real_module
_sys.modules.setdefault("ai_supervisor", _real_module)

if __name__ == "__main__":
	# Running as a script should behave like invoking the real supervisor.
	_real_module.main()
