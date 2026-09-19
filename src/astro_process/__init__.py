"""astro_process package — version SSOT and entry-point parity (FU-1).

Version precedence (DEF-013 FU-1, clarified 2026-09-08):
    1. ``pyproject.toml`` ``[project] version`` is the SSOT (hatchling, hard-coded,
       not dynamic). Version bump is the first step of the release-process
       (``release-process.md`` Phase 5, step 1: bump in monorepo SSOT, then sync
       to ``builds/astra/release-repo``).
    2. At runtime the installed distribution metadata is read via
       ``importlib.metadata.version("astra-pipeline")`` (legacy fallback
       ``"astra"``). Both ``astro_process.__version__`` (this module) and
       ``astra --version`` (``cli._resolve_cli_version()``) use the *identical*
       lookup chain, so import and CLI have equal precedence — neither
       hard-codes the version, both read the same wheel/editable metadata.
       Fallback when running from source without install: ``"0.0.0+dev"``.
    3. ``CHANGELOG.md`` documents the human-readable notes per version
       (curated, Keep-a-Changelog, generated via ``git-cliff`` at release;
       it is *derived* from the pyproject version, never the source).
    4. Git tag ``v<version>`` (e.g. ``v1.11.0``) is created from the pyproject
       version at release time (publish-workflow trigger). Tag never drives
       pyproject; pyproject drives tag — order is ``__version__/pyproject
       -> CHANGELOG -> git-tag``.

Entry-point parity (FU-1):
    - Canonical: ``astra`` console script
      (``[project.scripts] astra = "astro_process.cli:cli"``, alias
      ``astro-process``). This is the documented command.
    - Module execution: ``python -m astro_process`` (via
      ``astro_process/__main__.py``) is byte-identical parity to ``astra``
      — same ``cli:cli`` entry, same metadata lookup. Precedence is equal;
      use whichever fits the environment.
    - ``python -m astra`` is NOT supported — there is no top-level package
      ``astra`` (``packages = ["src/astro_process"]``). Use ``astra`` or
      ``python -m astro_process``.
    - Direct import ``import astro_process; astro_process.__version__``
      yields the same string as ``astra --version`` / ``python -m astro_process
      --version`` (same importlib.metadata lookup).

P-03 note (suggest-side, PCC implausible factors):
    PCC ``rejected_implausible_factors`` cannot be known at ``astra suggest``
    time — it is a runtime Quality-Gate decision on the stacked frame (r/g/b
    factors vs. ``[0.5, 2.0]``). Per stella 07.09., suggest is structurally
    unable to predict it. Coverage is considered satisfied downstream via
    ``pcc_status`` in ``agent-log.yaml``/``run-info.json`` (three-valued
    ``None``/``timeout``/``success``, FU-2), plus QC color context
    (``qc.py`` ``_compute_color`` G-excess >15% + PCC status) — see
    ``defects/DEF-013`` FU-1/FU-2 and ``backlog.md`` V1.12-FU-1.
"""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _get_version
except ImportError:  # pragma: no cover - Py311 only fallback
    from importlib_metadata import PackageNotFoundError  # type: ignore[no-redef]
    from importlib_metadata import version as _get_version  # type: ignore[no-redef]


def _resolve_version() -> str:
    """Resolve installed distribution version (same chain as cli._resolve_cli_version)."""
    for dist_name in ("astra-pipeline", "astra"):
        try:
            return _get_version(dist_name)
        except PackageNotFoundError:
            pass
    return "0.0.0+dev"


__version__ = _resolve_version()
__all__ = ["__version__"]
