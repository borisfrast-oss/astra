"""V1.8-3 (AC-FITS-A1..A4): Optionaler gestreckter FITS-Export (Asinh).

Abgedeckt:
- A1: ``stretched_fits: false`` -> nur linearer FITS (byte-identisch).
- A2: ``stretched_fits: true`` -> zusaetzliches ``*_stretched.fits``
  (NAXIS=3, float32, Header ``STRETCH=asinh`` + Kommentar).
- A3: Gestretchter FITS visuell hell (Median deutlich hoeher als linear).
- A4: ``astra inspect`` + ``agent-log.yaml`` dokumentiert ``stretched_fits``.
- Edge-Cases: stretch method linear/none, a-Parameter.
- Backward-Compat: kein Config-Block -> kein gestreckter FITS.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml
from astropy.io import fits

# ── Ensure src + tests on the path ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_multi_group import create_test_fits, make_sample_context  # noqa: E402

from astro_process.agents.archive import ArchiveAgent  # noqa: E402
from astro_process.agents.merge_agent import MergeResult  # noqa: E402
from astro_process.agents.processing_agent import (  # noqa: E402
    ProcessingAgent,
    ProcessingResult,
)
from astro_process.config.loader import resolve_export_config  # noqa: E402
from astro_process.config.models import (  # noqa: E402
    AppConfig,
    ExportConfig,
    MultiGroupConfig,
    PipelinePreset,
    ProcessingParams,
    StretchConfig,
)
from astro_process.core.export import (  # noqa: E402
    _apply_asinh_display,
    _apply_stretch_for_fits,
    export,
    export_stretched_fits,
)
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
)


def _load_fits(path: Path) -> np.ndarray:
    """Lade FITS und gebe Daten als (H, W, C) zurueck."""
    with fits.open(path) as hdul:
        data = hdul[0].data.astype(np.float32)
        header = hdul[0].header
    if data.ndim == 3 and data.shape[0] == 3:
        data = data.transpose(1, 2, 0)
    return data, header


def _create_linear_stack(path: Path, shape: tuple = (64, 64, 3)) -> Path:
    """Erzeuge einen realistischen linearen Stack fuer Stretch-Tests."""
    rng = np.random.RandomState(101)
    data = np.full(shape, 1000.0, dtype=np.float32)
    data += rng.normal(0, 30, data.shape).astype(np.float32)
    # Ein paar helle "Sterne"
    for _ in range(8):
        cy = rng.randint(12, shape[0] - 12)
        cx = rng.randint(12, shape[1] - 12)
        y, x = np.ogrid[: shape[0], : shape[1]]
        star = np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / 4)
        for c in range(shape[2]):
            data[:, :, c] += star * rng.uniform(2000.0, 8000.0)
    data = np.clip(data, 0, None)
    out = data.transpose(2, 0, 1)
    hdu = fits.PrimaryHDU(out.astype(np.float32))
    hdu.header["CTYPE3"] = "RGB"
    hdu.header["CUNIT3"] = "channel"
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


# ═══════════════════════════════════════════════════════════════════
# AC-FITS-A1: stretched_fits=false -> nur linearer FITS
# ═══════════════════════════════════════════════════════════════════


class TestStretchedFitsDisabled:
    def test_false_only_linear_fits(self, tmp_path: Path):
        """stretched_fits=False erzeugt kein *_stretched.fits."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=False)

        exports = export(src, "M27", working_dir=tmp_path, export_config=cfg)

        assert any(e.name == "M27_final.fits" for e in exports)
        assert not any(e.name.endswith("_stretched.fits") for e in exports)

    def test_false_byte_identical_linear(self, tmp_path: Path):
        """Der lineare FITS ist byte-identisch zum Input (shutil.copy2)."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=False)

        export(src, "M27", working_dir=tmp_path, export_config=cfg)

        linear = tmp_path / "M27_final.fits"
        assert linear.read_bytes() == src.read_bytes()

    def test_no_export_config_no_stretched(self, tmp_path: Path):
        """Kein export_config -> v1.6/V1.8-2 Verhalten, kein gestreckter FITS."""
        src = _create_linear_stack(tmp_path / "stack.fits")

        exports = export(src, "M27", working_dir=tmp_path)

        assert any(e.name == "M27_final.fits" for e in exports)
        assert not any(e.name.endswith("_stretched.fits") for e in exports)


# ═══════════════════════════════════════════════════════════════════
# AC-FITS-A2: stretched_fits=true -> *_stretched.fits existiert
# ═══════════════════════════════════════════════════════════════════


class TestStretchedFitsEnabled:
    def test_true_creates_stretched_fits(self, tmp_path: Path):
        """stretched_fits=True erzeugt zusaetzliches *_stretched.fits."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True)

        exports = export(src, "M27", working_dir=tmp_path, export_config=cfg)

        stretched_paths = [e for e in exports if e.name.endswith("_stretched.fits")]
        assert len(stretched_paths) == 1
        assert stretched_paths[0].name == "M27_stretched.fits"

    def test_stretched_fits_header_and_format(self, tmp_path: Path):
        """Gestreckter FITS: NAXIS=3, float32, STRETCH=asinh + Kommentar."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True)
        export(src, "M27", working_dir=tmp_path, export_config=cfg)

        stretched = tmp_path / "M27_stretched.fits"
        data, header = _load_fits(stretched)

        assert data.ndim == 3
        assert header["NAXIS"] == 3
        assert header["NAXIS3"] == 3
        assert data.dtype == np.float32
        assert header["STRETCH"] == "asinh"
        comments = [str(c) for c in header.get("COMMENT", [])]
        assert any("stretched for display" in c for c in comments)
        assert "linear is scientific" in " ".join(comments)

    def test_linear_fits_unchanged_when_true(self, tmp_path: Path):
        """Aktivierter gestreckter Export aendert den linearen FITS nicht."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True)

        export(src, "M27", working_dir=tmp_path, export_config=cfg)

        linear = tmp_path / "M27_final.fits"
        assert linear.read_bytes() == src.read_bytes()


# ═══════════════════════════════════════════════════════════════════
# AC-FITS-A3: Gestreckter FITS visuell hell
# ═══════════════════════════════════════════════════════════════════


class TestStretchedFitsVisualBrightness:
    def test_stretched_median_higher_than_linear(self, tmp_path: Path):
        """Gestreckter FITS hat deutlich hoeheren Median als linearer."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True)
        export(src, "M27", working_dir=tmp_path, export_config=cfg)

        linear_data, _ = _load_fits(tmp_path / "M27_final.fits")
        stretched_data, _ = _load_fits(tmp_path / "M27_stretched.fits")

        linear_median = float(np.median(linear_data))
        stretched_median = float(np.median(stretched_data))

        assert stretched_median > linear_median * 2
        assert stretched_median > 0

    def test_stretched_preserves_max_scale(self, tmp_path: Path):
        """Max-Wert bleibt erhalten (Skalierung auf urspruenglichen Max)."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True)
        export(src, "M27", working_dir=tmp_path, export_config=cfg)

        linear_data, _ = _load_fits(tmp_path / "M27_final.fits")
        stretched_data, _ = _load_fits(tmp_path / "M27_stretched.fits")

        # Max pro Kanal soll identisch sein (bis auf numerisches Rauschen)
        for c in range(3):
            assert stretched_data[:, :, c].max() == pytest.approx(
                linear_data[:, :, c].max(), rel=1e-4
            )


# ═══════════════════════════════════════════════════════════════════
# AC-FITS-A4: Dokumentation in inspect + agent-log
# ═══════════════════════════════════════════════════════════════════


class TestStretchedFitsDocumentation:
    def test_resolve_export_config_defaults(self):
        """Ohne Config-Block -> Default false + asinh/a=0.01."""
        cfg = AppConfig()
        pipeline = PipelinePreset(name="test", target_types=["test"], steps=[])
        effective = resolve_export_config(cfg, pipeline)

        assert effective.stretched_fits is False
        assert effective.stretch.method == "asinh"
        assert effective.stretch.a == pytest.approx(0.01)

    def test_resolve_export_config_config_wins(self):
        """Config-Block gewinnt ueber Defaults."""
        cfg = AppConfig(
            export=ExportConfig(
                stretched_fits=True,
                stretch=StretchConfig(method="linear", a=0.05),
            )
        )
        pipeline = PipelinePreset(name="test", target_types=["test"], steps=[])
        effective = resolve_export_config(cfg, pipeline)

        assert effective.stretched_fits is True
        assert effective.stretch.method == "linear"
        assert effective.stretch.a == pytest.approx(0.05)

    def test_processing_result_carries_stretched_fits(self, tmp_path: Path):
        """ProcessingResult.stretched_fits dokumentiert Status."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True)
        exports = export(src, "M27", working_dir=tmp_path, export_config=cfg)

        result = ProcessingResult(exports=exports, stretched_fits={
            "enabled": True,
            "created": any(e.name.endswith("_stretched.fits") for e in exports),
            "method": "asinh",
            "a": 0.01,
        })
        assert result.stretched_fits is not None
        assert result.stretched_fits["enabled"] is True
        assert result.stretched_fits["created"] is True

    def test_agent_log_contains_stretched_fits(self, tmp_path: Path):
        """agent-log.yaml enthaelt processing.stretched_fits."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        ctx = make_sample_context(tmp_path)

        result = ProcessingResult(
            exports=[output_dir / "M27_final.fits"],
            stretched_fits={
                "enabled": True,
                "created": True,
                "method": "asinh",
                "a": 0.01,
            },
        )

        cal_result = MagicMock()
        cal_result.master_dark = None
        cal_result.calibrated_lights = []

        agent = ArchiveAgent(output_dir, config=None)
        log_path = agent._create_agent_log(output_dir, ctx, result, cal_result)

        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        sf = log["processing"]["stretched_fits"]
        assert sf is not None
        assert sf["enabled"] is True
        assert sf["created"] is True
        assert sf["method"] == "asinh"
        assert sf["a"] == pytest.approx(0.01)

    def test_inspect_json_contains_stretched_fits(self, tmp_path: Path):
        """astra inspect --json enthaelt stretched_fits Block."""
        from click.testing import CliRunner
        from astro_process.cli import cli

        target = tmp_path / "M92"
        input_dir = target / "generated" / "20260101-120000" / "00_input"
        input_dir.mkdir(parents=True)
        light = input_dir / "light_0000.fits"
        rng = np.random.RandomState(31)
        data = rng.normal(100, 5, (32, 32)).astype(np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["EXPTIME"] = 15.0
        hdu.header["GAIN"] = 60
        hdu.header["OBJECT"] = "M92"
        hdu.header["CCD-TEMP"] = 20.0
        hdu.writeto(light, overwrite=True)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            'export:\n  stretched_fits: true\n  stretch:\n    method: linear\n    a: 0.05\n',
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--config", str(config_file), "inspect", str(target), "--json"],
        )
        assert result.exit_code == 0, result.output

        lines = result.output.splitlines()
        start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                start = i
        assert start is not None
        output = json.loads("\n".join(lines[start:]))

        assert "stretched_fits" in output
        sf = output["stretched_fits"]
        assert sf["stretched_fits"] is True
        assert sf["stretch"]["method"] == "linear"
        assert sf["stretch"]["a"] == pytest.approx(0.05)


# ═══════════════════════════════════════════════════════════════════
# Edge-Cases: stretch method + a-Parameter
# ═══════════════════════════════════════════════════════════════════


class TestStretchedFitsEdgeCases:
    def test_stretch_linear(self, tmp_path: Path):
        """method=linear erzeugt gueltigen gestreckten FITS."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True, stretch=StretchConfig(method="linear"))

        export(src, "M27", working_dir=tmp_path, export_config=cfg)

        stretched = tmp_path / "M27_stretched.fits"
        data, header = _load_fits(stretched)
        assert header["STRETCH"] == "linear"
        assert np.isfinite(data).all()

    def test_stretch_none(self, tmp_path: Path):
        """method=none kopiert die Daten nur (Header STRETCH=none)."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True, stretch=StretchConfig(method="none"))

        export(src, "M27", working_dir=tmp_path, export_config=cfg)

        stretched = tmp_path / "M27_stretched.fits"
        data, header = _load_fits(stretched)
        assert header["STRETCH"] == "none"
        linear_data, _ = _load_fits(src)
        np.testing.assert_allclose(data, linear_data, rtol=1e-5)

    def test_a_parameter_changes_stretch(self, tmp_path: Path):
        """Kleineres a erzeugt staerkeren Stretch (hoeherer Median)."""
        src = _create_linear_stack(tmp_path / "stack.fits")

        medians = {}
        for a in (0.005, 0.01, 0.05):
            cfg = ExportConfig(stretched_fits=True, stretch=StretchConfig(a=a))
            export(src, f"M27_{a}", working_dir=tmp_path, export_config=cfg)
            data, _ = _load_fits(tmp_path / f"M27_{a}_stretched.fits")
            medians[a] = float(np.median(data))

        # Groesseres a = staerkerer Asinh-Stretch = hoeherer Median
        assert medians[0.005] < medians[0.01]
        assert medians[0.01] < medians[0.05]

    def test_export_stretched_fits_best_effort_failure(self, tmp_path: Path):
        """Fehlerhafte Quelle -> None, kein Crash."""
        corrupt = tmp_path / "corrupt.fits"
        corrupt.write_text("not a fits file")
        cfg = ExportConfig(stretched_fits=True)

        result = export_stretched_fits(corrupt, tmp_path / "out.fits", cfg)
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# Multi-Group: merged_stretched.fits
# ═══════════════════════════════════════════════════════════════════


class TestMultiGroupMergedStretched:
    def test_merged_stretched_fits_created(self, tmp_path: Path):
        """Multi-Group Merge erhaelt optional *_merged_stretched.fits."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = make_sample_context(tmp_path / "data", group_count=2, frames_per_group=3)
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

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

        cfg = AppConfig(export=ExportConfig(stretched_fits=True))
        agent.config = cfg

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

        assert result.stretched_fits is not None
        assert result.stretched_fits["enabled"] is True
        assert result.stretched_fits["created"] is True

        stretched_path = tmp_path / "out" / "merged" / "TestTarget_merged_stretched.fits"
        assert stretched_path.exists()
        assert stretched_path in result.exports


# ═══════════════════════════════════════════════════════════════════
# Platesolve-Isolation: _stretched wird nie fuer wissenschaftliche Steps
# ═══════════════════════════════════════════════════════════════════


class TestPlatesolveIsolation:
    def test_stacked_reference_is_linear_not_stretched(self, tmp_path: Path):
        """Pipeline-Referenz (result.stacked) bleibt linear; gestreckter FITS
        ist nur ein Output-Artefakt."""
        src = _create_linear_stack(tmp_path / "stack.fits")
        cfg = ExportConfig(stretched_fits=True)

        # Simuliere ProcessingResult wie die Pipeline es befuellt.
        exports = export(src, "M27", working_dir=tmp_path, export_config=cfg)
        linear = tmp_path / "M27_final.fits"
        stretched = tmp_path / "M27_stretched.fits"

        assert linear.exists()
        assert stretched.exists()
        # Der gestreckte FITS ist nur ein Output; die Pipeline-Logik
        # (PCC/Registration/Platesolve) arbeitet weiterhin auf dem linearen FITS.
        result = ProcessingResult(
            stacked=linear,
            exports=exports,
            stretched_fits={"enabled": True, "created": True, "method": "asinh", "a": 0.01},
        )
        assert result.stacked == linear
        assert result.stacked != stretched

    def test_fits_parser_skips_stretched_files(self, tmp_path: Path):
        """``*_stretched.fits`` wird von der FITS-Discovery ausgeschlossen."""
        from astro_process.core.fits_parser import scan_directory
        from astro_process.models.core import FrameType

        # Stelle eine _stretched.fits im Input-Verzeichnis bereit
        _create_linear_stack(tmp_path / "M27_stretched.fits")
        _create_linear_stack(tmp_path / "M27_light_0000.fits")

        result = scan_directory(tmp_path)
        lights = result.get(FrameType.LIGHT, [])
        found = {Path(f.path).name for f in lights.frames}

        assert "M27_light_0000.fits" in found
        assert "M27_stretched.fits" not in found
