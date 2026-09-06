"""PL-D: Deterministisches Test-Plugin (dummy_step) — Referenz fuer das
Plugin-Interface (v12-plugin-interface.md, PL-D).

Handelt den fiktiven Step ``dummy_step`` und schreibt einen Marker-Artefakt
(``dummy_step_marker.txt``) in den Context-Working-Dir. Dient als
Referenz-Implementierung und fuer Integrationstests (AC-PL-D2) — kein
echter Produktiv-Plugin in v1.2 (OQ-PL-3-A).
"""

from __future__ import annotations

from astro_process.core.plugins import Plugin, PluginContext, PluginResult


class DummyPlugin(Plugin):
    """Handelt ``dummy_step`` und schreibt einen Marker-Artefakt."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def version(self) -> str:
        return "1.0.0"

    def handles(self, step_name: str) -> bool:
        return step_name == "dummy_step"

    def run(self, context: PluginContext) -> PluginResult:
        marker = context.working_dir / "dummy_step_marker.txt"
        marker.write_text("dummy\n", encoding="utf-8")
        return PluginResult(
            ok=True,
            step="dummy_step",
            artifact=marker,
            log_fields={"marker": str(marker)},
        )
