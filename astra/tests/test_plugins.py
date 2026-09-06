"""PL-D (AC-PL-D1): Registry-/Plugin-Unit-Tests.

Abgedeckt:
- Plugin-ABC: name/version/handles/run (AC-PL-A1).
- Registry: injizierte Instanzen (AC-PL-A3), resolve_step-None-Fall,
  Duplikat-Namen -> erste gewinnt + Warning (AC-PL-A2).
- Entry-Point-Discovery: lazy, Ladefehler/Invalid -> Warning, kein Crash.

Kein Netz, keine Installation: Alle Entry-Points werden via
``unittest.mock.patch`` simuliert; das Dummy-Plugin wird direkt aus
``tests/fixtures/plugin_dummy.py`` geladen.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure src + tests dir on the path ────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astro_process.agents.processing_agent as processing_agent  # noqa: E402
import astro_process.core.plugins as plugins_mod  # noqa: E402
from astro_process.agents.processing_agent import ProcessingAgent  # noqa: E402
from astro_process.config.models import (  # noqa: E402
    MultiGroupConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
)
from astro_process.core.plugins import (  # noqa: E402
    PLUGIN_ENTRY_POINT_GROUP,
    Plugin,
    PluginContext,
    PluginRegistry,
    PluginResult,
    resolve_step,
)
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
)

from test_multi_group import create_test_fits, make_sample_context  # noqa: E402


class _LogRecorder:
    """Ersetzt den structlog-Modul-Logger und sammelt Events (Muster
    test_registration._LogRecorder)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    @property
    def names(self) -> list[str]:
        return [e for e, _ in self.events]

    def has(self, name: str) -> bool:
        return name in self.names

    def events_named(self, name: str) -> list[tuple[str, dict]]:
        return [(n, k) for n, k in self.events if n == name]


def _load_dummy_plugin() -> Plugin:
    """Laedt die Dummy-Plugin-Fixture per Datei-Import (deterministisch)."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "plugin_dummy.py"
    spec = importlib.util.spec_from_file_location("plugin_dummy", fixture)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.DummyPlugin()


class _FailingPlugin(Plugin):
    """Plugin, dessen run() ok=False liefert (OQ-PL-4: Warning + Skip)."""

    @property
    def name(self) -> str:
        return "failing"

    @property
    def version(self) -> str:
        return "0.0.1"

    def handles(self, step_name: str) -> bool:
        return step_name == "failing_step"

    def run(self, context: PluginContext) -> PluginResult:
        return PluginResult(ok=False, step="failing_step", log_fields={"reason": "boom"})


class _BrokenHandlesPlugin(Plugin):
    """Plugin, dessen handles() wirft — muss uebersprungen werden (E1)."""

    @property
    def name(self) -> str:
        return "broken_handles"

    @property
    def version(self) -> str:
        return "0.0.1"

    def handles(self, step_name: str) -> bool:
        raise RuntimeError("handles broken")

    def run(self, context: PluginContext) -> PluginResult:
        return PluginResult(ok=True, step="x")


class TestPluginAbc:
    """AC-PL-A1: ABC-Felder + PluginResult + PluginContext."""

    def test_dummy_plugin_is_plugin(self):
        plugin = _load_dummy_plugin()
        assert isinstance(plugin, Plugin)
        assert plugin.name == "dummy"
        assert plugin.version == "1.0.0"

    def test_dummy_plugin_handles_dummy_step(self):
        plugin = _load_dummy_plugin()
        assert plugin.handles("dummy_step")
        assert not plugin.handles("stack_frames")

    def test_dummy_plugin_run_writes_marker(self, tmp_path):
        plugin = _load_dummy_plugin()
        context = PluginContext(working_dir=tmp_path, output_dir=tmp_path)
        result = plugin.run(context)

        assert result.ok is True
        assert result.step == "dummy_step"
        assert result.artifact is not None
        assert result.artifact.name == "dummy_step_marker.txt"
        assert result.artifact.exists()
        assert (tmp_path / "dummy_step_marker.txt").read_text(encoding="utf-8") == "dummy\n"

    def test_plugin_result_defaults(self):
        result = PluginResult(ok=False, step="s")
        assert result.artifact is None
        assert result.log_fields == {}


class TestPluginRegistry:
    """AC-PL-A2/A3: Registry-Verhalten (injizierte Instanzen)."""

    def test_register_and_resolve_step(self):
        registry = PluginRegistry(injected=[_load_dummy_plugin()])
        assert registry.resolve_step("dummy_step") is not None
        assert registry.resolve_step("stack_frames") is None

    def test_resolve_step_none_without_plugins(self):
        registry = PluginRegistry()
        assert registry.resolve_step("anything") is None

    def test_plugins_property_sorted(self):
        registry = PluginRegistry()
        # "failing" < "dummy" alphabetisch, aber Sortierung unabhaengig von Reihenfolge
        registry.register(_load_dummy_plugin())
        registry.register(_FailingPlugin())
        names = [p.name for p in registry.plugins]
        assert names == sorted(names)

    def test_duplicate_name_first_wins(self):
        registry = PluginRegistry(injected=[_load_dummy_plugin()])
        second = _load_dummy_plugin()  # gleicher Name "dummy"
        recorder = _LogRecorder()

        with patch("astro_process.core.plugins.logger", recorder):
            registry.register(second)

        # DEF-013: _register_builtin_plugins + Entry-Points leeren, damit
        # structure_enhancement den isolierten Duplikat-Test nicht stoert.
        with patch(
            "astro_process.core.plugins._register_builtin_plugins",
        ), patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[],
        ):
            plugins = registry.plugins

        assert len(plugins) == 1
        assert plugins[0].name == "dummy"
        # Erste Registrierung (Fixture-Instanz) gewinnt — die zweite ist weg.
        assert recorder.has("plugins.duplicate_name")

    def test_register_injected_before_entry_points(self):
        """AC-PL-A3: Injizierte Instanz gewinnt gegen Entry-Point-Duplikat."""
        registry = PluginRegistry(injected=[_load_dummy_plugin()])
        ep = _entry_point_mock("dummy", _load_dummy_plugin())
        recorder = _LogRecorder()

        # DEF-013: _register_builtin_plugins leeren, damit nur der Dummy-EP zaehlt.
        with patch("astro_process.core.plugins.logger", recorder), patch(
            "astro_process.core.plugins._register_builtin_plugins",
        ), patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[ep],
        ):
            registry.resolve_step("dummy_step")

        assert len(registry.plugins) == 1
        assert recorder.has("plugins.duplicate_name")

    def test_entry_points_loaded_lazy(self):
        """AC-PL-A2: Discovery erst bei Bedarf (kein Load beim Konstruktor)."""
        registry = PluginRegistry()
        with patch(
            "astro_process.core.plugins.importlib.metadata.entry_points"
        ) as mock_eps:
            registry.register(_load_dummy_plugin())
            mock_eps.assert_not_called()

        with patch(
            "astro_process.core.plugins.importlib.metadata.entry_points"
        ) as mock_eps:
            registry.resolve_step("dummy_step")
            mock_eps.assert_called_once_with(group=PLUGIN_ENTRY_POINT_GROUP)

    def test_entry_point_loaded_once(self):
        """Discovery laeuft genau einmal (Cache-Flag)."""
        registry = PluginRegistry()
        ep = _entry_point_mock("dummy", _load_dummy_plugin())
        with patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[ep],
        ) as mock_eps:
            registry.resolve_step("dummy_step")
            registry.resolve_step("dummy_step")
            mock_eps.assert_called_once()

    def test_entry_point_invalid_ignored(self):
        """Entry-Point liefert kein Plugin -> Warning, kein Crash."""
        registry = PluginRegistry()
        ep = _entry_point_mock("not_a_plugin", "nope")
        recorder = _LogRecorder()

        with patch("astro_process.core.plugins.logger", recorder), patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[ep],
        ):
            assert registry.resolve_step("dummy_step") is None

        assert recorder.has("plugins.entry_point_invalid")

    def test_entry_point_load_error_ignored(self):
        """ep.load() wirft -> Warning, resolve_step bleibt None."""
        registry = PluginRegistry()

        class _BoomEP:
            name = "boom_ep"

            def load(self):
                raise ImportError("cannot import boom_ep")

        recorder = _LogRecorder()
        with patch("astro_process.core.plugins.logger", recorder), patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[_BoomEP()],
        ):
            assert registry.resolve_step("dummy_step") is None

        assert recorder.has("plugins.entry_point_load_failed")

    def test_entry_point_subclass_instantiated(self):
        """Entry-Point liefert Plugin-Subklasse -> no-arg-Instanziierung."""
        registry = PluginRegistry()
        dummy_cls = _load_dummy_plugin().__class__
        with patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[_entry_point_mock("dummy", dummy_cls)],
        ):
            found = registry.resolve_step("dummy_step")

        assert found is not None
        assert found.name == "dummy"

    def test_broken_handles_skipped(self):
        """handles() wirft -> uebersprungen, andere Plugins bleiben erreichbar."""
        registry = PluginRegistry(
            injected=[_BrokenHandlesPlugin(), _load_dummy_plugin()]
        )
        recorder = _LogRecorder()
        with patch("astro_process.core.plugins.logger", recorder):
            assert registry.resolve_step("dummy_step") is not None
        assert recorder.has("plugins.handles_failed")


def _entry_point_mock(name: str, loaded):
    class _EP:
        def __init__(self, name, loaded):
            self.name = name
            self._loaded = loaded

        def load(self):
            return self._loaded

    return _EP(name, loaded)


class TestResolveStepFacade:
    """Modul-Fassade resolve_step(): Default-Registry bzw. explizite Registry."""

    def test_with_explicit_registry(self):
        registry = PluginRegistry(injected=[_load_dummy_plugin()])
        assert resolve_step("dummy_step", registry=registry) is not None
        assert resolve_step("unknown_step", registry=registry) is None

    def test_no_error_on_empty_default(self):
        """Smoke: Default-Registry wirft nicht, wenn nichts registriert ist."""
        assert resolve_step("whatever") is None


class TestPluginListCli:
    """PL-C (AC-PL-C1/C2): CLI `astra plugin list`."""

    def _invoke(self, *args: str):
        from click.testing import CliRunner

        from astro_process.cli import cli

        return CliRunner().invoke(cli, ["plugin", "list", *args])

    @staticmethod
    def _json_output(output: str):
        """Extrahiert den JSON-Teil der CLI-Ausgabe.

        B1 (Leo-Auftrag 2026-08-11): `config.loaded_from` (structlog-JSON)
        geht wie alle Pipeline-Logs auf stdout — der JSON-Array-Teil steht
        dahinter. structlog-Zeilen beginnen mit `{"event": ...}` und werden
        hier gefiltert.
        """
        import json as json_mod

        lines = [line for line in output.splitlines() if not line.startswith("{")]
        return json_mod.loads("\n".join(lines))

    def test_list_without_plugins_exit_zero(self):
        """AC-PL-C1: `astra plugin list` ohne installierte Plugins -> Exit 0,
        leere Liste, keine Fehler."""
        # DEF-013: Default-Registry + _register_builtin_plugins + Entry-Points leeren
        # — sonst laedt der lazy Cache das Builtin structure_enhancement in die
        # frisch erstellte Singleton-Registry.
        with patch(
            "astro_process.core.plugins._default_registry",
            PluginRegistry(),
        ), patch(
            "astro_process.core.plugins._register_builtin_plugins",
        ), patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[],
        ):
            result = self._invoke()
        assert result.exit_code == 0
        assert "Keine Plugins installiert" in result.output

    def test_list_json_without_plugins(self):
        """AC-PL-C1: `astra plugin list --json` ohne Plugins -> Exit 0, []."""
        # DEF-013: _register_builtin_plugins leeren (siehe test_list_without_plugins_exit_zero)
        with patch(
            "astro_process.core.plugins._default_registry",
            PluginRegistry(),
        ), patch(
            "astro_process.core.plugins._register_builtin_plugins",
        ), patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[],
        ):
            result = self._invoke("--json")
        assert result.exit_code == 0
        assert self._json_output(result.output) == []

    def test_list_shows_injected_plugin(self, monkeypatch):
        """AC-PL-C2: injiziertes Test-Plugin erscheint in der Liste."""
        import astro_process.core.plugins as plugins_mod

        registry = PluginRegistry(injected=[_load_dummy_plugin()])
        monkeypatch.setattr(plugins_mod, "_default_registry", registry)

        result = self._invoke()
        assert result.exit_code == 0
        assert "dummy" in result.output
        assert "1.0.0" in result.output

    def test_list_json_shows_injected_plugin(self, monkeypatch):
        """AC-PL-C2: `--json` enthaelt Name/Version des Test-Plugins."""
        import astro_process.core.plugins as plugins_mod

        registry = PluginRegistry(injected=[_load_dummy_plugin()])
        monkeypatch.setattr(plugins_mod, "_default_registry", registry)

        # DEF-013: _register_builtin_plugins + Entry-Points leeren, damit
        # structure_enhancement die JSON-Liste nicht aufblaeht.
        with patch(
            "astro_process.core.plugins._register_builtin_plugins",
        ), patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[],
        ):
            result = self._invoke("--json")
        assert result.exit_code == 0
        entries = self._json_output(result.output)
        assert len(entries) == 1
        assert entries[0]["name"] == "dummy"
        assert entries[0]["version"] == "1.0.0"

# ═══════════════════════════════════════════════════════════════════
# PL-B/PL-D: Plugin-Integration in run()/process_multi_group()
# (integriert aus test_plugins_processing.py)
# ═══════════════════════════════════════════════════════════════════












class _RaisingPlugin(Plugin):
    """Plugin, dessen run() eine Exception wirft (AC-PL-B2: Warning + Skip)."""

    @property
    def name(self) -> str:
        return "raising"

    @property
    def version(self) -> str:
        return "0.0.1"

    def handles(self, step_name: str) -> bool:
        return step_name == "raising_step"

    def run(self, context: PluginContext) -> PluginResult:
        raise RuntimeError("boom")


@pytest.fixture
def dummy_registry(monkeypatch: pytest.MonkeyPatch) -> PluginRegistry:
    """AC-PL-A3: Dummy-Plugin in die Default-Registry injizieren (Test-Hook)."""
    registry = PluginRegistry(injected=[_load_dummy_plugin()])
    monkeypatch.setattr(plugins_mod, "_default_registry", registry)
    return registry


def _run_agent(
    tmp_path: Path,
    steps: list[str],
    processing_params: ProcessingParams | None = None,
):
    """Minimaler run()-Aufruf (Muster test_processing_etappe2._run)."""
    agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
    context = SimpleNamespace(
        target=SimpleNamespace(name="TestTarget", ra=0.0, dec=0.0),
        equipment=SimpleNamespace(focal_length_mm=0.0, pixel_size_um=0.0),
    )
    pipeline = PipelinePreset(
        name="test",
        target_types=["nebula"],
        steps=[PipelineStep(name=s) for s in steps],
        processing_params=processing_params or ProcessingParams(),
    )
    return agent, agent.run(
        context,
        SimpleNamespace(calibrated_lights=[]),
        SimpleNamespace(debayered_frames=[]),
        pipeline,
    )


class TestPluginInRun:
    """AC-PL-B1/B2/D2/D3: run()-Pfad."""

    def test_dummy_plugin_executed_for_unknown_step(
        self, tmp_path: Path, monkeypatch, dummy_registry,
    ):
        """AC-PL-D2: Preset mit dummy_step + injiziertem Plugin -> Plugin
        ausgefuehrt, Marker-Artefakt existiert, kein Abbruch, keine
        Unhandled-Warning."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent, "logger", rec)

        _agent, result = _run_agent(tmp_path, ["dummy_step"])

        events = rec.events_named("pipeline.plugin_complete")
        assert len(events) == 1
        assert events[0][1]["plugin"] == "dummy"
        assert events[0][1]["step"] == "dummy_step"
        assert (tmp_path / "out" / "dummy_step_marker.txt").exists()
        assert rec.events_named("pipeline.step_unhandled") == []
        assert result is not None

    def test_unknown_step_without_plugin_warns(
        self, tmp_path: Path, monkeypatch,
    ):
        """AC-PL-D3 (E1-Close): unbekannter Step ohne Plugin -> Warning
        `pipeline.step_unhandled`, Ergebnis gueltig (Exit 0 mit Warnings)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent, "logger", rec)

        _agent, result = _run_agent(tmp_path, ["mystery_processor"])

        events = rec.events_named("pipeline.step_unhandled")
        assert len(events) == 1
        assert events[0][1]["step"] == "mystery_processor"
        assert result is not None

    def test_plugin_failure_skips_with_warning(
        self, tmp_path: Path, monkeypatch,
    ):
        """AC-PL-B2: Plugin-Fehler (ok=False) -> Warning + Skip, nie Abbruch."""
        registry = PluginRegistry(injected=[_FailingPlugin()])
        monkeypatch.setattr(plugins_mod, "_default_registry", registry)
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent, "logger", rec)

        _agent, result = _run_agent(tmp_path, ["failing_step"])

        events = rec.events_named("pipeline.plugin_failed")
        assert len(events) == 1
        assert events[0][1]["plugin"] == "failing"
        assert events[0][1]["step"] == "failing_step"
        assert events[0][1]["ok"] is False
        assert result is not None

    def test_plugin_exception_skips_with_warning(
        self, tmp_path: Path, monkeypatch,
    ):
        """AC-PL-B2: Plugin wirft Exception -> Warning + Skip, nie Abbruch."""
        registry = PluginRegistry(injected=[_RaisingPlugin()])
        monkeypatch.setattr(plugins_mod, "_default_registry", registry)
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent, "logger", rec)

        _agent, result = _run_agent(tmp_path, ["raising_step"])

        events = rec.events_named("pipeline.plugin_failed")
        assert len(events) == 1
        assert events[0][1]["plugin"] == "raising"
        assert "boom" in events[0][1]["error"]
        assert result is not None

    def test_known_steps_untouched(
        self, tmp_path: Path, monkeypatch, dummy_registry,
    ):
        """AC-PL-B3: bekannte Steps -> kein Plugin-Event, keine
        Unhandled-Warning (Kern-Step-Kette unveraendert)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent, "logger", rec)

        _agent, result = _run_agent(
            tmp_path, ["register_frames", "stack_frames", "export"]
        )

        assert rec.events_named("pipeline.plugin_complete") == []
        assert rec.events_named("pipeline.plugin_failed") == []
        assert rec.events_named("pipeline.step_unhandled") == []
        assert result is not None


class TestPluginInMultiGroup:
    """PL-B: process_multi_group-Pfad (E1-Luecke geschlossen)."""

    def test_dummy_plugin_executed_in_multi_group(
        self, tmp_path: Path, monkeypatch, dummy_registry,
    ):
        """process_multi_group fuehrt Plugins fuer unbekannte Steps aus
        (Marker existiert), kein Abbruch, keine Unhandled-Warning."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = make_sample_context(
            tmp_path / "data", group_count=2, frames_per_group=3
        )
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = [PipelineStep(name="dummy_step")]
        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [
            f.path for f in lights.frames if f.path.exists()
        ]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = {
            "15s60": create_test_fits(
                tmp_path / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1
            ),
            "60s40": create_test_fits(
                tmp_path / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2
            ),
        }

        def fake_pcc(stack_path, *args, **kwargs):
            return (stack_path, "gaia_success")

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], status="ok", corr_hp=0.9,
            )
            mock_pcc.side_effect = fake_pcc
            result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=MultiGroupConfig(),
                merge_agent=None,
            )

        events = rec.events_named("pipeline.plugin_complete")
        assert len(events) == 1
        assert events[0][1]["step"] == "dummy_step"
        assert (tmp_path / "out" / "dummy_step_marker.txt").exists()
        assert rec.events_named("pipeline.step_unhandled") == []
        assert result is not None
