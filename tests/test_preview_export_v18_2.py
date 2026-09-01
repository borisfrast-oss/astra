"""V1.8-2 (AC-PREV-A1..A5): Preview/Export-Pipeline (SCNR, Saturation, Background Neutralization).

Abgedeckt:
- A1: SCNR entfernt Gruen-Stich (reused core/pcc.py::apply_scnr).
- A2: Saturation aendert Werte, kein NaN/Inf, Pixel <= max.
- A3: Background-Neutralization gleicht Hintergrund ab (Median ~0).
- A4: Defaults ohne Config-Block = Asinh-only (byte-identisch zu v1.6).
- A5: export.preview in inspect-Output + agent-log.yaml dokumentiert.
- Edge-Cases: einzelne Steps deaktiviert, alle deaktiviert, stretch linear/none.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml
from astropy.io import fits
from PIL import Image

# ── Ensure src + tests on the path ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_multi_group import create_test_fits, make_sample_context  # noqa: E402

from astro_process.agents.archive import ArchiveAgent  # noqa: E402
from astro_process.agents.processing_agent import ProcessingResult  # noqa: E402
from astro_process.config.loader import resolve_preview_export_config  # noqa: E402
from astro_process.config.models import (  # noqa: E402
    AppConfig,
    ExportConfig,
    PipelinePreset,
    PreviewExportConfig,
    ProcessingParams,
)
from astro_process.core.export import export  # noqa: E402
from astro_process.core.preview import (  # noqa: E402
    _apply_background_neutralization,
    _apply_saturation,
    _apply_stretch,
    create_preview_jpg,
)


def _load_jpg_array(path: Path) -> np.ndarray:
    """Load JPG as HxWx3 uint8 numpy array."""
    return np.array(Image.open(path))


def _create_green_cast_fits(path: Path) -> Path:
    """Synthetic FITS mit deutlichem Gruen-Stich (G > R, G > B)."""
    rng = np.random.RandomState(7)
    data = np.full((64, 64, 3), 50.0, dtype=np.float32)
    # Hintergrund + Rauschen
    data += rng.normal(0, 2, data.shape).astype(np.float32)
    # Gruen-Stich ueberall
    data[:, :, 1] += 30.0
    # Ein paar "Sterne"
    for _ in range(5):
        cy = rng.randint(10, 54)
        cx = rng.randint(10, 54)
        y, x = np.ogrid[:64, :64]
        star = np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / 3)
        for c in range(3):
            data[:, :, c] += star * rng.uniform(1.0, 3.0)
    data = np.clip(data, 0, None)
    out = data.transpose(2, 0, 1)
    hdu = fits.PrimaryHDU(out.astype(np.float32))
    hdu.writeto(path, overwrite=True)
    return path


# ═══════════════════════════════════════════════════════════════════
# AC-PREV-A1: SCNR entfernt Gruen-Stich
# ═══════════════════════════════════════════════════════════════════


class TestPreviewScnr:
    def test_scnr_reduces_green_cast(self, tmp_path: Path):
        """scnr: true reduziert den Gruen-Anteil im Preview-JPG."""
        src = _create_green_cast_fits(tmp_path / "green.fits")
        off_jpg = tmp_path / "green_scnr_off.jpg"
        on_jpg = tmp_path / "green_scnr_on.jpg"

        off_cfg = PreviewExportConfig(scnr=False)
        on_cfg = PreviewExportConfig(scnr=True)

        assert create_preview_jpg(src, off_jpg, preview_config=off_cfg) is not None
        assert create_preview_jpg(src, on_jpg, preview_config=on_cfg) is not None

        off_arr = _load_jpg_array(off_jpg).astype(np.float32)
        on_arr = _load_jpg_array(on_jpg).astype(np.float32)

        # Durchschnittlicher Gruen-Anteil soll mit SCNR niedriger sein
        assert on_arr[:, :, 1].mean() < off_arr[:, :, 1].mean()
        # Bild wird nicht komplett schwarz/weiss
        assert on_arr.std() > 0


# ═══════════════════════════════════════════════════════════════════
# AC-PREV-A2: Saturation erhoeht Farbsaettigung
# ═══════════════════════════════════════════════════════════════════


class TestPreviewSaturation:
    def test_saturation_changes_values_no_nan_inf(self, tmp_path: Path):
        """saturation: 1.2 veraendert Werte, ohne NaN/Inf, Pixel <= 255."""
        src = create_test_fits(tmp_path / "color.fits", shape=(64, 64, 3), value=10.0, rng_seed=3)
        neutral_jpg = tmp_path / "sat_neutral.jpg"
        boost_jpg = tmp_path / "sat_boost.jpg"

        neutral_cfg = PreviewExportConfig(saturation=1.0)
        boost_cfg = PreviewExportConfig(saturation=1.2)

        assert create_preview_jpg(src, neutral_jpg, preview_config=neutral_cfg) is not None
        assert create_preview_jpg(src, boost_jpg, preview_config=boost_cfg) is not None

        neutral_arr = _load_jpg_array(neutral_jpg).astype(np.float32)
        boost_arr = _load_jpg_array(boost_jpg).astype(np.float32)

        # Saettigung aendert das Bild (nicht identisch)
        assert not np.array_equal(neutral_arr, boost_arr)

        # Kein NaN/Inf und kein Ueberlauf
        assert np.isfinite(boost_arr).all()
        assert boost_arr.max() <= 255
        assert boost_arr.min() >= 0

    def test_saturation_factor_ranges(self):
        """_apply_saturation skaliert Sättigung korrekt (0.5..2.0)."""
        rgb = np.array([[[0.5, 0.2, 0.1]]], dtype=np.float64)  # etwas gesättigt
        desat = _apply_saturation(rgb, 0.5)
        boost = _apply_saturation(rgb, 1.5)

        # Desaturation reduziert Differenz zwischen Kanälen
        assert abs(float(desat[0, 0, 0]) - float(desat[0, 0, 2])) <= abs(float(rgb[0, 0, 0]) - float(rgb[0, 0, 2]))
        # Boost erhoeht Differenz
        assert abs(float(boost[0, 0, 0]) - float(boost[0, 0, 2])) >= abs(float(rgb[0, 0, 0]) - float(rgb[0, 0, 2]))


# ═══════════════════════════════════════════════════════════════════
# AC-PREV-A3: Background Neutralization
# ═══════════════════════════════════════════════════════════════════


class TestPreviewBackgroundNeutralization:
    def test_background_median_near_zero(self):
        """background_neutralization zieht den Median pro Kanal ab."""
        h, w = 64, 64
        y, x = np.ogrid[:h, :w]
        gradient = (x + y).astype(np.float64) * 2.0
        data = np.stack([gradient + 10, gradient + 12, gradient + 8], axis=-1)

        corrected = _apply_background_neutralization(data)

        # Hintergrund-Median pro Kanal soll ~0 sein
        for c in range(3):
            assert np.median(corrected[:, :, c]) == pytest.approx(0.0, abs=0.5)
        # Keine negativen Werte
        assert corrected.min() >= 0.0

    def test_background_neutralization_in_preview(self, tmp_path: Path):
        """Preview mit bg_neutral=true gleicht Hintergrund ab."""
        src = tmp_path / "bg.fits"
        h, w = 64, 64
        data = np.full((h, w, 3), 100.0, dtype=np.float32)
        data[:, :, 0] += 20  # R-Offset
        data[:, :, 1] += 10  # G-Offset
        data[:, :, 2] += 30  # B-Offset
        out = data.transpose(2, 0, 1)
        fits.PrimaryHDU(out.astype(np.float32)).writeto(src, overwrite=True)

        off_jpg = tmp_path / "bg_off.jpg"
        on_jpg = tmp_path / "bg_on.jpg"

        off_cfg = PreviewExportConfig(background_neutralization=False, stretch="none")
        on_cfg = PreviewExportConfig(background_neutralization=True, stretch="none")

        assert create_preview_jpg(src, off_jpg, preview_config=off_cfg) is not None
        assert create_preview_jpg(src, on_jpg, preview_config=on_cfg) is not None

        on_arr = _load_jpg_array(on_jpg).astype(np.float32)
        # Da Hintergrund neutralisiert und stretch=none: Kanal-Mediane sollten
        # sehr nah beieinander liegen (nicht exakt 0 wegen uint8-Quantisierung).
        meds = [np.median(on_arr[:, :, c]) for c in range(3)]
        assert max(meds) - min(meds) < 5.0


# ═══════════════════════════════════════════════════════════════════
# AC-PREV-A4: Rueckwaertskompatibilitaet (byte-identisch v1.6)
# ═══════════════════════════════════════════════════════════════════


class TestPreviewBackwardCompat:
    def test_no_config_block_byte_identical_to_v16(self, tmp_path: Path):
        """Ohne preview_config (bzw. None) bleibt der Output identisch zum
        v1.6 Asinh-only Pfad."""
        src = create_test_fits(tmp_path / "compat.fits", shape=(64, 64, 3), value=5.0, rng_seed=11)

        legacy_jpg = tmp_path / "legacy.jpg"
        explicit_none_jpg = tmp_path / "explicit_none.jpg"
        asinh_only_jpg = tmp_path / "asinh_only.jpg"

        # v1.6-Aufruf ohne preview_config
        assert create_preview_jpg(src, legacy_jpg) is not None
        # Explizit None
        assert create_preview_jpg(src, explicit_none_jpg, preview_config=None) is not None
        # Asinh-only Config (Preset-Default ohne Config-Block)
        asinh_only_cfg = PreviewExportConfig(
            stretch="asinh", scnr=False, saturation=1.0,
            background_neutralization=False,
        )
        assert create_preview_jpg(src, asinh_only_jpg, preview_config=asinh_only_cfg) is not None

        legacy_bytes = legacy_jpg.read_bytes()
        none_bytes = explicit_none_jpg.read_bytes()
        cfg_bytes = asinh_only_jpg.read_bytes()

        assert none_bytes == legacy_bytes
        assert cfg_bytes == legacy_bytes


# ═══════════════════════════════════════════════════════════════════
# AC-PREV-A5: Dokumentation in inspect + agent-log
# ═══════════════════════════════════════════════════════════════════


class TestPreviewExportDocumentation:
    def test_resolve_preview_export_config_uses_config_block(self):
        """Config-Block gewinnt ueber Preset-Defaults."""
        cfg = AppConfig(
            export=ExportConfig(
                preview=PreviewExportConfig(
                    stretch="linear",
                    scnr=True,
                    saturation=1.5,
                    background_neutralization=True,
                )
            )
        )
        pipeline = PipelinePreset(
            name="test", target_types=["test"], steps=[],
            processing_params=ProcessingParams(
                preview_export=PreviewExportConfig(stretch="asinh", scnr=False)
            ),
        )
        effective = resolve_preview_export_config(cfg, pipeline)
        assert effective.stretch == "linear"
        assert effective.scnr is True
        assert effective.saturation == pytest.approx(1.5)
        assert effective.background_neutralization is True

    def test_resolve_preview_export_config_defaults_asinh_only(self):
        """Ohne Config-Block -> Asinh-only Defaults."""
        cfg = AppConfig()
        pipeline = PipelinePreset(name="test", target_types=["test"], steps=[])
        effective = resolve_preview_export_config(cfg, pipeline)
        assert effective.stretch == "asinh"
        assert effective.scnr is False
        assert effective.saturation == pytest.approx(1.0)
        assert effective.background_neutralization is False

    def test_preview_export_config_model_defaults_are_feature_defaults(self):
        """PreviewExportConfig-Model repraesentiert die empfohlenen Feature-Defaults."""
        cfg = PreviewExportConfig()
        assert cfg.stretch == "asinh"
        assert cfg.scnr is True
        assert cfg.saturation == pytest.approx(1.2)
        assert cfg.background_neutralization is True

    def test_processing_result_carries_preview_export(self, tmp_path: Path):
        """ProcessingResult.preview_export enthaelt die effektiven Settings."""
        src = create_test_fits(tmp_path / "doc.fits", shape=(64, 64, 3), value=5.0, rng_seed=13)
        cfg = AppConfig(
            export=ExportConfig(
                preview=PreviewExportConfig(scnr=True, saturation=1.2)
            )
        )
        exports = export(src, "DocTarget", working_dir=tmp_path, preview_config=cfg.export.preview)
        assert exports

        result = ProcessingResult(exports=exports, preview_export=cfg.export.preview.model_dump())
        assert result.preview_export is not None
        assert result.preview_export["scnr"] is True
        assert result.preview_export["saturation"] == pytest.approx(1.2)

    def test_agent_log_contains_preview_export(self, tmp_path: Path):
        """agent-log.yaml enthaelt processing.preview_export."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        ctx = make_sample_context(tmp_path)

        result = ProcessingResult(
            exports=[output_dir / "dummy.fits"],
            preview_export={
                "stretch": "asinh",
                "scnr": True,
                "saturation": 1.2,
                "background_neutralization": True,
            },
        )

        # Dummy CalibrationResult
        cal_result = MagicMock()
        cal_result.master_dark = None
        cal_result.calibrated_lights = []

        agent = ArchiveAgent(output_dir, config=None)
        log_path = agent._create_agent_log(output_dir, ctx, result, cal_result)

        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert "processing" in log
        pe = log["processing"].get("preview_export")
        assert pe is not None
        assert pe["stretch"] == "asinh"
        assert pe["scnr"] is True
        assert pe["saturation"] == pytest.approx(1.2)
        assert pe["background_neutralization"] is True

    def test_inspect_json_contains_preview_export(self, tmp_path: Path):
        """astra inspect --json enthaelt preview_export Block."""
        from click.testing import CliRunner
        from astro_process.cli import cli

        # Synthetic target mit einem Light-Frame
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

        # Config mit explizitem export.preview Block
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            'export:\n  preview:\n    stretch: linear\n    scnr: true\n    '
            'saturation: 1.2\n    background_neutralization: true\n',
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--config", str(config_file), "inspect", str(target), "--json"],
        )
        assert result.exit_code == 0, result.output
        # Ausgabe enthaelt structlog-Events + das multi-line inspect-JSON.
        # Letzter Block ab der letzten Zeile, die mit '{' beginnt.
        lines = result.output.splitlines()
        start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                start = i
        assert start is not None, "Kein JSON-Start in inspect-Ausgabe"
        output = json.loads("\n".join(lines[start:]))
        assert "preview_export" in output
        pe = output["preview_export"]
        assert pe["stretch"] == "linear"
        assert pe["scnr"] is True
        assert pe["saturation"] == pytest.approx(1.2)
        assert pe["background_neutralization"] is True


# ═══════════════════════════════════════════════════════════════════
# Edge-Cases
# ═══════════════════════════════════════════════════════════════════


class TestPreviewExportEdgeCases:
    def test_all_steps_disabled(self, tmp_path: Path):
        """Alle Steps aus = Asinh-only, identisch zum Default."""
        src = create_test_fits(tmp_path / "all_off.fits", shape=(64, 64, 3), value=5.0, rng_seed=17)
        legacy_jpg = tmp_path / "legacy.jpg"
        all_off_jpg = tmp_path / "all_off.jpg"

        assert create_preview_jpg(src, legacy_jpg) is not None
        all_off_cfg = PreviewExportConfig(
            stretch="asinh",
            scnr=False,
            saturation=1.0,
            background_neutralization=False,
        )
        assert create_preview_jpg(src, all_off_jpg, preview_config=all_off_cfg) is not None

        assert all_off_jpg.read_bytes() == legacy_jpg.read_bytes()

    def test_stretch_linear(self, tmp_path: Path):
        """stretch: linear erzeugt ein gueltiges JPG ohne Asinh-Kruemmung."""
        src = create_test_fits(tmp_path / "linear.fits", shape=(64, 64, 3), value=8.0, rng_seed=19)
        linear_jpg = tmp_path / "linear.jpg"
        linear_cfg = PreviewExportConfig(stretch="linear")
        assert create_preview_jpg(src, linear_jpg, preview_config=linear_cfg) is not None

        arr = _load_jpg_array(linear_jpg)
        assert arr.shape == (64, 64, 3)
        assert np.isfinite(arr).all()
        assert arr.max() <= 255

    def test_stretch_none(self, tmp_path: Path):
        """stretch: none erzeugt ein gueltiges JPG ohne Stretch."""
        src = create_test_fits(tmp_path / "none.fits", shape=(64, 64, 3), value=8.0, rng_seed=23)
        none_jpg = tmp_path / "none.jpg"
        none_cfg = PreviewExportConfig(stretch="none")
        assert create_preview_jpg(src, none_jpg, preview_config=none_cfg) is not None

        arr = _load_jpg_array(none_jpg)
        assert arr.shape == (64, 64, 3)
        assert np.isfinite(arr).all()
        assert arr.max() <= 255

    def test_stretch_methods_differ(self, tmp_path: Path):
        """asinh, linear, none erzeugen unterschiedliche Ergebnisse."""
        src = create_test_fits(tmp_path / "methods.fits", shape=(64, 64, 3), value=8.0, rng_seed=29)
        results = {}
        for method in ("asinh", "linear", "none"):
            path = tmp_path / f"{method}.jpg"
            cfg = PreviewExportConfig(stretch=method)
            assert create_preview_jpg(src, path, preview_config=cfg) is not None
            results[method] = _load_jpg_array(path)

        assert not np.array_equal(results["asinh"], results["linear"])
        assert not np.array_equal(results["linear"], results["none"])

    def test_apply_stretch_methods(self):
        """_apply_stretch verzweigt korrekt."""
        data = np.array([[[0.0, 0.5, 1.0]]], dtype=np.float32)
        asinh = _apply_stretch(data, "asinh", sigma_factor=3.0)
        linear = _apply_stretch(data, "linear", sigma_factor=3.0)
        none_ = _apply_stretch(data, "none", sigma_factor=3.0)

        assert asinh.shape == data.shape
        assert linear.shape == data.shape
        assert none_.shape == data.shape
        assert np.isfinite(asinh).all()
        assert np.isfinite(linear).all()
        assert np.isfinite(none_).all()
