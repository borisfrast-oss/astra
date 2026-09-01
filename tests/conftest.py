"""Shared pytest configuration for astra tests.

colour-demosaicing can perform a partial matplotlib import when matplotlib is
installed but not yet loaded; astropy's optional-dependency machinery then
raises ``ValueError: matplotlib.__spec__ is not set``. Eagerly importing
matplotlib (when present) prevents the partial-import state.

See first GitHub CI run findings (v1.9 M5 replay).
"""
from __future__ import annotations

try:
    import matplotlib  # noqa: F401
except Exception:
    pass
