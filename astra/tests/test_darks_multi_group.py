"""T3: Per-Group Darks im Multi-Group-Modus + dark_source in merge_report.json.

Eigene minimale FITS-Fixtures (64x64, konstant) — keine Imports aus
tests/synthetic.py (Parallel-Dev T4) und keine Änderungen an
tests/test_multi_group.py.

Abdeckung:
- T3a-1: Multi-Group -> master_dark_{group_hash}.fits pro Gruppe
- T3a-2: Single-Group -> weiterhin master_dark_single.fits (Backward-Compat)
- T3a-3: Gruppe ohne Dark -> KEIN Master, dark_source "none", KEIN Fallback
  (keine Cross-Contamination; Lights bleiben unkalibriert)
- T3a-4: Darks-Library exakter Match -> dark_source "library_exact", kein
  Kopieren in die Library (E2)
- T3a-5: Darks-Library nur Temp-nächster Match -> dark_source "library_nearest"
- T3b-1: processing_agent gibt dark_source pro Gruppe in group_metadata durch
- T3b-2: merge_agent schreibt dark_source in input_stacks[].metadata des
  merge_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from astropy.io import fits

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.agents.calibration import CalibrationAgent, CalibrationResult
from astro_process.agents.merge_agent import MergeAgent
from astro_process.agents.processing_agent import ProcessingAgent
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
)
from astro_process.config.models import (
    MultiGroupConfig,
    ProcessingParams,
)
from astro_process.core.fits_parser import apply_filename_fallback, parse_fits_header
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
# Test Helpers — minimale eigene FITS-Fixtures
# ═══════════════════════════════════════════════════════════════════

LIGHT_VALUE = 50.0
DARK_VALUE = 10.0


def _write_fits(path: Path, data: np.ndarray, header: dict | None = None) -> None:
    """Write a 2D (or 3D) FITS file with optional header cards."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(np.asarray(data, dtype=np.float32))
    if header:
        for k, v in header.items():
            hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


def _make_light(
    path: Path,
    exptime: float,
    gain: int,
    filter_name: str | None = None,
    ccd_temp: float | None = None,
) -> FrameInfo:
    """Create a light FrameInfo (2D 64x64, constant LIGHT_VALUE)."""
    header_cards = {"EXPTIME": exptime, "GAIN": gain, "FILTER": "none", "OBJECT": "M 27"}
    if ccd_temp is not None:
        header_cards["CCD-TEMP"] = ccd_temp
    _write_fits(path, np.full((64, 64), LIGHT_VALUE, dtype=np.float32), header_cards)
    return FrameInfo(
        path=path,
        frame_type=FrameType.LIGHT,
        header=FitsHeader(exptime=exptime, gain=gain, filter_name=filter_name,
                          ccd_temp=ccd_temp),
        index=0,
        size_bytes=path.stat().st_size,
        width=64,
        height=64,
    )


def _make_local_dark(
    path: Path,
    exptime: float,
    gain: int,
    filter_name: str = "none",
    ccd_temp: float = 20.0,
) -> FrameInfo:
    """Create a local dark FrameInfo (2D 64x64, constant DARK_VALUE)."""
    _write_fits(
        path,
        np.full((64, 64), DARK_VALUE, dtype=np.float32),
        {"EXPTIME": exptime, "GAIN": gain, "FILTER": filter_name, "CCD-TEMP": ccd_temp},
    )
    return FrameInfo(
        path=path,
        frame_type=FrameType.DARK,
        header=FitsHeader(exptime=exptime, gain=gain, filter_name=filter_name,
                          ccd_temp=ccd_temp),
        index=0,
        size_bytes=path.stat().st_size,
        width=64,
        height=64,
    )


def _make_library_dark(
    path: Path,
    exptime: float,
    gain: int,
    ccd_temp: float,
    stem: str,
) -> None:
    """Write a dark FITS into a darks_repository subdir (real FITS header)."""
    _write_fits(
        path,
        np.full((64, 64), DARK_VALUE, dtype=np.float32),
        {"EXPTIME": exptime, "GAIN": gain, "FILTER": "none", "CCD-TEMP": ccd_temp},
    )


def _build_context(
    root: Path,
    light_specs: list[dict],
    dark_specs: list[dict] | None = None,
) -> ObservationContext:
    """Build an ObservationContext with lights (and optional local darks).

    light_specs: [{"exptime": float, "gain": int, "filter_name": str|None,
                   "ccd_temp": float|None}, ...]
    dark_specs:  [{"exptime": float, "gain": int, "ccd_temp": float}, ...]
    """
    lights = [
        _make_light(
            root / f"light_{i:03d}.fits",
            s["exptime"],
            s["gain"],
            s.get("filter_name"),
            s.get("ccd_temp"),
        )
        for i, s in enumerate(light_specs)
    ]

    darks = []
    for i, s in enumerate(dark_specs or []):
        darks.append(
            _make_local_dark(
                root / "darks" / f"dark_{i:03d}.fits",
                s["exptime"],
                s["gain"],
                s.get("filter_name", "none"),
                s.get("ccd_temp", 20.0),
            )
        )

    light_set = FrameSet(frame_type=FrameType.LIGHT, frames=lights)
    dark_set = FrameSet(frame_type=FrameType.DARK, frames=darks)
    cal_status = CalibrationStatus(
        dark_available=bool(darks), dark_count=len(darks)
    )
    return ObservationContext(
        target=ObservationTarget(name="TestTarget"),
        frames={FrameType.LIGHT: light_set, FrameType.DARK: dark_set},
        calibration=cal_status,
        equipment=EquipmentInfo(focal_length_mm=200.0, pixel_size_um=3.76),
        acquisition=AcquisitionInfo(gain=100),
        source_path=root,
    )


def _read_array(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        return hdul[0].data.astype(np.float32)


# ═══════════════════════════════════════════════════════════════════
# T3a — CalibrationAgent: Per-Group Master Darks
# ═══════════════════════════════════════════════════════════════════

class TestT3aPerGroupMasterDarks:
    """T3a: Per-Group Master-Darks + dark_source Bestimmung."""

    def test_multi_group_creates_per_group_master_darks(self, tmp_path: Path):
        """2 Gruppen mit lokalen Darks -> je master_dark_{hash}.fits."""
        workdir = tmp_path / "working"
        context = _build_context(
            tmp_path / "data",
            light_specs=[
                {"exptime": 15.0, "gain": 60},
                {"exptime": 15.0, "gain": 60},
                {"exptime": 60.0, "gain": 40},
                {"exptime": 60.0, "gain": 40},
            ],
            dark_specs=[
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 20.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 20.0},
            ],
        )

        agent = CalibrationAgent(workdir, config=None)
        result = agent.run(context)

        masters_dir = workdir / "00_input" / "master"
        assert (masters_dir / "master_dark_15s60.fits").exists()
        assert (masters_dir / "master_dark_60s40.fits").exists()
        # Multi-Group: kein "globaler" Master
        assert result.master_dark is None
        assert set(result.master_dark_paths) == {"15s60", "60s40"}
        assert result.master_dark_paths["15s60"] == masters_dir / "master_dark_15s60.fits"
        assert result.master_dark_paths["60s40"] == masters_dir / "master_dark_60s40.fits"
        assert result.master_dark_sources == {"15s60": "local", "60s40": "local"}
        assert result.dark_sources == {"15s60": "local", "60s40": "local"}
        # Lights wurden mit dem jeweils EIGENEN Master kalibriert (50-10=40)
        assert len(result.calibrated_lights) == 4
        for cal in result.calibrated_lights:
            assert np.allclose(_read_array(cal), LIGHT_VALUE - DARK_VALUE)

    def test_single_group_keeps_master_dark_single(self, tmp_path: Path):
        """Single-Group-Modus -> weiterhin master_dark_single.fits (Backward-Compat)."""
        workdir = tmp_path / "working"
        context = _build_context(
            tmp_path / "data",
            light_specs=[
                {"exptime": 15.0, "gain": 60},
                {"exptime": 15.0, "gain": 60},
            ],
            dark_specs=[
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
            ],
        )

        agent = CalibrationAgent(workdir, config=None)
        result = agent.run(context)

        single_master = workdir / "00_input" / "master" / "master_dark_single.fits"
        assert single_master.exists()
        assert result.master_dark == single_master
        assert result.master_dark_sources == {"15s60": "local"}
        # Per-Group-Pfad zeigt ebenfalls auf den Single-Master
        assert result.master_dark_paths["15s60"] == single_master

    def test_group_without_dark_skipped_no_fallback(self, tmp_path: Path):
        """Gruppe ohne eigenes Dark -> KEIN Master, dark_source none, KEIN Fallback."""
        workdir = tmp_path / "working"
        context = _build_context(
            tmp_path / "data",
            light_specs=[
                {"exptime": 15.0, "gain": 60},
                {"exptime": 15.0, "gain": 60},
                {"exptime": 60.0, "gain": 40},
                {"exptime": 60.0, "gain": 40},
            ],
            dark_specs=[
                # Nur Gruppe 15s60 hat lokale Darks
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
            ],
        )

        agent = CalibrationAgent(workdir, config=None)
        result = agent.run(context)

        masters_dir = workdir / "00_input" / "master"
        assert (masters_dir / "master_dark_15s60.fits").exists()
        # Kein Master fuer 60s40 (KEIN Fallback auf andere Gruppe)
        assert not (masters_dir / "master_dark_60s40.fits").exists()
        assert result.master_dark_sources == {"15s60": "local", "60s40": "none"}
        assert result.dark_sources == {"15s60": "local", "60s40": "none"}
        assert context.calibration.dark_sources == {"15s60": "local", "60s40": "none"}

        # Lights von 15s60: kalibriert (50-10=40)
        cal_values = [_read_array(c)[0, 0] for c in result.calibrated_lights]
        # Reihenfolge: erst 15s60 (40.0), dann 60s40 (50.0, unveraendert)
        assert cal_values[:2] == pytest.approx([LIGHT_VALUE - DARK_VALUE] * 2)
        assert cal_values[2:] == pytest.approx([LIGHT_VALUE] * 2)

    def test_library_exact_dark_source(self, tmp_path: Path):
        """Multi-Group + Library exakter Exposure/Gain/Temp-Match -> library_exact, kein Kopieren (E2)."""
        workdir = tmp_path / "working"
        repo = tmp_path / "darks_repo"
        for sub, exptime, gain, temp in [("180s60", 180.0, 60, 28.0),
                                         ("60s40", 60.0, 40, 24.0)]:
            lib_group_dir = repo / sub
            lib_group_dir.mkdir(parents=True, exist_ok=True)
            _make_library_dark(
                lib_group_dir / f"dark_exp_{exptime:.1f}_gain_{gain}_bin_1_{int(temp)}C_stack_1.fits",
                exptime, gain, temp, "a",
            )
            _make_library_dark(
                lib_group_dir / f"dark_exp_{exptime:.1f}_gain_{gain}_bin_1_{int(temp)}C_stack_2.fits",
                exptime, gain, temp, "b",
            )

        # KEINE lokalen Darks; Light-Temp == Library-Temp (exakter Match)
        context = _build_context(
            tmp_path / "data",
            light_specs=[
                {"exptime": 180.0, "gain": 60, "ccd_temp": 28.0},
                {"exptime": 180.0, "gain": 60, "ccd_temp": 28.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 24.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 24.0},
            ],
        )

        agent = CalibrationAgent(workdir, config=None,
                                 darks_repository=repo)
        result = agent.run(context)

        assert (workdir / "00_input" / "master" / "master_dark_180s60.fits").exists()
        assert (workdir / "00_input" / "master" / "master_dark_60s40.fits").exists()
        assert result.master_dark_sources == {
            "180s60": "library_exact", "60s40": "library_exact",
        }
        assert result.master_dark_paths["180s60"] == \
            workdir / "00_input" / "master" / "master_dark_180s60.fits"
        assert result.master_dark_paths["60s40"] == \
            workdir / "00_input" / "master" / "master_dark_60s40.fits"
        # Lights wurden mit dem jeweiligen Library-Master kalibriert
        for cal in result.calibrated_lights:
            assert np.allclose(_read_array(cal), LIGHT_VALUE - DARK_VALUE)
        # E2: Library unveraendert (kein Kopieren, nur lesend)
        assert len(list(repo.rglob("*.fits"))) == 4

    def test_library_nearest_dark_source(self, tmp_path: Path):
        """Multi-Group: Library nur Temp-naechster Match (>3C) -> library_nearest; andere Gruppe exakt."""
        workdir = tmp_path / "working"
        repo = tmp_path / "darks_repo"
        for sub, exptime, gain, temp in [("180s60", 180.0, 60, 28.0),
                                         ("60s40", 60.0, 40, 24.0)]:
            lib_group_dir = repo / sub
            lib_group_dir.mkdir(parents=True, exist_ok=True)
            _make_library_dark(
                lib_group_dir / f"dark_exp_{exptime:.1f}_gain_{gain}_bin_1_{int(temp)}C_stack_1.fits",
                exptime, gain, temp, "a",
            )
            _make_library_dark(
                lib_group_dir / f"dark_exp_{exptime:.1f}_gain_{gain}_bin_1_{int(temp)}C_stack_2.fits",
                exptime, gain, temp, "b",
            )

        # 180s60: Light-Temp 35.0 |35-28|=7 > 3 -> KEIN exakter Match, <= 10 -> nearest
        # 60s40:  Light-Temp 24.0 == Library-Temp -> exakt
        context = _build_context(
            tmp_path / "data",
            light_specs=[
                {"exptime": 180.0, "gain": 60, "ccd_temp": 35.0},
                {"exptime": 180.0, "gain": 60, "ccd_temp": 35.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 24.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 24.0},
            ],
        )

        agent = CalibrationAgent(workdir, config=None,
                                 darks_repository=repo)
        result = agent.run(context)

        assert (workdir / "00_input" / "master" / "master_dark_180s60.fits").exists()
        assert (workdir / "00_input" / "master" / "master_dark_60s40.fits").exists()
        assert result.master_dark_sources == {
            "180s60": "library_nearest", "60s40": "library_exact",
        }


# ═══════════════════════════════════════════════════════════════════
# T3b — dark_source in group_metadata + merge_report.json
# ═══════════════════════════════════════════════════════════════════

class TestT3bDarkSourceReporting:
    """T3b: dark_source pro Gruppe bis in den merge_report durchreichen."""

    def test_processing_agent_metadata_dark_source_per_group(self, tmp_path: Path):
        """process_multi_group setzt dark_source pro Gruppe aus master_dark_sources."""
        workdir = tmp_path / "working"
        data_dir = tmp_path / "data"
        context = _build_context(
            data_dir,
            light_specs=[
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
                {"exptime": 15.0, "gain": 60, "ccd_temp": 20.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 20.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 20.0},
                {"exptime": 60.0, "gain": 40, "ccd_temp": 20.0},
            ],
        )
        lights = context.get_lights()
        cal_result = CalibrationResult(
            working_dir=workdir,
            master_dark_sources={"15s60": "library_exact", "60s40": "none"},
            calibrated_lights=[f.path for f in lights.frames],
        )
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = {
            "15s60": self._write_stack(tmp_path / "stack_15s60.fits", 15.0, 60),
            "60s40": self._write_stack(tmp_path / "stack_60s40.fits", 60.0, 40),
        }

        agent = ProcessingAgent(workdir, config=None)
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            # Beide Gruppen bekommen denselben Stack (Test fokussiert Metadata)
            mock_stack.side_effect = lambda _frames, *_a, **_k: stack_fits["15s60"]
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], status="ok",
                shift_y=0.0, shift_x=0.0, correlation=0.9,
                corr_hp=0.9,
            )
            mock_pcc.side_effect = lambda stack_path, *_a, **_k: (
                stack_path, "gaia_success",
            )

            result = agent.process_multi_group(
                context,
                cal_result,
                deb_result,
                pipeline,
                multi_group_config=MultiGroupConfig(),
                merge_agent=None,
            )

        groups_meta = result.multi_group_metadata["groups"]
        assert groups_meta["15s60"]["dark_source"] == "library_exact"
        assert groups_meta["60s40"]["dark_source"] == "none"

    def test_merge_report_includes_dark_source(self, tmp_path: Path):
        """merge_report.json: input_stacks[].metadata.dark_source gesetzt."""
        stack1 = self._write_stack(tmp_path / "stack1.fits", 15.0, 60)
        stack2 = self._write_stack(tmp_path / "stack2.fits", 60.0, 40)

        agent = MergeAgent(working_dir=tmp_path, config=None)
        result = agent.run(
            group_stacks={"15s60": stack1, "60s40": stack2},
            group_metadata={
                "15s60": {
                    "frame_count": 43, "exptime": 15.0, "gain": 60,
                    "filter": None, "total_exposure": 645.0,
                    "pcc_status": "gaia_success",
                    "dark_source": "local",
                },
                "60s40": {
                    "frame_count": 28, "exptime": 60.0, "gain": 40,
                    "filter": None, "total_exposure": 1680.0,
                    "pcc_status": "gaia_success",
                    "dark_source": "library_exact",
                },
            },
            target_name="TestTarget",
        )

        assert result.merged_path is not None
        report = result.merge_report
        assert "dark_source" in report["input_stacks"][0]["metadata"]
        by_group = {s["group"]: s["metadata"]["dark_source"]
                    for s in report["input_stacks"]}
        assert by_group == {"15s60": "local", "60s40": "library_exact"}

        # Geschriebenes merge_report.json enthaelt das Feld ebenfalls
        report_path = tmp_path / "merged" / "merge_report.json"
        assert report_path.exists()
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        assert {s["group"]: s["metadata"]["dark_source"]
                for s in loaded["input_stacks"]} == by_group

    @staticmethod
    def _write_stack(path: Path, exptime: float, gain: int) -> Path:
        """Write a small 3D RGB stack FITS (C,H,W) for merge tests."""
        data = np.zeros((3, 64, 64), dtype=np.float32) + 0.5
        _write_fits(path, data, {"EXPTIME": exptime, "GAIN": gain})
        return path


# ═══════════════════════════════════════════════════════════════════
# QF-03 (QG4-Close) — Header-lose Darks: filterunabhaengiges Matching
# ═══════════════════════════════════════════════════════════════════


class TestQF03HeaderlessDarks:
    """QF-03: Header-lose M27-Darks (Dateinamen-Metadaten) matchen Lights
    mit Filter — Dark-Matching ist filterunabhaengig (nur EXPTIME/GAIN/TEMP)."""

    @staticmethod
    def _build_context(
        root: Path,
        light_filter: str | None,
        dark_paths: list[Path],
    ) -> ObservationContext:
        """Context mit einem Light (filter=light_filter) + header-losen Darks.

        Darks sind echte FITS OHNE Header-Cards (M27-Dumps); Metadaten
        kommen aus dem Dateinamen (apply_filename_fallback, V1.6-1).
        """
        light = _make_light(
            root / "light_0001.fits", 30.0, 40, light_filter, 34.0,
        )
        dark_frames = []
        for p in dark_paths:
            h = parse_fits_header(p)
            # V1.6-1: Filename-Fallback fuer Calibration-Frames
            h = apply_filename_fallback(p, h)
            dark_frames.append(
                FrameInfo(
                    path=p,
                    frame_type=FrameType.DARK,
                    header=h,
                    index=0,
                    size_bytes=p.stat().st_size,
                    width=64,
                    height=64,
                )
            )
        light_set = FrameSet(frame_type=FrameType.LIGHT, frames=[light])
        dark_set = FrameSet(frame_type=FrameType.DARK, frames=dark_frames)
        cal_status = CalibrationStatus(
            dark_available=bool(dark_frames), dark_count=len(dark_frames)
        )
        return ObservationContext(
            target=ObservationTarget(name="TestTarget"),
            frames={FrameType.LIGHT: light_set, FrameType.DARK: dark_set},
            calibration=cal_status,
            equipment=EquipmentInfo(focal_length_mm=200.0, pixel_size_um=3.76),
            acquisition=AcquisitionInfo(gain=40),
            source_path=root,
        )

    @staticmethod
    def _write_headerless_darks(directory: Path, temps: list[int]) -> list[Path]:
        """Write header-lose M27-Dumps (dark_exp_30.000000_gain_40_bin_1_*C_stack_N.fits)."""
        paths = []
        for i, temp in enumerate(temps, start=1):
            p = directory / f"dark_exp_30.000000_gain_40_bin_1_{temp}C_stack_{i}.fits"
            _write_fits(p, np.full((64, 64), DARK_VALUE, dtype=np.float32))
            paths.append(p)
        return paths

    def test_local_headerless_dark_matches_light_with_filter(self, tmp_path: Path):
        """QF-03-Kern: Light mit Filter 'Duo-', lokale header-lose Darks
        (filter=None) -> Match 'local' (vorher: no_dark_match)."""
        data_dir = tmp_path / "data"
        darks_dir = data_dir / "darks"
        darks_dir.mkdir(parents=True, exist_ok=True)
        dark_paths = self._write_headerless_darks(darks_dir, [29, 34, 38])
        context = self._build_context(data_dir, "Duo-", dark_paths)

        agent = CalibrationAgent(tmp_path / "working", config=None)
        dark_paths_found, source = agent._find_darks_for_group(
            context, (30.0, 40, "Duo-"), 34.0
        )

        assert source == "local"
        assert len(dark_paths_found) > 0
        # Temp-Band: 34 (exakt) + 31-37 (Toleranz 3.0) im echten Satz; hier nur
        # 29/34/38 -> nur 34°C liegt in Toleranz
        assert len(dark_paths_found) == 1
        assert "34C" in dark_paths_found[0].name

    def test_library_headerless_dark_matches_light_with_filter(self, tmp_path: Path):
        """M27-Fall komplett: KEINE lokalen Darks; Bibliothek `_darks/30s40`
        mit header-losen Darks -> library_exact (vorher: dark_missing)."""
        data_dir = tmp_path / "data"
        repo = tmp_path / "darks_repo"
        lib_group_dir = repo / "30s40"
        lib_group_dir.mkdir(parents=True, exist_ok=True)
        self._write_headerless_darks(lib_group_dir, [34, 35])

        context = self._build_context(data_dir, "Duo-", [])

        agent = CalibrationAgent(
            tmp_path / "working", config=None, darks_repository=repo
        )
        dark_paths_found, source = agent._find_darks_for_group(
            context, (30.0, 40, "Duo-"), 34.0
        )

        assert source == "library_exact"
        # 34°C exakt + 35°C (|35-34|=1 <= 3.0) -> beide in Toleranz
        assert len(dark_paths_found) == 2

    def test_no_temp_dark_within_tolerance_still_no_match(self, tmp_path: Path):
        """Nur Darks ausserhalb der Temp-Toleranz -> weiterhin kein Match
        (kein Falsch-Match durch den Filter-Fix)."""
        data_dir = tmp_path / "data"
        darks_dir = data_dir / "darks"
        darks_dir.mkdir(parents=True, exist_ok=True)
        dark_paths = self._write_headerless_darks(darks_dir, [10, 11])
        context = self._build_context(data_dir, "Duo-", dark_paths)

        agent = CalibrationAgent(tmp_path / "working", config=None)
        dark_paths_found, source = agent._find_darks_for_group(
            context, (30.0, 40, "Duo-"), 34.0
        )

        assert source == "none"
        assert dark_paths_found == []


# ═══════════════════════════════════════════════════════════════════
# Bug 2026-08-09 (stella) — None-Safety in get_for_calibration()
# ═══════════════════════════════════════════════════════════════════


class TestHeaderlessDarkNoneSafety:
    """None-Safety: header-loser Dark + unparsbarer Dateiname (exptime/gain
    None) darf NICHT crashen (TypeError bei abs(None - 30.0)) — Frame wird
    uebersprungen; wenn kein Dark matcht -> no_dark_match, Gruppe bleibt
    unkalibriert (T3-Prinzip)."""

    @staticmethod
    def _write_empty_header_fits(path: Path, value: float) -> None:
        """FITS ohne Header-Cards (nur SIMPLE/BITPIX/NAXIS/...)."""
        _write_fits(path, np.full((64, 64), value, dtype=np.float32))

    def test_get_for_calibration_skips_none_param_frames(self):
        """Kern: Frames mit exptime/gain None werden uebersprungen (kein
        TypeError), brauchbare Frames matchen weiterhin."""
        good = FrameInfo(
            path=Path("dark_good.fits"),
            frame_type=FrameType.DARK,
            header=FitsHeader(exptime=30.0, gain=40, ccd_temp=34.0),
            index=0,
        )
        bad = FrameInfo(
            path=Path("dark_bad.fits"),
            frame_type=FrameType.DARK,
            header=FitsHeader(exptime=None, gain=None),
            index=1,
        )
        dark_set = FrameSet(frame_type=FrameType.DARK, frames=[bad, good])

        matched = dark_set.get_for_calibration(30.0, 40, None, 34.0)

        assert [f.path.name for f in matched] == ["dark_good.fits"]

    def test_find_darks_for_group_headerless_dark_no_crash(self, tmp_path: Path):
        """C20-Repro: header-loser Dark (unparsbarer Dateiname) -> kein
        Crash, kein Match (source 'none'), Gruppe bleibt unkalibriert (T3)."""
        data_dir = tmp_path / "data"
        darks_dir = data_dir / "darks"
        darks_dir.mkdir(parents=True, exist_ok=True)
        dark_path = darks_dir / "dark_unparsable.fits"
        self._write_empty_header_fits(dark_path, DARK_VALUE)

        # QF-03-Kontext baut den Dark ueber parse_fits_header -> Header
        # existiert, aber exptime/gain None (der Crash-Pfad).
        context = TestQF03HeaderlessDarks._build_context(data_dir, "Duo-", [dark_path])

        agent = CalibrationAgent(tmp_path / "working", config=None)
        dark_paths_found, source = agent._find_darks_for_group(
            context, (30.0, 40, "Duo-"), 34.0
        )

        assert source == "none"
        assert dark_paths_found == []

    def test_compact_dark_filename_now_matches(self, tmp_path: Path):
        """Ebene 2: Dark_30s40.fits wird jetzt geparst (exptime 30, gain 40)
        -> lokaler header-loser Dark matcht (source 'local')."""
        data_dir = tmp_path / "data"
        darks_dir = data_dir / "darks"
        darks_dir.mkdir(parents=True, exist_ok=True)
        dark_path = darks_dir / "Dark_30s40.fits"
        self._write_empty_header_fits(dark_path, DARK_VALUE)

        context = TestQF03HeaderlessDarks._build_context(data_dir, "Duo-", [dark_path])

        agent = CalibrationAgent(tmp_path / "working", config=None)
        dark_paths_found, source = agent._find_darks_for_group(
            context, (30.0, 40, "Duo-"), 34.0
        )

        assert source == "local"
        assert len(dark_paths_found) == 1
