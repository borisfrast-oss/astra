"""F-SE-1.2 (v12-structure-enhancement.md): Structure Enhancement plugin.

Abgedeckt:
- SE-A / AC-SE-A1..A6: Algorithmus (reine Funktion) + Gate-Eigenschaften
  (USM + Intensitaets-Gate, per Kanal, deterministisch).
- SE-B / AC-SE-B1..B4: Plugin-Form + Vertrag (Input/Output, Fehler
  ok=False) + `PluginContext.step_params` (additiv).
- SE-C / AC-SE-C1..C2: Step-Params radius/amount (Defaults + Clamp/Warning).
- SE-D / AC-SE-D1..D3: Verdrahtung in run()/process_multi_group()
  (Export = Enhanced; Multi-Group: genau 1x auf dem finalen Merge).
- SE-E / AC-SE-E1..E3: Erwartungswerte am M27-Analog + Determinismus +
  Regression (bekannte Steps erzeugen keine neuen Events).

Toleranzen (fixiert und dokumentiert, AC-SE-A4):
- Kontrastanstieg (RMS des High-Pass in der Nebel-Maske, Gate-Band mit
  Gate > 0.3) am M27-Analog (Seed 42, 256x256): gemessen ~12.65 %,
  Assertion >= +10 % (AC-SE-A4).
- Apertur-Fluss der Sterne (5x5 um Kern-Pixel >= ceil): gemessen ~-0.03 %,
  Assertion |delta| <= 5 % (AC-SE-A3).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from astropy.io import fits

# ── Ensure src + tests on the path ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthetic  # noqa: E402
from test_multi_group import create_test_fits, make_sample_context  # noqa: E402

import astro_process.agents.processing_agent as processing_agent_mod  # noqa: E402
import astro_process.core.plugins as plugins_mod  # noqa: E402
from astro_process.agents.merge_agent import MergeResult  # noqa: E402
from astro_process.agents.processing_agent import ProcessingAgent  # noqa: E402
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
)
from astro_process.config.models import (  # noqa: E402
    MultiGroupConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
)
from astro_process.core.plugins import (  # noqa: E402
    PluginContext,
    PluginRegistry,
)
from astro_process.plugins.structure_enhancement import (  # noqa: E402
    CEIL_QUANTILE,
    DEFAULT_AMOUNT,
    DEFAULT_RADIUS,
    K_FLOOR,
    StructureEnhancementPlugin,
    apply_structure_enhancement,
    apply_structure_enhancement_with_report,
)


class _LogRecorder:
    """Minimaler structlog-Recorder (Muster test_plugins_processing)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def _record(self, name: str, **kwargs: object) -> None:
        self.records.append((name, kwargs))

    def info(self, name, **kwargs):
        self._record(name, **kwargs)

    def warning(self, name, **kwargs):
        self._record(name, **kwargs)

    def error(self, name, **kwargs):
        self._record(name, **kwargs)

    def debug(self, name, **kwargs):
        self._record(name, **kwargs)

    def events_named(self, name: str) -> list[tuple[str, dict]]:
        return [(n, k) for n, k in self.records if n == name]


def _gate_stats(channel: np.ndarray) -> tuple[float, float, float, float]:
    """Spiegelt die Gate-Statistik des Algorithmus (SE-A Schritte 1-3)."""
    m = float(np.median(channel))
    mad = float(np.median(np.abs(channel - m)))
    return m, mad, m + K_FLOOR * mad, float(np.quantile(channel, CEIL_QUANTILE))


def _save_fits(data: np.ndarray, path: Path) -> None:
    """Schreibt (H,W) bzw. (H,W,C) als FITS (Konvention wie _save_frame)."""
    out = np.asarray(data, dtype=np.float32)
    if out.ndim == 3:
        out = out.transpose(2, 0, 1)  # (H, W, C) -> (C, H, W)
    hdu = fits.PrimaryHDU(out)
    if out.ndim == 3:
        hdu.header["CTYPE3"] = "RGB"
        hdu.header["CUNIT3"] = "channel"
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)


def _load_fits(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float32)
    if data.ndim == 3:
        data = data.transpose(1, 2, 0)  # (C, H, W) -> (H, W, C)
    return data


def _m27_frame(tmp_path: Path) -> np.ndarray:
    """M27-Analog (QF-C, deterministisch): erster Light-Frame als
    Stack-Analog (das echte stacked.fits ist durch Registrierung mit
    mode='nearest' sogar sauberer)."""
    scene = synthetic.generate_m27_analog(tmp_path / "m27", seed=42)
    key = scene.dataset.group_keys[0]
    with fits.open(scene.dataset.group_map[key][0]) as hdul:
        return np.asarray(hdul[0].data, dtype=np.float32)


def _run_agent(
    tmp_path: Path,
    steps: list[str],
    stacked: np.ndarray | None = None,
    step_params: dict | None = None,
):
    """Minimaler run()-Aufruf; legt optional stacked.fits an."""
    agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
    if stacked is not None:
        _save_fits(stacked, tmp_path / "out" / "04_stacked" / "stacked.fits")
    context = SimpleNamespace(
        target=SimpleNamespace(name="TestTarget", ra=0.0, dec=0.0),
        equipment=SimpleNamespace(focal_length_mm=0.0, pixel_size_um=0.0),
    )
    pipeline = PipelinePreset(
        name="test",
        target_types=["nebula"],
        steps=[
            PipelineStep(
                name=s,
                params=(step_params or {}) if s == "structure_enhancement" else {},
            )
            for s in steps
        ],
        processing_params=ProcessingParams(),
    )
    result = agent.run(
        context,
        SimpleNamespace(calibrated_lights=[]),
        SimpleNamespace(debayered_frames=[]),
        pipeline,
    )
    return agent, result


# ═══════════════════════════════════════════════════════════════════
# SE-A: reine Funktion (Algorithmus)
# ═══════════════════════════════════════════════════════════════════


class TestApplyStructureEnhancement:
    """AC-SE-A1..A6 + AC-SE-E1: USM + Intensitaets-Gate am M27-Analog."""

    def test_deterministic_byte_identical(self, tmp_path: Path):
        """AC-SE-E1: gleiche Eingabe -> identisches Ergebnis (kein RNG)."""
        img = _m27_frame(tmp_path)
        out1 = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        out2 = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        assert out1.dtype == np.float32
        assert out1.tobytes() == out2.tobytes()

    def test_background_exactly_unchanged(self, tmp_path: Path):
        """AC-SE-A2: Pixel unterhalb floor_c sind exakt identisch (gate=0)."""
        img = _m27_frame(tmp_path)
        out = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        _, _, floor_v, _ = _gate_stats(img)
        below = img <= floor_v
        assert below.any()
        assert np.array_equal(out[below], img[below])

    def test_star_cores_exactly_unchanged(self, tmp_path: Path):
        """AC-SE-A3: Pixel oberhalb ceil_c sind exakt identisch (gate=0)."""
        img = _m27_frame(tmp_path)
        out = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        _, _, _, ceil_v = _gate_stats(img)
        above = img >= ceil_v
        assert above.any()
        assert np.array_equal(out[above], img[above])

    def test_star_aperture_flux_stable(self, tmp_path: Path):
        """AC-SE-A3: Apertur-Fluss (5x5 um Kern-Pixel) aendert sich <= 5%."""
        from scipy.ndimage import center_of_mass, find_objects, label

        img = _m27_frame(tmp_path)
        out = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        _, _, floor_v, ceil_v = _gate_stats(img)
        star_mask = img >= ceil_v
        lab, n = label(star_mask)
        assert n >= 1
        total_in = 0.0
        total_out = 0.0
        for sl in find_objects(lab):
            cy, cx = center_of_mass(star_mask[sl])
            cy_i = int(round(sl[0].start + cy))
            cx_i = int(round(sl[1].start + cx))
            yy, xx = np.ogrid[: img.shape[0], : img.shape[1]]
            box = (np.abs(yy - cy_i) <= 2) & (np.abs(xx - cx_i) <= 2)
            total_in += float(np.sum(np.clip(img[box] - floor_v, 0, None)))
            total_out += float(np.sum(np.clip(out[box] - floor_v, 0, None)))
        assert total_in > 0
        delta_pct = (total_out / total_in - 1.0) * 100.0
        assert abs(delta_pct) <= 5.0

    def test_local_contrast_rises_at_defaults(self, tmp_path: Path):
        """AC-SE-A4: Mikro-Kontrast (RMS High-Pass, Nebel-Maske im Gate-Band
        mit Gate > 0.3) steigt >= +10% bei Defaults (gemessen ~12.65%)."""
        from scipy.ndimage import gaussian_filter

        img = _m27_frame(tmp_path)
        out = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        _, _, floor_v, ceil_v = _gate_stats(img)
        blurred = gaussian_filter(img, sigma=DEFAULT_RADIUS)
        hp_in = img - blurred
        hp_out = out - blurred
        gate = (img - floor_v) / (ceil_v - floor_v)
        mask = (img > floor_v) & (img < ceil_v) & (gate > 0.3)
        assert mask.sum() >= 100
        rms_in = float(np.sqrt(np.mean(hp_in[mask] ** 2)))
        rms_out = float(np.sqrt(np.mean(hp_out[mask] ** 2)))
        assert rms_in > 0
        rise_pct = (rms_out / rms_in - 1.0) * 100.0
        assert rise_pct >= 10.0

    def test_defaults_conservative(self, tmp_path: Path):
        """SE-E: Kontrastanstieg im Gate-Band <= +40% (gemessen ~10.06%);
        Defaults sind konservativ (kein aggressives Enhancement)."""
        from scipy.ndimage import gaussian_filter

        img = _m27_frame(tmp_path)
        out = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        _, _, floor_v, ceil_v = _gate_stats(img)
        blurred = gaussian_filter(img, sigma=DEFAULT_RADIUS)
        hp_in = img - blurred
        hp_out = out - blurred
        mask = (img > floor_v) & (img < ceil_v)
        assert mask.any()
        rms_in = float(np.sqrt(np.mean(hp_in[mask] ** 2)))
        rms_out = float(np.sqrt(np.mean(hp_out[mask] ** 2)))
        rise_pct = (rms_out / rms_in - 1.0) * 100.0
        assert rise_pct <= 40.0

    def test_global_statistics_stable(self, tmp_path: Path):
        """AC-SE-A5: Median exakt erhalten; Delta P99.9 < 1%; Delta RMS < 5%."""
        img = _m27_frame(tmp_path)
        out = apply_structure_enhancement(img, DEFAULT_RADIUS, DEFAULT_AMOUNT)
        assert float(np.median(out)) == float(np.median(img))
        p_in = float(np.quantile(img, 0.999))
        p_out = float(np.quantile(out, 0.999))
        assert abs(p_out / p_in - 1.0) * 100.0 < 1.0
        rms_in = float(np.sqrt(np.mean(img**2)))
        rms_out = float(np.sqrt(np.mean(out**2)))
        assert abs(rms_out / rms_in - 1.0) * 100.0 < 5.0

    def test_degenerate_image_channel_unchanged(self):
        """AC-SE-A6: degeneriertes Bild (ceil <= floor) -> unveraendert +
        Report (degenerate), nie Abbruch."""
        img = np.full((64, 64), 100.0, dtype=np.float32)
        out, degenerate = apply_structure_enhancement_with_report(img)
        assert degenerate == [0]
        assert np.array_equal(out, img)

    def test_rgb_processed_per_channel(self):
        """OQ-SE-2 (Option A): 3D-Bild wird pro Kanal verarbeitet; 2D-Ergebnis
        entspricht dem jeweiligen Kanal des 3D-Ergebnisses."""
        ch = np.full((64, 64), 100.0, dtype=np.float32)
        ch[20:40, 30:50] += 6.0  # kleine Struktur im Gate-Band
        mono = apply_structure_enhancement(ch)
        rgb = np.stack([ch, ch, ch], axis=-1)
        out3 = apply_structure_enhancement(rgb)
        assert out3.shape == rgb.shape
        assert np.array_equal(out3[..., 0], mono)
        assert np.array_equal(out3[..., 1], mono)
        assert np.array_equal(out3[..., 2], mono)

    def test_raises_for_invalid_shape(self):
        """Nur (H,W) / (H,W,C) werden unterstuetzt (klarer Fehler, ok=False-
        Weg des Plugins faengt ihn ab — AC-SE-B3)."""
        with pytest.raises(ValueError, match="unsupported image shape"):
            apply_structure_enhancement(np.zeros((4, 4, 4, 4), dtype=np.float32))


# ═══════════════════════════════════════════════════════════════════
# SE-B/SE-C: Plugin-Form + Vertrag + Step-Params
# ═══════════════════════════════════════════════════════════════════


class TestStructureEnhancementPlugin:
    """AC-SE-B1..B4 + AC-SE-C1..C2: Plugin-Vertrag."""

    def test_name_version_handles(self):
        """AC-SE-B1: name/version; handles nur structure_enhancement."""
        plugin = StructureEnhancementPlugin()
        assert plugin.name == "structure_enhancement"
        assert plugin.version == "1.0.0"
        assert plugin.handles("structure_enhancement")
        assert not plugin.handles("stretch")
        assert not plugin.handles("stack_frames")

    def test_entry_point_registration(self, monkeypatch):
        """AC-SE-B1: Registry laedt das Plugin ueber die Entry-Point-Gruppe
        astra.plugins (simuliert, kein Reinstall noetig)."""
        registry = PluginRegistry()

        class _EP:
            name = "structure-enhancement"

            def load(self):
                return StructureEnhancementPlugin

        with patch(
            "astro_process.core.plugins.importlib.metadata.entry_points",
            return_value=[_EP()],
        ):
            found = registry.resolve_step("structure_enhancement")
        assert found is not None
        assert found.name == "structure_enhancement"

    def test_run_writes_enhanced_fits(self, tmp_path: Path):
        """AC-SE-B2: Input 04_stacked/stacked.fits -> Output
        04_stacked/enhanced.fits; artifact + log_fields."""
        img = _m27_frame(tmp_path)
        _save_fits(img, tmp_path / "04_stacked" / "stacked.fits")
        rec = _LogRecorder()
        context = PluginContext(
            working_dir=tmp_path,
            output_dir=tmp_path,
            logger=rec,
        )
        result = StructureEnhancementPlugin().run(context)
        assert result.ok is True
        assert result.step == "structure_enhancement"
        assert result.artifact is not None
        assert result.artifact.name == "enhanced.fits"
        assert result.artifact.exists()
        assert result.log_fields["radius"] == DEFAULT_RADIUS
        assert result.log_fields["amount"] == DEFAULT_AMOUNT
        assert rec.events_named("structure_enhancement.complete")

    def test_run_missing_stack_fails_gracefully(self, tmp_path: Path):
        """AC-SE-B3: fehlender Input -> ok=False (stack_not_found), nie
        Abbruch/Exception."""
        context = PluginContext(working_dir=tmp_path, output_dir=tmp_path)
        result = StructureEnhancementPlugin().run(context)
        assert result.ok is False
        assert result.log_fields["reason"] == "stack_not_found"

    def test_run_defaults_without_params(self, tmp_path: Path):
        """AC-SE-C1: Step ohne params -> Defaults (3.0 / 0.2) im Log."""
        img = _m27_frame(tmp_path)
        _save_fits(img, tmp_path / "04_stacked" / "stacked.fits")
        context = PluginContext(working_dir=tmp_path, output_dir=tmp_path)
        result = StructureEnhancementPlugin().run(context)
        assert result.ok is True
        assert result.log_fields == {"radius": 3.0, "amount": 0.2}

    def test_run_step_params_applied(self, tmp_path: Path):
        """AC-SE-C1: params {radius, amount} wirken (im Log + Bild aendert
        sich gegenueber den Defaults)."""
        img = _m27_frame(tmp_path)
        _save_fits(img, tmp_path / "04_stacked" / "stacked.fits")

        def _run(params: dict) -> np.ndarray:
            out = tmp_path / f"04_stacked_{params['radius']}_{params['amount']}"
            out.mkdir(parents=True, exist_ok=True)
            _save_fits(img, out / "04_stacked" / "stacked.fits")
            context = PluginContext(working_dir=out, output_dir=out, step_params=params)
            result = StructureEnhancementPlugin().run(context)
            assert result.ok is True
            assert result.log_fields["radius"] == params["radius"]
            assert result.log_fields["amount"] == params["amount"]
            return _load_fits(out / "04_stacked" / "enhanced.fits")

        out_custom = _run({"radius": 1.0, "amount": 0.4})
        out_default = _run({"radius": 3.0, "amount": 0.2})
        assert not np.array_equal(out_custom, out_default)

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"radius": 0.1, "amount": 2.0}, {"radius": 0.5, "amount": 1.0}),
            ({"radius": 100.0, "amount": -1.0}, {"radius": 50.0, "amount": 0.0}),
            ({"radius": "abc"}, {"radius": 3.0, "amount": 0.2}),
        ],
    )
    def test_invalid_params_clamped_with_warning(
        self, tmp_path: Path, params: dict, expected: dict
    ):
        """AC-SE-C2: ungueltige Werte -> Warning + Clamp, nie Abbruch."""
        img = _m27_frame(tmp_path)
        _save_fits(img, tmp_path / "04_stacked" / "stacked.fits")
        rec = _LogRecorder()
        context = PluginContext(
            working_dir=tmp_path,
            output_dir=tmp_path,
            step_params=params,
            logger=rec,
        )
        result = StructureEnhancementPlugin().run(context)
        assert result.ok is True
        assert result.log_fields["radius"] == expected["radius"]
        assert result.log_fields["amount"] == expected["amount"]
        clamped = rec.events_named("structure_enhancement.params_clamped")
        assert len(clamped) >= 1

    def test_degenerate_input_logs_info_and_succeeds(self, tmp_path: Path):
        """AC-SE-A6 (Plugin-Ebene): konstantes Bild -> Info-Log
        channel_unchanged, ok=True, Artefakt = unveraendert."""
        img = np.full((64, 64, 3), 100.0, dtype=np.float32)
        _save_fits(img, tmp_path / "04_stacked" / "stacked.fits")
        rec = _LogRecorder()
        context = PluginContext(working_dir=tmp_path, output_dir=tmp_path, logger=rec)
        result = StructureEnhancementPlugin().run(context)
        assert result.ok is True
        unchanged = rec.events_named("structure_enhancement.channel_unchanged")
        assert len(unchanged) == 3  # pro Kanal ein Info-Log
        out = _load_fits(tmp_path / "04_stacked" / "enhanced.fits")
        assert np.array_equal(out, img)


class TestPluginContextStepParams:
    """AC-SE-B4: PluginContext.step_params additiv, Default {}."""

    def test_default_empty(self):
        ctx = PluginContext(working_dir=Path(), output_dir=Path())
        assert ctx.step_params == {}

    def test_explicit_params(self):
        ctx = PluginContext(
            working_dir=Path(),
            output_dir=Path(),
            step_params={"radius": 2.0},
        )
        assert ctx.step_params == {"radius": 2.0}


# ═══════════════════════════════════════════════════════════════════
# SE-D: Verdrahtung in run()/process_multi_group()
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def se_registry(monkeypatch: pytest.MonkeyPatch) -> PluginRegistry:
    """SE-Plugin in die Default-Registry injizieren (Test-Hook, AC-PL-A3)."""
    registry = PluginRegistry(injected=[StructureEnhancementPlugin()])
    monkeypatch.setattr(plugins_mod, "_default_registry", registry)
    return registry


NEBULA_STANDARD_STEPS = [
    "create_master_dark",
    "calibrate_lights",
    "register_frames",
    "stack_frames",
    "gradient_removal",
    "background_extraction",
    "structure_enhancement",
    "stretch",
    "export",
]


class TestIntegrationRun:
    """AC-SE-D1/D2 + AC-SE-E3: run()-Pfad."""

    def test_nebula_standard_no_unhandled_and_export_enhanced(
        self,
        tmp_path: Path,
        monkeypatch,
        se_registry,
    ):
        """AC-SE-D1/D2: nebula_standard-Step-Liste + SE-Plugin -> keine
        `pipeline.step_unhandled`-Warning; plugin_complete vorhanden;
        Export-Artefakt enthaelt die Enhancement (== enhanced.fits)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)
        img = _m27_frame(tmp_path)

        _agent, result = _run_agent(tmp_path, NEBULA_STANDARD_STEPS, stacked=img)

        assert rec.events_named("pipeline.step_unhandled") == []
        complete = rec.events_named("pipeline.plugin_complete")
        assert len(complete) == 1
        assert complete[0][1]["plugin"] == "structure_enhancement"
        assert complete[0][1]["step"] == "structure_enhancement"
        assert result.stacked is not None
        assert result.stacked.name == "enhanced.fits"

        # Export enthaelt die Enhancement: geladener Export == enhanced.fits
        enhanced = _load_fits(tmp_path / "out" / "04_stacked" / "enhanced.fits")
        fits_out = tmp_path / "out" / "TestTarget_final.fits"
        assert fits_out.exists()
        assert np.array_equal(_load_fits(fits_out), enhanced)

    def test_missing_stack_skips_with_warning(
        self,
        tmp_path: Path,
        monkeypatch,
        se_registry,
    ):
        """AC-SE-B3: fehlender Stack -> plugin_failed (stack_not_found),
        Ergebnis gueltig, keine step_unhandled-Warning."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        _agent, result = _run_agent(tmp_path, ["structure_enhancement", "export"])

        failed = rec.events_named("pipeline.plugin_failed")
        assert len(failed) == 1
        assert failed[0][1]["plugin"] == "structure_enhancement"
        assert failed[0][1]["log_fields"]["reason"] == "stack_not_found"
        assert rec.events_named("pipeline.step_unhandled") == []
        assert result is not None

    def test_known_steps_no_se_events(
        self,
        tmp_path: Path,
        monkeypatch,
        se_registry,
    ):
        """AC-SE-E3: bekannte Steps (galaxy_standard-artig) erzeugen keine
        neuen Plugin-Events/Warnings durch das SE-Plugin (AC-PL-B3)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        _agent, result = _run_agent(
            tmp_path,
            ["register_frames", "stack_frames", "background_extraction", "export"],
        )

        assert rec.events_named("pipeline.plugin_complete") == []
        assert rec.events_named("pipeline.plugin_failed") == []
        assert rec.events_named("pipeline.step_unhandled") == []
        assert result is not None


class TestIntegrationMultiGroup:
    """AC-SE-D3: process_multi_group laeuft genau 1x auf dem finalen Merge."""

    def test_plugin_runs_once_on_final_merge(
        self,
        tmp_path: Path,
        monkeypatch,
        se_registry,
    ):
        """plugin_complete genau 1x; Merge wird als 04_stacked/stacked.fits
        materialisiert; finale Artefakte (exports) enthalten enhanced.fits."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = make_sample_context(tmp_path / "data", group_count=2, frames_per_group=3)
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = [PipelineStep(name="structure_enhancement")]
        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
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
        merged_fits = create_test_fits(tmp_path / "merged.fits", exptime=60.0, gain=40, rng_seed=3)
        merge_agent = MagicMock()
        merge_agent.run.return_value = MergeResult(merged_path=merged_fits, merge_report={})

        def fake_pcc(stack_path, *args, **kwargs):
            return (stack_path, "gaia_success")

        with (
            patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg,
            patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack,
            patch.object(agent, "_register_to_reference_stack") as mock_cross,
            patch.object(agent, "_apply_pcc_per_group") as mock_pcc,
        ):
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"],
                shift_y=0.0,
                shift_x=0.0,
                correlation=0.9,
                corr_hp=0.9,
                status="ok",
            )
            mock_pcc.side_effect = fake_pcc
            result = agent.process_multi_group(
                context,
                cal_result,
                deb_result,
                pipeline,
                multi_group_config=MultiGroupConfig(),
                merge_agent=merge_agent,
            )

        complete = rec.events_named("pipeline.plugin_complete")
        assert len(complete) == 1
        assert complete[0][1]["step"] == "structure_enhancement"
        assert rec.events_named("pipeline.step_unhandled") == []

        # Merge wurde fuer das Plugin materialisiert; enhanced.fits existiert
        materialized = tmp_path / "out" / "04_stacked" / "stacked.fits"
        enhanced = tmp_path / "out" / "04_stacked" / "enhanced.fits"
        assert materialized.exists()
        assert enhanced.exists()

        # Finale Artefakte sind enhanced (Adoption des Plugin-Artefakts)
        assert result.stacked is not None
        assert result.stacked.name == "enhanced.fits"
        assert any(str(e).endswith("enhanced.fits") for e in result.exports)
        assert len(result.exports) >= 1
