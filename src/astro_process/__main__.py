"""Module entry-point parity for ``python -m astro_process`` (FU-1).

This forwards to the same CLI as the ``astra`` console script
(``[project.scripts] astra = "astro_process.cli:cli"``), so both have equal
precedence and read the same distribution metadata (``astro_process.__version__``
/ ``cli._resolve_cli_version()``). ``python -m astra`` is NOT supported
(``packages = ["src/astro_process"]``) — use ``astra`` or ``python -m astro_process``.

Version precedence documented in ``astro_process/__init__.py``:
``pyproject.toml`` (SSOT) -> installed metadata -> ``__version__`` -> CHANGELOG -> git tag.
"""

from .cli import cli

if __name__ == "__main__":
    cli()
