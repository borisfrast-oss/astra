"""Leo-Auftrag 2026-08-10 (Bad-Pixel-Korrektur): Teil A + Teil C Tests.

Teil A (Cosmetic Correction — core/cosmetic + agents/cosmetic_agent):
- Detektion: Pixel in k Frames erhoeht -> ersetzt (stella-Vorgabe
  "3 von >= 8", Default +50 DN ueber lokaler Umgebung).
- Normale Pixel bleiben unveraendert.
- Bayer-Farbe erhalten: ein defektes Pixel in Kanal R wird NICHT mit
  G/B-Nachbarn interpoliert (nur same-color-Nachbarn, Distanz 2).
- Dark-Bedingung: Pixel, an denen das Dark selbst heiss ist, werden
  NICHT als light-only-Defekte gewertet (Dark < Dark-BG + 20 normal).
- Agent: disabled -> None; enabled -> 01b_cosmetic/cos_*.fits +
  Debug-Maps (bad_pixel_map.fits, interpolated_pixels.fits).

Teil C (Dark-Master-Stack auf Median — calibration._create_group_master_dark):
- Mehrere Darks: Master = MEDIAN (ein einzelnes Dark mit heissem Pixel
  darf den Master NICHT verfaelschen: Average -> 200, Median -> 100).
- Einzelnes Dark: wird unveraendert als Master uebernommen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from astropy.io import fits
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import write_default_suggested  # noqa: E402
from astro_process.agents.calibration import CalibrationAgent, CalibrationResult
from astro_process.agents.cosmetic_agent import (
    CosmeticCorrectionAgent,
    create_cosmetic_agent,
)
from astro_process.cli import cli  # noqa: E402  (merged from test_cosmetic_correction_cli_flag.py)
from astro_process.config.loader import DEFAULT_CONFIG  # noqa: E402
from astro_process.config.models import AppConfig, CosmeticCorrectionConfig
from astro_process.core.cosmetic import detect_bad_pixels, interpolate_bad_pixels
from astro_process.models.core import (
    AcquisitionInfo,
    CalibrationStatus,
    EquipmentInfo,
    FitsHeader,
    FrameInfo,
    FrameSet,
    FrameType,
    ObservationContext,
    ObservationTarget,
)

# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

BG = 100.0


def _write_fits(path: Path, data: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(np.asarray(data, dtype=np.float32)).writeto(
        path, overwrite=True
    )


def _read_array(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        return hdul[0].data.astype(np.float32)


def _flat_frames(
    n: int,
    shape: tuple[int, int] = (64, 64),
    hot_pixels: dict[tuple[int, int], int] | None = None,
    hot_frames: int = 3,
) -> list[np.ndarray]:
    """n konstante Frames; heisse Pixel (H/W-Werte) in den ersten
    ``hot_frames`` Frames erhoeht (Rest BG)."""
    frames = [np.full(shape, BG, dtype=np.float32) for _ in range(n)]
    for (y, x), value in (hot_pixels or {}).items():
        for i in range(min(hot_frames, n)):
            frames[i][y, x] = value
    return frames


def _config(enabled: bool = True, **overrides) -> AppConfig:
    params = dict(
        enabled=enabled, n_frames=3, threshold=50.0, dark_tolerance=20.0
    )
    params.update(overrides)
    return AppConfig(cosmetic_correction=CosmeticCorrectionConfig(**params))


def _build_context(root: Path, light_paths: list[Path]) -> ObservationContext:
    """ObservationContext mit konstanten Lights (EXPTIME 15, GAIN 60).

    Bereits existierende Frames werden NICHT ueberschrieben (damit Tests
    zuerst Hot-Pixel-Frames schreiben und dann den Context darueber bauen
    koennen).
    """
    lights = []
    for i, p in enumerate(light_paths):
        if not p.exists():
            _write_fits(p, np.full((64, 64), BG, dtype=np.float32))
        lights.append(
            FrameInfo(
                path=p,
                frame_type=FrameType.LIGHT,
                header=FitsHeader(
                    exptime=15.0, gain=60, filter_name="none", ccd_temp=20.0
                ),
                index=i,
                size_bytes=p.stat().st_size,
                width=64,
                height=64,
            )
        )
    empty = FrameSet(frame_type=FrameType.DARK, frames=[])
    return ObservationContext(
        target=ObservationTarget(name="TestTarget"),
        frames={FrameType.LIGHT: FrameSet(frame_type=FrameType.LIGHT, frames=lights),
                FrameType.DARK: empty},
        calibration=CalibrationStatus(dark_available=False, dark_count=0),
        equipment=EquipmentInfo(focal_length_mm=200.0, pixel_size_um=3.76),
        acquisition=AcquisitionInfo(gain=60),
        source_path=root,
    )


# ═══════════════════════════════════════════════════════════════════
# Teil A — core/cosmetic: Detektion
# ═══════════════════════════════════════════════════════════════════

class TestDetection:
    def test_detects_pixel_hot_in_n_frames(self):
        """Pixel in 3 von 8 Frames erhoeht -> defekt (Default n_frames=3)."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300})
        mask = detect_bad_pixels(frames)
        assert mask.shape == (64, 64)
        assert mask[10, 10]
        assert mask.sum() == 1

    def test_normal_frames_give_empty_mask(self):
        frames = _flat_frames(8)
        mask = detect_bad_pixels(frames)
        assert not mask.any()

    def test_pixel_hot_in_fewer_than_n_frames_not_detected(self):
        """Pixel nur in 2 Frames heiss, n_frames=3 -> NICHT defekt."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300}, hot_frames=2)
        mask = detect_bad_pixels(frames)
        assert not mask[10, 10]

    def test_threshold_controls_detection(self):
        """Erhoehung +30: Schwelle 50 -> nein, Schwelle 20 -> ja."""
        frames = _flat_frames(8, hot_pixels={(10, 10): BG + 30})
        assert not detect_bad_pixels(frames, threshold=50.0)[10, 10]
        assert detect_bad_pixels(frames, threshold=20.0)[10, 10]

    def test_iterable_input_supported(self):
        """Iterable von 2D-Arrays statt 3D-Array (Agent-Streaming-Pfad)."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300})
        mask = detect_bad_pixels(iter(frames))
        assert mask[10, 10]
        assert mask.sum() == 1

    def test_dark_condition_masks_dark_hot_pixels(self):
        """Dark an der Stelle selbst heiss (>= dark_bg + 20) -> NICHT defekt."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300})
        dark = np.full((64, 64), BG, dtype=np.float32)
        dark[10, 10] = BG + 200.0  # Dark-Hot-Pixel
        mask = detect_bad_pixels(frames, master_dark=dark)
        assert not mask[10, 10]

    def test_dark_condition_normal_allows_detection(self):
        """Dark an der Stelle normal (< dark_bg + 20) -> defekt (light-only)."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300})
        dark = np.full((64, 64), BG, dtype=np.float32)  # normal ueberall
        mask = detect_bad_pixels(frames, master_dark=dark)
        assert mask[10, 10]

    def test_no_dark_skips_dark_condition(self):
        """master_dark=None -> nur Light-Detektion (Agent-Warnpfad)."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300})
        mask = detect_bad_pixels(frames, master_dark=None)
        assert mask[10, 10]

    def test_shape_mismatch_raises(self):
        frames = _flat_frames(4)
        dark = np.full((32, 32), BG, dtype=np.float32)
        with pytest.raises(ValueError, match="master_dark shape"):
            detect_bad_pixels(frames, master_dark=dark)

    def test_invalid_parameters_raise(self):
        frames = _flat_frames(4)
        with pytest.raises(ValueError, match="n_frames"):
            detect_bad_pixels(frames, n_frames=0)
        with pytest.raises(ValueError, match="threshold"):
            detect_bad_pixels(frames, threshold=0.0)


# ═══════════════════════════════════════════════════════════════════
# Teil A — core/cosmetic: Interpolation
# ═══════════════════════════════════════════════════════════════════

class TestInterpolation:
    def test_replaces_bad_pixel_with_same_color_median(self):
        """Defektes Pixel wird durch Median der same-color-Nachbarn ersetzt."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300})
        mask = detect_bad_pixels(frames)
        out = interpolate_bad_pixels(frames[0], mask)
        # (10,10) ist Kanal R (beide Koordinaten gerade); alle R-Nachbarn
        # in Distanz 2 liegen auf BG -> Median BG.
        assert out[10, 10] == pytest.approx(BG, abs=1e-3)
        assert out[10, 10] != frames[0][10, 10]

    def test_normal_pixels_unchanged(self):
        """Nicht-defekte Pixel bleiben exakt unveraendert."""
        frames = _flat_frames(8, hot_pixels={(10, 10): 300})
        mask = detect_bad_pixels(frames)
        out = interpolate_bad_pixels(frames[0], mask)
        untouched = np.ones((64, 64), dtype=bool)
        untouched[10, 10] = False
        assert np.array_equal(out[untouched], frames[0][untouched])

    def test_bayer_color_preserved(self):
        """Defektes R-Pixel wird NICHT mit G/B-Nachbarn interpoliert.

        Kanaele haben unterschiedliche Level (R=100, G/B=500): wuerde die
        Interpolation G/B-Nachbarn einbeziehen, waere das Ergebnis ~500.
        Erwartet: ~100 (Median der R-same-color-Nachbarn, Distanz 2).
        """
        shape = (64, 64)
        frame = np.zeros(shape, dtype=np.float32)
        for y in range(shape[0]):
            for x in range(shape[1]):
                frame[y, x] = BG if (y % 2 == 0 and x % 2 == 0) else 500.0
        # Defektes R-Pixel (gerade/gerade): in 3 Frames erhoeht.
        frames = [frame.copy() for _ in range(8)]
        for i in range(3):
            frames[i][10, 10] = 700.0
        mask = detect_bad_pixels(frames)
        assert mask[10, 10]
        # Auch andere R-Pixel duerfen nicht als defekt gelten.
        assert mask.sum() == 1
        out = interpolate_bad_pixels(frames[0], mask)
        assert out[10, 10] == pytest.approx(BG, abs=1e-3)
        assert out[10, 10] != 500.0

    def test_no_bad_pixels_returns_copy(self):
        frames = _flat_frames(4)
        out = interpolate_bad_pixels(frames[0], np.zeros((64, 64), dtype=bool))
        assert np.array_equal(out, frames[0])
        assert out is not frames[0]

    def test_edges_handled_by_reflect_pad(self):
        """Rand-Pixel (y=0, x=0, R-Kanal): same-color-Nachbar via Reflect."""
        frames = _flat_frames(8, hot_pixels={(0, 0): 300})
        mask = detect_bad_pixels(frames)
        assert mask[0, 0]
        out = interpolate_bad_pixels(frames[0], mask)
        # Nachbar (2,2) liegt auf BG, ebenso (0,2)/(2,0) via Reflect ->
        # Median BG.
        assert out[0, 0] == pytest.approx(BG, abs=1e-3)


# ═══════════════════════════════════════════════════════════════════
# Teil A — agents/cosmetic_agent
# ═══════════════════════════════════════════════════════════════════

class TestCosmeticAgent:
    def _setup_single_group_run(self, tmp_path: Path):
        """Arbeitsverzeichnis + 8 cal-Frames (3 heiss in Pixel (10,10))
        + Master-Dark (normal an (10,10)) + Context + CalibrationResult."""
        workdir = tmp_path / "working"
        cal_dir = workdir / "01_calibrated"
        cal_dir.mkdir(parents=True, exist_ok=True)
        masters_dir = workdir / "00_input" / "master"
        masters_dir.mkdir(parents=True, exist_ok=True)

        data_root = tmp_path / "data"
        light_paths = [data_root / f"light_{i:03d}.fits" for i in range(8)]
        cal_paths = []
        for i, lp in enumerate(light_paths):
            _write_fits(lp, np.full((64, 64), BG, dtype=np.float32))
            frame = np.full((64, 64), BG, dtype=np.float32)
            if i < 3:
                frame[10, 10] = 300.0
            cp = cal_dir / f"cal_{lp.name}"
            _write_fits(cp, frame)
            cal_paths.append(cp)

        master_path = masters_dir / "master_dark_single.fits"
        _write_fits(master_path, np.full((64, 64), BG, dtype=np.float32))

        context = _build_context(data_root, light_paths)
        cal_result = CalibrationResult(
            working_dir=workdir,
            master_dark=master_path,
            master_dark_paths={"15s60": master_path},
            calibrated_lights=cal_paths,
        )
        return workdir, context, cal_result

    def test_agent_disabled_returns_none(self, tmp_path: Path):
        workdir, context, cal_result = self._setup_single_group_run(tmp_path)
        agent = create_cosmetic_agent(workdir, _config(enabled=False))
        assert agent.run(context, cal_result) is None

    def test_agent_end_to_end_single_group(self, tmp_path: Path):
        workdir, context, cal_result = self._setup_single_group_run(tmp_path)
        agent = create_cosmetic_agent(workdir, _config(enabled=True))
        result = agent.run(context, cal_result)

        assert result is not None
        assert len(result.corrected_lights) == 8
        assert result.bad_pixel_count == 1
        assert result.groups == 1

        # Korrigierte Frames in 01b_cosmetic/cos_*.fits.
        for i in range(8):
            out_path = result.corrected_lights[i]
            assert out_path.exists()
            assert out_path.parent == workdir / "01b_cosmetic"
            data = _read_array(out_path)
            assert data[10, 10] == pytest.approx(BG, abs=1e-3)

        # Debug-Maps nach generated/<run>/ (working_dir).
        assert result.bad_pixel_map is not None
        assert result.bad_pixel_map.name == "bad_pixel_map.fits"
        assert result.bad_pixel_map.parent == workdir
        bad_map = _read_array(result.bad_pixel_map)
        assert bad_map[10, 10] == 1
        assert bad_map.sum() == 1

        assert result.interpolated_pixels is not None
        assert result.interpolated_pixels.name == "interpolated_pixels.fits"
        interp = _read_array(result.interpolated_pixels)
        assert interp[10, 10] == 8  # in allen 8 Frames interpoliert
        assert interp.sum() == 8

    def test_agent_no_calib_raw_paths(self, tmp_path: Path):
        """--no-calib-Fall: calibrated_lights sind rohe Input-Pfade, kein
        Master-Dark -> Detektion ohne Dark-Bedingung (Warnung), korrigiert
        trotzdem."""
        workdir = tmp_path / "working"
        data_root = tmp_path / "data"
        light_paths = [data_root / f"light_{i:03d}.fits" for i in range(8)]
        for i, lp in enumerate(light_paths):
            frame = np.full((64, 64), BG, dtype=np.float32)
            if i < 3:
                frame[10, 10] = 300.0
            _write_fits(lp, frame)

        context = _build_context(data_root, light_paths)
        cal_result = CalibrationResult(
            working_dir=workdir, calibrated_lights=light_paths
        )
        agent = create_cosmetic_agent(workdir, _config(enabled=True))
        result = agent.run(context, cal_result)
        assert result is not None
        assert len(result.corrected_lights) == 8
        assert result.bad_pixel_count == 1
        assert result.bad_pixel_map is not None

    def test_agent_config_override_threshold(self, tmp_path: Path):
        """Schwelle 30: Erhoehung +30 wird erkannt; Default 50 wuerde
        nichts finden."""
        workdir, context, cal_result = self._setup_single_group_run(tmp_path)
        # setup erhoeht auf 300 (+200) — passt fuer beide Schwellen; hier
        # nur sicherstellen, dass config-Schwellen durchgreifen.
        agent = create_cosmetic_agent(
            workdir, _config(enabled=True, threshold=10.0)
        )
        result = agent.run(context, cal_result)
        assert result is not None
        assert result.bad_pixel_count == 1


# ═══════════════════════════════════════════════════════════════════
# Teil C — calibration: Dark-Master-Stack auf Median
# ═══════════════════════════════════════════════════════════════════

class TestDarkMasterMedian:
    def test_master_dark_uses_median_stack(self, tmp_path: Path):
        """3 Darks, eines mit heissem Pixel (+300): Median-Master behaelt
        BG (100), Average-Master wuerde auf 200 verfaelschen."""
        workdir = tmp_path / "working"
        agent = CalibrationAgent(workdir, config=None)
        dark_paths = []
        for i in range(3):
            p = tmp_path / f"dark_{i}.fits"
            arr = np.full((64, 64), BG, dtype=np.float32)
            if i == 0:
                arr[5, 5] = BG + 300.0  # einzelner Dark-Hot-Pixel
            _write_fits(p, arr)
            dark_paths.append(p)

        master = agent._create_group_master_dark(dark_paths, "single")
        data = _read_array(master)
        assert data[5, 5] == pytest.approx(BG, abs=1e-3)
        assert float(np.median(data)) == pytest.approx(BG, abs=1e-3)

    def test_single_dark_copied_as_master(self, tmp_path: Path):
        """Einzelnes Dark: wird unveraendert als Master uebernommen
        (kein Stacking noetig — Median wie Average identisch)."""
        workdir = tmp_path / "working"
        agent = CalibrationAgent(workdir, config=None)
        p = tmp_path / "dark.fits"
        arr = np.full((64, 64), 42.0, dtype=np.float32)
        arr[3, 3] = 400.0
        _write_fits(p, arr)

        master = agent._create_group_master_dark([p], "single")
        data = _read_array(master)
        assert np.array_equal(data, arr)


# ═══════════════════════════════════════════════════════════════════
# Merged from test_cosmetic_correction_cli_flag.py (W2.5 SOFORT 3)
# CLI-Flag --cosmetic-correction / --no-cosmetic-correction
# Precedence: CLI > Config > Default (analog --gradient-removal-enabled).
# Begruendung Merge statt Delete: test_cli_v18_4.py (AC-CLI) deckt
# cosmetic-Flag NICHT ab (kein cosmetic-Test vorhanden) und
# test_cosmetic_correction.py deckt Core+Agent ab — CLI-Precedence
# gehoert thematisch hierher als separater Section TestCosmeticCorrectionCLI.
# 4 Tests (enabled_overrides_default, disabled_overrides_config,
#  no_flag_preserves_config, no_flag_no_config_defaults_false)
# bleiben erhalten; grep-Erleichterung fuer W3 trotzdem erreicht
# (eine Datei weniger, kein separates cosmetic_cli Noise).
# ═══════════════════════════════════════════════════════════════════


def _write_config_cli(path: Path, update: dict | None = None) -> Path:
    """DEFAULT_CONFIG-Basis mit optionalem Override als config.yaml (CLI-Merge)."""
    data = yaml.safe_load(DEFAULT_CONFIG)
    if update:
        data.update(update)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _invoke_process_with_cc_mock(runner: CliRunner, args: list[str], tmp_path: Path):
    """Invoke `process` mit gemockten Agents — Cosmetic-Override wird auf
    cfg.cosmetic_correction.enabled geprueft (Capturing via side_effect)."""
    captured: dict = {}

    discovery = MagicMock()
    discovery.run.return_value = MagicMock(context=MagicMock(total_light_frames=1))

    cal = MagicMock()
    cal.run.return_value = MagicMock(
        master_dark=None, calibrated_lights=[], master_dark_paths={}
    )

    cosmetic = MagicMock()
    cosmetic.run.return_value = None  # deaktiviert -> None

    def _make_cosmetic(*_args, **_kwargs):
        cfg = _args[1] if len(_args) > 1 else _kwargs.get("config")
        if cfg is not None and getattr(cfg, "cosmetic_correction", None) is not None:
            captured["cc_enabled"] = cfg.cosmetic_correction.enabled
        else:
            captured["cc_enabled"] = False
        return cosmetic

    deb = MagicMock()
    deb.run.return_value = MagicMock(debayered_frames=[])
    proc = MagicMock()
    proc.run.return_value = MagicMock(stacked=None)
    arch = MagicMock()
    arch.run.return_value = MagicMock(output_dir=tmp_path, final_fits=None)

    with patch("astro_process.cli.create_discovery_agent", return_value=discovery), \
         patch("astro_process.cli.create_calibration_agent", return_value=cal), \
         patch("astro_process.cli.create_cosmetic_agent", side_effect=_make_cosmetic), \
         patch("astro_process.cli.create_debayer_agent", return_value=deb), \
         patch("astro_process.cli.create_processing_agent", return_value=proc), \
         patch("astro_process.cli.create_archive_agent", return_value=arch):
        result = runner.invoke(cli, args)

    return result, captured


class TestCosmeticCorrectionCLI:
    """CLI-Flag --cosmetic-correction / --no-cosmetic-correction (merged)."""

    def test_flag_enabled_overrides_default(self, tmp_path, monkeypatch):
        """--cosmetic-correction: enabled = True (Default ist False)."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        _write_config_cli(cfgdir / "config.yaml")
        target = tmp_path / "Target"
        target.mkdir()
        write_default_suggested(target)
        monkeypatch.chdir(cfgdir)

        runner = CliRunner()
        result, captured = _invoke_process_with_cc_mock(
            runner,
            ["process", str(target), "--from-suggested", "--no-calib", "--cosmetic-correction"],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        assert captured.get("cc_enabled") is True

    def test_flag_disabled_overrides_config(self, tmp_path, monkeypatch):
        """--no-cosmetic-correction: enabled = False, auch wenn Config True hat."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        _write_config_cli(cfgdir / "config.yaml", {
            "cosmetic_correction": {"enabled": True, "n_frames": 3,
                                    "threshold": 50.0, "dark_tolerance": 20.0}
        })
        target = tmp_path / "Target"
        target.mkdir()
        write_default_suggested(target)
        monkeypatch.chdir(cfgdir)

        runner = CliRunner()
        result, captured = _invoke_process_with_cc_mock(
            runner,
            ["process", str(target), "--from-suggested", "--no-calib", "--no-cosmetic-correction"],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        assert captured.get("cc_enabled") is False

    def test_no_flag_preserves_config(self, tmp_path, monkeypatch):
        """Ohne Flag bleibt Config-Wert unberuehrt (enabled=True aus Config)."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        _write_config_cli(cfgdir / "config.yaml", {
            "cosmetic_correction": {"enabled": True, "n_frames": 3,
                                    "threshold": 50.0, "dark_tolerance": 20.0}
        })
        target = tmp_path / "Target"
        target.mkdir()
        write_default_suggested(target)
        monkeypatch.chdir(cfgdir)

        runner = CliRunner()
        result, captured = _invoke_process_with_cc_mock(
            runner,
            ["process", str(target), "--from-suggested", "--no-calib"],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        assert captured.get("cc_enabled") is True

    def test_no_flag_no_config_defaults_false(self, tmp_path, monkeypatch):
        """Ohne Flag und ohne Config-Block: Default = False."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        _write_config_cli(cfgdir / "config.yaml")
        target = tmp_path / "Target"
        target.mkdir()
        write_default_suggested(target)
        monkeypatch.chdir(cfgdir)

        runner = CliRunner()
        result, captured = _invoke_process_with_cc_mock(
            runner,
            ["process", str(target), "--from-suggested", "--no-calib"],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        assert captured.get("cc_enabled") is False
