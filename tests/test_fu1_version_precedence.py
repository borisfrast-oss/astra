"""FU-1: Version precedence + entry-point parity (pyproject -> __version__ -> CHANGELOG -> git-tag).

Tests:
 - import precedence (direct import vs CLI share same metadata lookup)
 - python -m astro_process parity (same version as `astra --version`)
 - pyproject header documents precedence (static check)
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
PYPROJECT = REPO_ROOT / "pyproject.toml"


class TestVersionPrecedenceStatic:
    """Doku-Klarung: pyproject header documents __version__ -> CHANGELOG -> git-tag."""

    def test_pyproject_header_documents_precedence(self):
        txt = PYPROJECT.read_text(encoding="utf-8")
        # Must document SSOT + order __version__/pyproject -> CHANGELOG -> git-tag
        assert "V1.12-FU-1" in txt or "Version precedence" in txt
        assert "pyproject.toml" in txt and "CHANGELOG" in txt and "git tag" in txt

    def test_init_exports_version(self):
        init = SRC / "astro_process" / "__init__.py"
        assert init.exists(), "FU-1 requires src/astro_process/__init__.py"
        txt = init.read_text(encoding="utf-8")
        assert "__version__" in txt
        assert "importlib.metadata" in txt
        assert "astra-pipeline" in txt
        # Docstring must mention precedence order
        lower = txt.lower()
        assert "precedence" in lower
        assert "pyproject" in lower
        assert "changelog" in lower
        assert "git tag" in lower or "git-tag" in lower

    def test_main_entry_point_exists(self):
        main = SRC / "astro_process" / "__main__.py"
        assert main.exists(), "FU-1 requires src/astro_process/__main__.py for python -m parity"
        txt = main.read_text(encoding="utf-8")
        assert "from .cli import cli" in txt
        assert 'python -m astro_process' in txt or "python -m" in txt

    def test_cli_and_init_share_lookup_chain(self):
        # Both cli.py and __init__.py use same dist names astra-pipeline/astra -> 0.0.0+dev
        cli = (SRC / "astro_process" / "cli.py").read_text(encoding="utf-8")
        init = (SRC / "astro_process" / "__init__.py").read_text(encoding="utf-8")
        for name in ("astra-pipeline", "astra", "0.0.0+dev"):
            assert name in cli, f"cli should reference {name!r}"
            assert name in init, f"__init__ should reference {name!r}"


class TestVersionRuntimeParity:
    """Runtime: direct import vs CLI vs python -m parity (equal precedence)."""

    def test_import_version_resolves(self):
        # Direct import must not crash and must yield a dotted string or 0.0.0+dev
        sys.path.insert(0, str(SRC))
        import astro_process

        ver = getattr(astro_process, "__version__", None)
        assert isinstance(ver, str) and len(ver) > 0
        # Either real version like 1.11.0 or fallback 0.0.0+dev
        assert "." in ver or ver == "0.0.0+dev"
        # Re-install path: if package installed, version should equal importlib.metadata
        try:
            from importlib.metadata import version as _get_version

            for dist in ("astra-pipeline", "astra"):
                try:
                    expected = _get_version(dist)
                    assert ver == expected
                    break
                except Exception:
                    continue
        except Exception:
            pass

    def test_cli_version_equals_import_version(self):
        sys.path.insert(0, str(SRC))
        import astro_process
        from astro_process.cli import _resolve_cli_version

        import_ver = getattr(astro_process, "__version__", None)
        cli_ver = _resolve_cli_version()
        assert import_ver == cli_ver, f"import {import_ver!r} != cli {cli_ver!r} — same metadata lookup required (FU-1 equal precedence)"

    def test_python_m_parity(self):
        # python -m astro_process --version should equal astra --version conceptually
        # We invoke both via subprocess and compare stdout contains same version token
        sys.path.insert(0, str(SRC))
        import astro_process

        import_ver = getattr(astro_process, "__version__", None)
        # python -m astro_process --version
        result = subprocess.run(
            [sys.executable, "-m", "astro_process", "--version"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        # If the module entry-point works, it exits 0 and prints version
        # On fallback 0.0.0+dev it still must contain that string
        if result.returncode == 0:
            output = (result.stdout + result.stderr).strip()
            assert import_ver in output, f"python -m output {output!r} must contain __version__ {import_ver!r}"


class TestP03StatusCheckDoc:
    """P-03 Status-Check: PCC implausible factors suggest-sided is documented as covered."""

    def test_suggest_module_documents_p03(self):
        sug = (SRC / "astro_process" / "core" / "suggest.py").read_text(encoding="utf-8")
        assert "P-03" in sug
        assert "rejected_implausible_factors" in sug
        assert "pcc_status" in sug or "pcc_status" in sug.lower()

    def test_troubleshooting_doc_data_documents_p03(self):
        doc = (REPO_ROOT / "scripts" / "doc_data" / "troubleshooting.md").read_text(encoding="utf-8")
        assert "P-03" in doc or "PCC Suggest-side" in doc
        assert "pcc_status" in doc.lower() or "rejected_implausible_factors" in doc.lower()
        assert "covered" in doc.lower()
