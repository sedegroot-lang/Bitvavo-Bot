"""FIX #086 — Runtime patches for python_bitvavo_api library bugs.

Problem: `rateLimitThread.waitForReset(waitTime)` calls `time.sleep(waitTime)`
where `waitTime` can be negative when the rate-limit reset timestamp is in the
past (clock drift, late receipt, post-ban late processing). Python raises
`ValueError: sleep length must be non-negative` and the thread crashes — taking
down the dashboard backend (and any other consumer of the library).

Patch is a no-op if already applied. Idempotent. Apply early at import time.
"""
from __future__ import annotations

import time as _time

_PATCHED = False


def apply() -> bool:
    """Patch python_bitvavo_api.bitvavo.rateLimitThread.waitForReset.

    Returns True when patch was applied (or already applied). Returns False
    only if the library is not importable.
    """
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from python_bitvavo_api import bitvavo as _bv_mod  # type: ignore
    except Exception:
        return False

    cls = getattr(_bv_mod, "rateLimitThread", None)
    if cls is None:
        return False

    def waitForReset(self, waitTime):  # type: ignore[no-redef]
        _time.sleep(max(0.0, float(waitTime or 0)))
        if _time.time() < getattr(self.bitvavo, "rateLimitReset", 0):
            self.bitvavo.rateLimitRemaining = 1000
        else:
            timeToWait = (self.bitvavo.rateLimitReset / 1000.0) - _time.time()
            self.waitForReset(max(0.0, timeToWait))

    cls.waitForReset = waitForReset  # type: ignore[assignment]
    _PATCHED = True
    return True


# Apply automatically on import.
apply()
