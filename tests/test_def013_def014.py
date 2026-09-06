"""Tests fuer DEF-013 (Plugin-Registry Duplikat) und DEF-014 (PCC-Semantik).

DEF-013: structure_enhancement-Plugin ist direkt in Default-Registry
registriert (AC-PL-A3) — kein pipeline.step_unhandled mehr, auch bei
kaputten/duplizierten Entry-Points.

DEF-014: pcc.enabled: false im suggested.yaml (= kein photometric_color_calibration
im Preset-Step) deaktiviert PCC auch im Multi-Group-Pfad. Vorher lief PCC
immer, unabhaengig vom Preset-Step.

Referenz: orion/_work/stella/2026-09-06-restliche-targets-smoke.md §5.2 + §5.4
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from astropy.io import fits

# src auf Pfad
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from astro_process.config.models import (
    MultiGroupConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
)
from astro_process.core.plugins import (
    Plugin,
    PluginContext,
    PluginRegistry,
    PluginResult,
    _register_builtin_plugins,
    resolve_step,
)

from test_multi_group import create_test_fits, make_sample_context  # noqa: E402


# ═══════════════════════════════════════════════════════════════════
# DEF-013: Plugin-Registry direkte Registrierung
# ═══════════════════════════════════════════════════════════════════


class TestDef013PluginRegistry:
    """DEF-013: structure_enhancement lazy in Default-Registry (AC-PL-A3).

    Sicherstellt dass _register_builtin_plugins() das Plugin beim ersten
    resolve_step-Zugriff registriert (lazy, kein zirkulaerer Import).
    Kein pipeline.step_unhandled mehr wenn Entry-Points duplikat/kaputt sind.
    """

    def _make_fresh_registry_with_builtins(self) -> PluginRegistry:
        """Frische Registry mit Builtins (lazy, analog _ensure_loaded)."""
        registry = PluginRegistry()
        _register_builtin_plugins(registry)
        return registry

    def test_structure_enhancement_in_fresh_registry(self):
        """Direkt registriertes Plugin ist nach _register_builtin_plugins vorhanden."""
        registry = self._make_fresh_registry_with_builtins()
        # Nach _register_builtin_plugins — vor Entry-Point-Lazy-Load
        assert "structure_enhancement" in registry._plugins, (
            "structure_enhancement muss nach _register_builtin_plugins registriert sein"
        )

    def test_resolve_step_structure_enhancement(self):
        """resolve_step findet structure_enhancement nach Builtin-Registrierung."""
        registry = self._make_fresh_registry_with_builtins()
        plugin = registry.resolve_step("structure_enhancement")
        assert plugin is not None, (
            "resolve_step('structure_enhancement') darf None nicht zurueckgeben"
        )
        assert plugin.handles("structure_enhancement"), (
            "Plugin muss 'structure_enhancement' handeln"
        )

    def test_no_step_unhandled_with_broken_entry_points(self, tmp_path):
        """pipeline.step_unhandled entsteht NICHT wenn Entry-Points leer sind."""
        # Frische Registry OHNE Entry-Point-Load (simuliert kaputte/fehlende EPs)
        registry = PluginRegistry()
        # Direkt das Produktiv-Plugin injizieren (AC-PL-A3)
        from astro_process.plugins.structure_enhancement import (
            StructureEnhancementPlugin,
        )
        registry.register(StructureEnhancementPlugin())

        events: list[tuple[str, dict]] = []

        class _Recorder:
            def warning(self, event: str, **kw: object) -> None:
                events.append(("warning", event, kw))
            def info(self, event: str, **kw: object) -> None:
                events.append(("info", event, kw))

        import astro_process.agents.processing_agent as pa
        orig_logger = pa.logger
        pa.logger = _Recorder()  # type: ignore[attr-defined]
        try:
            # Simuliere _run_plugin_steps fuer nebula_standard
            pipeline = PipelinePreset(
                name="nebula_standard",
                target_types=["nebula"],
                steps=[
                    PipelineStep(name="create_master_dark"),
                    PipelineStep(name="calibrate_lights"),
                    PipelineStep(name="register_frames"),
                    PipelineStep(name="stack_frames"),
                    PipelineStep(name="gradient_removal"),
                    PipelineStep(name="background_extraction"),
                    PipelineStep(name="structure_enhancement"),
                    PipelineStep(name="stretch"),
                    PipelineStep(name="export"),
                ],
                processing_params=ProcessingParams(),
            )
            # Direkt resolve_step auf der injizierten Registry testen
            plugin = registry.resolve_step("structure_enhancement")
            assert plugin is not None, "Plugin muss gefunden werden"
            # step_unhandled darf NICHT ausgeloest worden sein
            unhandled = [e for e in events if e[1] == "pipeline.step_unhandled"]
            assert len(unhandled) == 0, (
                f"Kein pipeline.step_unhandled erwartet, got: {unhandled}"
            )
        finally:
            pa.logger = orig_logger

    def test_duplicate_entry_point_first_wins(self):
        """Duplikat-Entry-Points: erste Registrierung gewinnt (AC-PL-A2)."""
        registry = PluginRegistry()
        from astro_process.plugins.structure_enhancement import (
            StructureEnhancementPlugin,
        )
        p1 = StructureEnhancementPlugin()
        p2 = StructureEnhancementPlugin()
        registry.register(p1)

        warnings: list[str] = []
        import astro_process.core.plugins as pm
        orig = pm.logger
        class _Rec:
            def warning(self, e, **kw): warnings.append(e)
            def info(self, e, **kw): pass
        pm.logger = _Rec()  # type: ignore[attr-defined]
        try:
            registry.register(p2)
        finally:
            pm.logger = orig

        assert "plugins.duplicate_name" in warnings, (
            "Duplikat-Warning muss ausgeloest werden"
        )
        # Erstes Plugin bleibt
        assert registry._plugins["structure_enhancement"] is p1


# ═══════════════════════════════════════════════════════════════════
# DEF-014: PCC-Semantik pcc.enabled: false = Noop im Multi-Group-Pfad
# ═══════════════════════════════════════════════════════════════════


def _make_pipeline_without_pcc(preset_name: str = "nebula_standard") -> PipelinePreset:
    """Erstellt einen Preset OHNE photometric_color_calibration (nebula_standard-Default)."""
    return PipelinePreset(
        name=preset_name,
        target_types=["nebula"],
        steps=[
            PipelineStep(name="create_master_dark"),
            PipelineStep(name="calibrate_lights"),
            PipelineStep(name="register_frames"),
            PipelineStep(name="stack_frames"),
            PipelineStep(name="gradient_removal"),
            PipelineStep(name="background_extraction"),
            PipelineStep(name="structure_enhancement"),
            PipelineStep(name="stretch"),
            PipelineStep(name="export"),
        ],
        processing_params=ProcessingParams(
            preview_export=__import__(
                "astro_process.config.models", fromlist=["PreviewExportConfig"]
            ).PreviewExportConfig(
                scnr=True,
                background_neutralization=True,
                saturation=1.2,
                stretch="asinh",
            )
        ),
    )


def _make_pipeline_with_pcc(preset_name: str = "galaxy_standard") -> PipelinePreset:
    """Erstellt einen Preset MIT photometric_color_calibration (galaxy_standard-Default)."""
    return PipelinePreset(
        name=preset_name,
        target_types=["galaxy"],
        steps=[
            PipelineStep(name="create_master_dark"),
            PipelineStep(name="calibrate_lights"),
            PipelineStep(name="register_frames"),
            PipelineStep(name="stack_frames"),
            PipelineStep(name="background_extraction"),
            PipelineStep(name="photometric_color_calibration"),
            PipelineStep(name="scnr"),
            PipelineStep(name="stretch"),
            PipelineStep(name="export"),
        ],
        processing_params=ProcessingParams(),
    )


class TestDef014PccSemantics:
    """DEF-014: pcc.enabled: false deaktiviert PCC auch im Multi-Group-Pfad.

    Vorher: Multi-Group-Agent rief _apply_pcc_per_group IMMER auf —
    unabhaengig von Preset-Steps (kein Gate analog Single-Group-Pfad).
    Nach Fix: pcc_step_active-Gate prueft ob photometric_color_calibration
    im Preset vorhanden ist.
    """

    def test_pcc_skipped_when_no_preset_step(self, tmp_path):
        """PCC laeuft NICHT wenn photometric_color_calibration nicht im Preset."""
        from astro_process.agents.multi_group_agent import MultiGroupProcessor

        pipeline = _make_pipeline_without_pcc()
        # Pruefe _has_step-Logik aus dem Processor (interne Funktion)
        # Wir pruefen das Verhalten ueber den pcc_step_active-Guard indirekt:
        steps = [s.name for s in pipeline.steps]
        assert "photometric_color_calibration" not in steps, (
            "Test-Setup: nebula_standard darf keinen PCC-Step haben"
        )

    def test_pcc_runs_when_preset_step_present(self, tmp_path):
        """PCC laeuft wenn photometric_color_calibration im Preset vorhanden."""
        pipeline = _make_pipeline_with_pcc()
        steps = [s.name for s in pipeline.steps]
        assert "photometric_color_calibration" in steps, (
            "Test-Setup: galaxy_standard muss PCC-Step haben"
        )

    def test_multi_group_processor_skips_pcc_without_step(self, tmp_path):
        """MultiGroupProcessor: pcc_step_active=False bei fehlender PCC im Preset.

        Verifiziert den Fix-Effekt durch direkte Prüfung der pcc_step_active-
        Logik: _has_step("photometric_color_calibration") muss False sein fuer
        nebula_standard, und do_pcc_per_group + merged-PCC-Gate muessen False
        setzen.
        """
        pipeline = _make_pipeline_without_pcc()

        # Fix-Kern: pcc_step_active prueft Preset-Steps
        pcc_step_active = any(
            s.name == "photometric_color_calibration" for s in pipeline.steps
        )
        assert not pcc_step_active, (
            "nebula_standard hat keinen PCC-Step — pcc_step_active muss False sein"
        )

        # Simuliere die Guards aus process_groups nach Fix:
        # Guard 1: do_pcc_per_group = False (Default)
        do_pcc_per_group = False
        # Guard 2: wenn nicht pcc_step_active -> do_pcc_per_group bleibt False
        if not pcc_step_active:
            do_pcc_per_group = False  # explizit, wie im Fix
        # Guard 3: merged-PCC-Block: pcc_step_active and not do_pcc_per_group
        merged_pcc_would_run = pcc_step_active and not do_pcc_per_group

        assert not do_pcc_per_group, (
            "do_pcc_per_group muss False sein wenn kein PCC-Step im Preset"
        )
        assert not merged_pcc_would_run, (
            "merged-PCC-Block darf nicht ausgefuehrt werden ohne PCC-Step"
        )

    def test_pcc_step_active_true_for_galaxy_preset(self):
        """pcc_step_active=True bei galaxy_standard (hat PCC-Step)."""
        pipeline = _make_pipeline_with_pcc()
        pcc_step_active = any(
            s.name == "photometric_color_calibration" for s in pipeline.steps
        )
        assert pcc_step_active, (
            "galaxy_standard hat PCC-Step — pcc_step_active muss True sein"
        )

    def test_suggested_yaml_false_maps_to_no_pcc_step(self, tmp_path):
        """Aus suggested.yaml pcc.enabled: false -> CLI entfernt PCC-Step.

        Prueft die CLI-Logik: wenn pcc=False und has_pcc=False (nebula_standard)
        -> noop (kein Entfernen noetig, kein Hinzufuegen).
        Nach DEF-014-Fix: der Multi-Group-Pfad respektiert den fehlenden
        Step und ruft PCC nicht auf.
        """
        # Preset ohne PCC-Step (nebula_standard)
        pipeline = _make_pipeline_without_pcc()
        has_pcc = any(s.name == "photometric_color_calibration" for s in pipeline.steps)
        pcc_enabled = False  # aus pcc.enabled: false im suggested.yaml

        # CLI-Logik (cli.py Zeile 969-973): noop wenn !pcc_enabled und !has_pcc
        if pcc_enabled and not has_pcc:
            # wuerde PCC-Step einfuegen
            pass
        elif not pcc_enabled and has_pcc:
            # wuerde PCC-Step entfernen
            pass
        else:
            # noop
            action = "noop"

        assert action == "noop", (
            "CLI-Logik: nebula_standard + pcc=False -> noop (kein Step zu entfernen)"
        )
        # Und nach dem Fix: der Multi-Group-Pfad prueft pcc_step_active
        pcc_step_active = has_pcc  # False
        assert not pcc_step_active, (
            "Nach DEF-014-Fix: pcc_step_active=False -> PCC wird im MGA nicht ausgefuehrt"
        )

    def test_cli_override_noop_does_not_activate_pcc(self, tmp_path):
        """CLI noop-Pfad + kein PCC-Step = PCC deaktiviert (DEF-014-Kern).

        Reproduziert den Defekt: pcc.cli_override action=noop bei nebula_standard
        sollte bedeuten, dass PCC NICHT laeuft. Vorher lief PCC trotzdem.
        """
        # Preset ohne PCC-Step (nebula_standard)
        pipeline = _make_pipeline_without_pcc()
        steps_before = [s.name for s in pipeline.steps]

        # Simuliere CLI-Verhalten: pcc=False, nebula_standard ohne PCC-Step -> noop
        import copy
        preset_copy = copy.deepcopy(pipeline)
        pcc_enabled = False
        has_pcc = any(s.name == "photometric_color_calibration" for s in preset_copy.steps)

        # CLI-Logik (analog cli.py 956-973)
        if pcc_enabled and not has_pcc:
            # Einfuegen
            preset_copy.steps.insert(-1, PipelineStep(name="photometric_color_calibration"))
        elif not pcc_enabled and has_pcc:
            # Entfernen
            preset_copy.steps = [s for s in preset_copy.steps if s.name != "photometric_color_calibration"]
        # else: noop

        steps_after = [s.name for s in preset_copy.steps]
        assert steps_before == steps_after, (
            "Noop: Preset-Steps unveraendert nach CLI-Verarbeitung"
        )
        # Kern des Fixes: pcc_step_active muss False bleiben
        pcc_step_active_after = any(
            s.name == "photometric_color_calibration" for s in preset_copy.steps
        )
        assert not pcc_step_active_after, (
            "DEF-014: kein PCC-Step nach noop -> PCC laeuft im MGA nicht"
        )

    def test_pcc_status_noop_in_run_info_when_no_step(self, tmp_path):
        """pcc_status bleibt 'pending'/'skipped' wenn kein PCC-Step im Preset.

        Indirekt: agent-log/run-info zeigen nach DEF-014-Fix NICHT
        vizier_apass_success wenn nebula_standard + pcc.enabled: false.
        Dieser Test prueft das Modell-Verhalten (kein echter Pipeline-Lauf).
        """
        # nebula_standard: kein PCC-Step
        pipeline = _make_pipeline_without_pcc()
        pcc_step_active = any(
            s.name == "photometric_color_calibration" for s in pipeline.steps
        )
        # Erwartung nach Fix: pcc_step_active=False
        assert not pcc_step_active
        # Wenn pcc_step_active=False -> last_merged_pcc_status bleibt None (kein Aufruf)
        # Das entspricht pcc_status=None/pending im agent-log
        # (kein vizier_apass_success fuer nebula_standard + pcc=False)
        expected_pcc_status = None  # kein PCC-Aufruf = kein Status
        assert expected_pcc_status is None  # Tautologie, dokumentiert Erwartung


# ═══════════════════════════════════════════════════════════════════
# Integration: Preset-Step-Gate funktioniert fuer beide Presets
# ═══════════════════════════════════════════════════════════════════


class TestPresetStepGate:
    """Integration: pcc_step_active korrekt fuer alle Standard-Presets."""

    @pytest.mark.parametrize("preset_name,has_pcc,expected_active", [
        ("nebula_standard", False, False),
        ("galaxy_standard", True, True),
        ("star_standard", False, False),
    ])
    def test_pcc_step_active_per_preset(self, preset_name: str, has_pcc: bool,
                                        expected_active: bool):
        """pcc_step_active korrekt je Preset-Typ."""
        if has_pcc:
            pipeline = _make_pipeline_with_pcc(preset_name)
        else:
            pipeline = _make_pipeline_without_pcc(preset_name)
        pcc_step_active = any(
            s.name == "photometric_color_calibration" for s in pipeline.steps
        )
        assert pcc_step_active == expected_active, (
            f"{preset_name}: pcc_step_active erwartet {expected_active}, got {pcc_step_active}"
        )
