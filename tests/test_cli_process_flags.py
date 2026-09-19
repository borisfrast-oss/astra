"""Tests for T4 CLI P0 Mini-Fix — tote Flags `process --resume` + `--output/-o`.

Proposal: orion/_work/boris/proposal-cli-p0-minifix.md (tess @84c7a4d)
AC-1: --resume → Exit 2 with verworfen + archive hint (explicit guard, before all others)
AC-2: --output/-o → removed → Exit 2 no such option
AC-3: --help lists neither --output/-o, --resume still visible (explicit guard, deviation documented)
Scope: only src/astro_process/cli.py + this test + help snapshot

Decision on AC-3 (documented deviation):
  Proposal §3 says resume Flag behalten als Guard (nicht hidden) with explicit error,
  while AC-3 expects Help lists neither. Keeping Guard means Help still shows
  --resume (1 line remains). We implement explicit guard per Tess instruction
  (bevorzuge expliziten Error) and accept Help deviation: --output gone, --resume visible.
  See test_ac3_help_clean.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from conftest import write_default_suggested  # noqa: E402
from astro_process.cli import cli  # noqa: E402


def _make_light_fits(path: Path, exptime: float = 15.0, gain: int = 60) -> Path:
    data = np.full((32, 32), 100.0, dtype=np.float32)
    hdu = fits.PrimaryHDU(data)
    hdu.header["EXPTIME"] = float(exptime)
    hdu.header["GAIN"] = int(gain)
    hdu.header["OBJECT"] = "TestTarget"
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def _make_target_with_lights(root: Path, name: str = "TestTarget", n_lights: int = 3) -> Path:
    target = root / name
    lights = target / "lights"
    lights.mkdir(parents=True, exist_ok=True)
    for i in range(n_lights):
        _make_light_fits(lights / f"light_{i:04d}.fits")
    return target


# ─────────────────────────────────────────────────────────────────
# AC-1: --resume → Exit 2 explicit guard
# ─────────────────────────────────────────────────────────────────


class TestAC1ResumeRemoved:
    """AC-1: `astra process <target> --resume --from-suggested <f>` → Exit 2 verworfen."""

    def test_process_resume_explicit_guard(self, tmp_path):
        target = _make_target_with_lights(tmp_path, n_lights=2)
        suggested = write_default_suggested(target)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "process",
                str(target),
                "--resume",
                "--from-suggested",
                str(suggested),
            ],
        )

        assert result.exit_code == 2, f"Expected Exit 2, got {result.exit_code}\n{result.output}"
        # Proposal exact message: process.resume.removed: --resume is deprecated, use --limit/--group (see _work/archive/2026-09-13-resume-removed/)
        assert "deprecated" in result.output, f"Missing 'deprecated' in: {result.output}"
        assert "archive/2026-09-13-resume-removed" in result.output, f"Missing archive hint in: {result.output}"
        assert "process.resume.removed" in result.output, f"Missing code in: {result.output}"

    def test_process_resume_precedence_over_limit_guard(self, tmp_path):
        """Precedence: --resume guard must fire before --limit+--resume guard (669)."""
        target = _make_target_with_lights(tmp_path, n_lights=2)
        suggested = write_default_suggested(target)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "process",
                str(target),
                "--resume",
                "--limit",
                "5",
                "--from-suggested",
                str(suggested),
            ],
        )

        assert result.exit_code == 2, f"Expected Exit 2, got {result.exit_code}\n{result.output}"
        # Must be the explicit resume.removed error, not the old limit+resume message
        assert "process.resume.removed" in result.output
        assert "deprecated" in result.output


# ─────────────────────────────────────────────────────────────────
# AC-2: --output/-o removed → Exit 2 no such option
# ─────────────────────────────────────────────────────────────────


class TestAC2OutputRemoved:
    """AC-2: `astra process <target> --output /tmp/x --from-suggested <f>` → Exit 2 no such option."""

    def test_process_output_removed_long(self, tmp_path):
        target = _make_target_with_lights(tmp_path, n_lights=2)
        suggested = write_default_suggested(target)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "process",
                str(target),
                "--output",
                "/tmp/x",
                "--from-suggested",
                str(suggested),
            ],
        )

        assert result.exit_code == 2, f"Expected Exit 2, got {result.exit_code}\n{result.output}"
        # Click error for unknown option
        assert "no such option" in result.output.lower(), f"Missing 'no such option' in: {result.output}"
        assert "--output" in result.output, f"Missing '--output' in: {result.output}"

    def test_process_output_removed_short(self, tmp_path):
        target = _make_target_with_lights(tmp_path, n_lights=2)
        suggested = write_default_suggested(target)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "process",
                str(target),
                "-o",
                "/tmp/x",
                "--from-suggested",
                str(suggested),
            ],
        )

        assert result.exit_code == 2, f"Expected Exit 2, got {result.exit_code}\n{result.output}"
        assert "no such option" in result.output.lower(), f"Missing 'no such option' in: {result.output}"
        # short -o should also be reported
        assert "-o" in result.output or "--output" in result.output


# ─────────────────────────────────────────────────────────────────
# AC-3: --help clean — --output gone, --resume still visible (deviation)
# ─────────────────────────────────────────────────────────────────


class TestAC3HelpClean:
    """AC-3: `astra process --help` — --output/-o removed, --resume deviation documented.

    Proposal AC-3 expects Help lists neither flag (-2 lines).
    Tess-Entscheidung (plan.md §Entscheidungen/T4): implement explicit Error for --resume,
    Flag NOT hidden. Therefore Help still lists --resume (1 line remains, not 0).
    Deviation is intentional for better user guidance (archive link).
    If strict AC-3 (0 lines) is required, alternative is to remove --resume completely
    (both → no such option). Current implementation: explicit guard = 1 line remains.
    """

    def test_help_no_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "--help"])

        assert result.exit_code == 0, f"Help failed: {result.output}"
        # --output / -o must be gone
        assert "--output" not in result.output, f"'--output' still in help:\n{result.output}"
        # Check that standalone -o is not listed as alias for output (avoid false positive on other -o)
        # The removed option was "--output, -o" pair; ensure "-o," not present near output
        # Simpler: help must not contain the removed option's help text "Output directory"
        assert "Output directory" not in result.output, f"'Output directory' still in help"

    def test_help_resume_visible_deviation(self):
        """Documents deviation: --resume stays visible because explicit guard is not hidden."""
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "--help"])

        assert result.exit_code == 0
        # With explicit guard (non-hidden), --resume is still listed
        # This asserts the chosen design (explicit error) — AC-3 strict would expect not in.
        assert "--resume" in result.output, (
            "Deviation documented: --resume Guard is not hidden, so Help still shows '--resume'. "
            "If AC-3 strict (0 lines) required, remove --resume option entirely. Current design "
            f"keeps guard for user guidance. Help output:\n{result.output}"
        )
        # If project later decides to remove --resume entirely, this test will fail
        # and should be updated to assert "--resume" not in output.lower().
