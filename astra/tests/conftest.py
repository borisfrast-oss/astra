"""Shared pytest configuration for astra tests.

colour-demosaicing can perform a partial matplotlib import when matplotlib is
installed but not yet loaded; astropy's optional-dependency machinery then
raises ``ValueError: matplotlib.__spec__ is not set``. Eagerly importing
matplotlib (when present) prevents the partial-import state.

See first GitHub CI run findings (v1.9 M5 replay).
"""
from __future__ import annotations

from pathlib import Path

import yaml

try:
    import matplotlib  # noqa: F401
except Exception:
    pass


def write_default_suggested(
    target_dir: Path,
    preset: str = "star_standard",
    registration_method: str = "fft",
    debayer_method: str = "superpixel",
) -> Path:
    """Write a minimal valid suggested.yaml into *target_dir*.

    V1.11-ENTSCHLACKUNG helper (ENTS-3 Ripple-Migration): existing tests
    that invoke ``astra process`` without ``--from-suggested`` must supply
    the now-required file. The defaults (``star_standard``, ``fft``,
    ``superpixel``) match the former hard-coded pipeline defaults so that
    existing assertions on log-events / effective values remain unchanged.

    Schema v1 — all mandatory fields are present; ``pcc.enabled: null``
    lets the Config decide (OQ-ENTS-3 A) just as the old implicit path did.

    Usage in a test::

        write_default_suggested(target)
        result = runner.invoke(cli, ["process", str(target),
                                     "--from-suggested", "--dry-run"])
    """
    data = {
        "version": 1,
        "target": target_dir.name,
        "preset": preset,
        "registration": {
            "method": registration_method,
            "max_rotation_deg": 2.0,
        },
        "debayer": {"method": debayer_method},
        "pcc": {"enabled": None},
        "source": "test_fixture",
    }
    out = target_dir / "suggested.yaml"
    out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return out
