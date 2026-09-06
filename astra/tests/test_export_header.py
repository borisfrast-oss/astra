"""F-META-1.2 (stella Punkt 4 / Befund 7 + Punkt 5): Header-Metadaten im Final-Export.

Abgedeckt:
- Light-Header-Keys (OBJECT..EQMODE) aus dem ersten Light-Frame werden in den
  Final-FITS-Header uebernommen (Siril/Plate-Solving).
- Approximatives TAN-WCS (CRVAL/CRPIX/CDELT/CTYPE/CUNIT) aus Zielkoordinaten +
  Pixel-Skala, wenn PCC-Schritt mit ra/dec/pixel_scale verfuegbar.
- F-META-1.2 (stella Punkt 5): XPIXSZ/YPIXSZ werden auf die EFFEKTIVE
  Pixelgroesse gesetzt (PCC-Skala -> pixel_scale x FOCALLEN / 206.265;
  sonst nativer Wert x stack_scale_factor, Default 2.0), damit Siril die
  korrekte ~7.98 arcsec/px ableitet statt 3.99 aus dem nativen XPIXSZ.
  DWARF mini: nativ 2MP/2.9µm, Stack 2x Superpixel-Debayer -> 5.8 µm.
  WCS/CDELT bleiben unveraendert.
- Best effort: ohne Light-Header/PCC bleibt der Header unveraendert, keine
  Fehler; Fehler beim Schreiben -> Warning, nie Abbruch.
- Multi-Group-Merge-Export (merged/) wird analog angereichert.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from astropy.io import fits

# ── Ensure src + tests on the path ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_multi_group import create_test_fits, make_sample_context  # noqa: E402

import astro_process.core.export as export_mod  # noqa: E402
from astro_process.agents.merge_agent import MergeResult  # noqa: E402
from astro_process.agents.processing_agent import ProcessingAgent  # noqa: E402
from astro_process.core.export import (  # noqa: E402
    annotate_export_header,
    export,
)
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
)
from astro_process.config.models import (  # noqa: E402
    MultiGroupConfig,
    PipelineStep,
    ProcessingParams,
)
from astro_process.models.core import (  # noqa: E402
    EquipmentInfo,
    FitsHeader,
    FrameInfo,
    FrameSet,
    FrameType,
    ObservationContext,
    ObservationTarget,
)


class _LogRecorder:
    """Minimaler structlog-Recorder (Muster test_plugins_processing)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def info(self, name, **kwargs):
        self.records.append((name, kwargs))

    def warning(self, name, **kwargs):
        self.records.append((name, kwargs))

    def events_named(self, name: str) -> list[tuple[str, dict]]:
        return [(n, k) for n, k in self.records if n == name]


# DWARF-mini-artiger Light-Header (Befund 7: OBJECT..EQMODE vorhanden;
# nativ 1920x1080 ~2MP, Pixel 2.9 µm, Tele 150 mm).
LIGHT_RAW_CARDS = {
    "OBJECT": "M 3",
    "RA": 205.5484,
    "DEC": 28.37728,
    "TELESCOP": "DWARF mini",
    "INSTRUME": "DWARF mini",
    "CAMERA": "DWARF mini",
    "FOCALLEN": 150.0,
    "XPIXSZ": 2.9,
    "YPIXSZ": 2.9,
    "EXPTIME": 15.0,
    "GAIN": 60,
    "FILTER": "Duo-Band",
    "DATE-OBS": "2026-08-05T09:19:19",
    "DET-TEMP": 5.0,
    "EQMODE": 1,
}

# PCC-Skala = 206.265 x 5.8 / 150 = 7.97558 arcsec/px (Stack: nativer
# 2.9 µm x stack_scale_factor 2.0 = 5.8 µm). Siril misst empirisch
# ~7.985 arcsec/px (fitted Brennweite 149.82 mm) — stella 2026-08-05.
WCS_INFO = {
    "ra": 205.5484,
    "dec": 28.37728,
    "pixel_scale_arcsec": 7.97558,
}


def _make_context(
    tmp_path: Path,
    raw_cards: dict | None = None,
    target_ra: float | None = 205.5484,
    target_dec: float | None = 28.37728,
) -> ObservationContext:
    frames = []
    if raw_cards is not None:
        frames = [
            FrameInfo(
                path=Path("light_0000.fits"),
                frame_type=FrameType.LIGHT,
                header=FitsHeader(raw_cards=raw_cards),
                index=0,
            )
        ]
    return ObservationContext(
        target=ObservationTarget(name="TestTarget", ra=target_ra, dec=target_dec),
        frames={FrameType.LIGHT: FrameSet(frame_type=FrameType.LIGHT, frames=frames)},
        equipment=EquipmentInfo(telescope="DWARF mini", focal_length_mm=150.0, pixel_size_um=2.9),
        source_path=tmp_path,
    )


def _load_header(path: Path) -> fits.Header:
    with fits.open(path) as hdul:
        return hdul[0].header.copy()


# ═══════════════════════════════════════════════════════════════════
# F-META-1.2-A: annotate_export_header (Unit)
# ═══════════════════════════════════════════════════════════════════


class TestAnnotateExportHeader:
    def test_light_keys_and_wcs_written(self, tmp_path: Path):
        """Light-Header-Keys (inkl. EQMODE) + approximatives TAN-WCS werden
        in den Header geschrieben (Kriterium Befund 7). XPIXSZ/YPIXSZ sind
        auf die EFFEKTIVE Pixelgroesse gesetzt (stella Punkt 5: PCC-Skala
        7.97558 arcsec/px x FOCALLEN 150 / 206.265 = 5.8 µm statt 2.9)."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards=LIGHT_RAW_CARDS)

        annotate_export_header(img, ctx, wcs=WCS_INFO)

        header = _load_header(img)
        assert header["OBJECT"] == "M 3"
        assert header["TELESCOP"] == "DWARF mini"
        assert header["FOCALLEN"] == 150.0
        assert header["XPIXSZ"] == pytest.approx(5.8, abs=1e-9)
        assert header["YPIXSZ"] == pytest.approx(5.8, abs=1e-9)
        assert header["EQMODE"] == 1
        assert header["DATE-OBS"] == "2026-08-05T09:19:19"

        assert header["CRVAL1"] == pytest.approx(205.5484)
        assert header["CRVAL2"] == pytest.approx(28.37728)
        # Bildzentrum (1-basiert): NAXIS1/NAXIS2 = 100 -> CRPIX = 50.5
        assert header["CRPIX1"] == pytest.approx(50.5)
        assert header["CRPIX2"] == pytest.approx(50.5)
        assert header["CDELT1"] == pytest.approx(-WCS_INFO["pixel_scale_arcsec"] / 3600.0)
        assert header["CDELT2"] == pytest.approx(WCS_INFO["pixel_scale_arcsec"] / 3600.0)
        assert header["CTYPE1"] == "RA---TAN"
        assert header["CTYPE2"] == "DEC--TAN"
        assert header["CUNIT1"] == "deg"
        assert header["CUNIT2"] == "deg"

    def test_only_present_keys_written_without_wcs(self, tmp_path: Path):
        """Fehlende Keys werden nicht erfunden; ohne WCS keine CRVAL/CDELT."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(
            tmp_path,
            raw_cards={"OBJECT": "M 3", "EQMODE": 1},
        )

        annotate_export_header(img, ctx, wcs=None)

        header = _load_header(img)
        assert header["OBJECT"] == "M 3"
        assert header["EQMODE"] == 1
        assert "TELESCOP" not in header
        assert "CRVAL1" not in header
        assert "CTYPE1" not in header

    def test_best_effort_without_lights_and_wcs(self, tmp_path: Path):
        """Kein Light-Header + kein WCS -> Header unveraendert, kein Event."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        before = _load_header(img)
        ctx = _make_context(tmp_path, raw_cards=None)

        annotate_export_header(img, ctx, wcs=None)

        after = _load_header(img)
        # Card-Set-Vergleich ist bei astropy unzuverlaessig (Card.__hash__/
        # __eq__ inkonsistent) -> deterministischer Text-Vergleich.
        assert after.tostring() == before.tostring()

    def test_wcs_skipped_when_partial_wcs_data(self, tmp_path: Path):
        """Unvollstaendige WCS-Daten (ra fehlt / scale=0) -> keine CRVAL."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards={"OBJECT": "M 3"})

        annotate_export_header(
            img, ctx, wcs={"ra": None, "dec": 28.0, "pixel_scale_arcsec": 15.0}
        )

        header = _load_header(img)
        assert header["OBJECT"] == "M 3"
        assert "CRVAL1" not in header

    # ── F-META-1.2 (stella Punkt 5): effektive Pixelgroesse ──────────

    def test_pixel_scale_effective_from_pcc(self, tmp_path: Path):
        """PCC-Skala vorhanden + FOCALLEN -> XPIXSZ = pixel_scale x FOCALLEN /
        206.265 (5.8 µm bei 7.97558 arcsec/px und FOCALLEN 150). Siril
        leitet daraus exakt die gemessene Skala ab."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards=LIGHT_RAW_CARDS)

        annotate_export_header(img, ctx, wcs=WCS_INFO)

        header = _load_header(img)
        expected = WCS_INFO["pixel_scale_arcsec"] * 150.0 / 206.265
        assert header["XPIXSZ"] == pytest.approx(expected, abs=1e-9)
        assert header["YPIXSZ"] == pytest.approx(expected, abs=1e-9)
        # Konsistenz mit dem Fallback (2.9 x 2.0): beide Wege -> 5.8 µm
        assert expected == pytest.approx(2.9 * 2.0, abs=1e-6)
        # Siril-Rueckrechnung: 206.265 x 5.8 / 150 = 7.97558 arcsec/px
        # (Siril misst empirisch ~7.985 arcsec/px, stella 2026-08-05)
        assert 206.265 * header["XPIXSZ"] / 150.0 == pytest.approx(
            WCS_INFO["pixel_scale_arcsec"], abs=1e-9
        )
        assert 206.265 * header["XPIXSZ"] / 150.0 == pytest.approx(7.985, abs=0.01)

    def test_pixel_scale_fallback_without_pcc(self, tmp_path: Path):
        """Kein PCC (nebula_standard/M27-Fall) -> XPIXSZ = nativer Wert x
        stack_scale_factor (Default 2.0) = 2.9 x 2.0 = 5.8 µm."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards=LIGHT_RAW_CARDS)

        annotate_export_header(img, ctx, wcs=None)

        header = _load_header(img)
        assert header["XPIXSZ"] == pytest.approx(2.9 * 2.0, abs=1e-9)
        assert header["YPIXSZ"] == pytest.approx(2.9 * 2.0, abs=1e-9)
        # Siril: 206.265 x 5.8 / 150 = 7.98 arcsec/px (Kriterium; stella
        # misst empirisch ~7.985 arcsec/px)
        assert 206.265 * header["XPIXSZ"] / 150.0 == pytest.approx(7.985, abs=0.01)
        # Kein WCS -> keine CDELT-Keys (Siril rechnet aus XPIXSZ/FOCALLEN)
        assert "CDELT1" not in header
        assert "CTYPE1" not in header

    def test_pixel_scale_fallback_custom_stack_scale_factor(self, tmp_path: Path):
        """Konfigurierter stack_scale_factor (z.B. 3.0) ueberschreibt den
        Default 2.0 im Fallback-Pfad (Config/Preset-Precedence)."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards=LIGHT_RAW_CARDS)

        annotate_export_header(img, ctx, wcs=None, stack_scale_factor=3.0)

        header = _load_header(img)
        assert header["XPIXSZ"] == pytest.approx(2.9 * 3.0, abs=1e-9)
        assert header["YPIXSZ"] == pytest.approx(2.9 * 3.0, abs=1e-9)

    def test_pixel_scale_fallback_when_focal_missing_with_pcc(self, tmp_path: Path):
        """PCC-Skala vorhanden, aber FOCALLEN fehlt -> Fallback nativer Wert x
        Faktor (spec Punkt 5); WCS/CDELT werden trotzdem geschrieben."""
        raw = dict(LIGHT_RAW_CARDS)
        raw.pop("FOCALLEN")
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards=raw)

        annotate_export_header(img, ctx, wcs=WCS_INFO)

        header = _load_header(img)
        assert header["XPIXSZ"] == pytest.approx(2.9 * 2.0, abs=1e-9)
        # WCS bleibt unveraendert geschrieben (CDELT aus der PCC-Skala)
        assert header["CDELT2"] == pytest.approx(WCS_INFO["pixel_scale_arcsec"] / 3600.0)
        assert header["CTYPE1"] == "RA---TAN"

    def test_default_stack_scale_factor_pcc_and_fallback_consistent(
        self, tmp_path: Path
    ):
        """F-META-1.2 (stella Punkt 5): stack_scale_factor Default ist 2.0
        (DWARF mini, nativ 2MP/2.9µm, 2x Superpixel-Debayer) — PCC-Pfad
        (WCS-Skala) und Fallback-Pfad (ohne WCS) ergeben identisch
        XPIXSZ/YPIXSZ = 2.9 x 2.0 = 5.8 µm -> Siril-Skala ~7.98 arcsec/px."""
        from astro_process.config.loader import resolve_registration
        from astro_process.config.models import (
            AppConfig,
            PipelinePreset,
            PipelineStep,
            RegistrationConfig,
        )

        # Default 2.0 im Config-Modell und in der verankerten
        # Registrations-Config (resolve_registration ohne Override).
        assert RegistrationConfig().stack_scale_factor == 2.0
        preset = PipelinePreset(
            name="test",
            target_types=["star"],
            steps=[PipelineStep(name="register_frames")],
        )
        assert resolve_registration(AppConfig(), preset).stack_scale_factor == 2.0

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        ctx = _make_context(tmp_path, raw_cards=LIGHT_RAW_CARDS)

        # PCC-Pfad: 7.97558 x 150 / 206.265 = 5.8 µm (aus der WCS-Skala)
        img_pcc = create_test_fits(tmp_path / "stack_pcc.fits", rng_seed=1)
        annotate_export_header(img_pcc, ctx, wcs=WCS_INFO)

        # Fallback-Pfad: 2.9 x Default 2.0 = 5.8 µm (kein PCC)
        img_fb = create_test_fits(tmp_path / "stack_fb.fits", rng_seed=1)
        annotate_export_header(img_fb, ctx, wcs=None)

        header_pcc = _load_header(img_pcc)
        header_fb = _load_header(img_fb)
        assert header_pcc["XPIXSZ"] == pytest.approx(5.8, abs=1e-9)
        assert header_fb["XPIXSZ"] == pytest.approx(5.8, abs=1e-9)
        # Beide Wege identisch -> kein zirkulaerer 4.0-Faktor mehr
        assert header_pcc["XPIXSZ"] == pytest.approx(header_fb["XPIXSZ"], abs=1e-9)
        assert 206.265 * header_fb["XPIXSZ"] / 150.0 == pytest.approx(7.985, abs=0.01)

    def test_pixel_scale_not_adjusted_without_equipment_keys(self, tmp_path: Path):
        """Ohne FOCALLEN und ohne native XPIXSZ/YPIXSZ -> keine Aenderung
        (best effort, keine Fehler, kein XPIXSZ erfunden)."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        img = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards={"OBJECT": "M 3"})

        annotate_export_header(img, ctx, wcs=None)

        header = _load_header(img)
        assert header["OBJECT"] == "M 3"
        assert "XPIXSZ" not in header

    def test_best_effort_on_corrupt_file_logs_warning(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """Fehler beim FITS-Schreiben -> Warning `export.header_annotate_failed`,
        keine Ausnahme (best effort)."""
        rec = _LogRecorder()
        monkeypatch.setattr(export_mod, "logger", rec)
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        corrupt = tmp_path / "corrupt.fits"
        corrupt.write_text("not a fits file")
        ctx = _make_context(tmp_path, raw_cards=LIGHT_RAW_CARDS)

        annotate_export_header(corrupt, ctx, wcs=WCS_INFO)

        failed = rec.events_named("export.header_annotate_failed")
        assert len(failed) == 1
        assert "error" in failed[0][1]


# ═══════════════════════════════════════════════════════════════════
# F-META-1.2-B: export (Single-Group, End-to-End)
# ═══════════════════════════════════════════════════════════════════


class TestExportIntegration:
    def test_export_annotated_with_context_and_wcs(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """export mit context+wcs -> Final-FITS enthaelt Keys + WCS,
        Log `export.header_annotated` mit keys_count>0 und wcs=True."""
        rec = _LogRecorder()
        monkeypatch.setattr(export_mod, "logger", rec)
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        src = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards=LIGHT_RAW_CARDS)

        exports = export(src, "TestTarget", context=ctx, wcs=WCS_INFO,
                         working_dir=agent.working_dir)

        fits_out = tmp_path / "out" / "TestTarget_final.fits"
        assert fits_out in exports
        header = _load_header(fits_out)
        assert header["OBJECT"] == "M 3"
        assert header["CRVAL1"] == pytest.approx(205.5484)
        assert header["CTYPE1"] == "RA---TAN"
        # F-META-1.2 (stella Punkt 5): effektive Pixelgroesse aus der
        # PCC-Skala -> 7.97558 x 150 / 206.265 = 5.8 µm (Default-Faktor 2.0
        # aus der verankerten Registrations-Config, wcs=None -> Fallback
        # nativer 2.9 x 2.0 waere identisch 5.8).
        assert header["XPIXSZ"] == pytest.approx(5.8, abs=1e-6)
        assert header["YPIXSZ"] == pytest.approx(5.8, abs=1e-6)

        annotated = rec.events_named("export.header_annotated")
        assert len(annotated) == 1
        assert annotated[0][1]["keys_count"] > 0
        assert annotated[0][1]["wcs"] is True
        assert annotated[0][1]["pixel_size_adjusted"] is True
        assert annotated[0][1]["pixel_size_um"] == pytest.approx(5.8, abs=1e-3)

    def test_export_without_context_unchanged(self, tmp_path: Path, monkeypatch):
        """export ohne context (bestehende Aufruf-Signatur) -> Header bleibt
        unveraendert, kein `export.header_annotated`-Event (kein Verhaltens-
        bruch fuer bestehende Laeufe)."""
        rec = _LogRecorder()
        monkeypatch.setattr(export_mod, "logger", rec)
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        src = create_test_fits(tmp_path / "stack.fits", rng_seed=1)

        exports = export(src, "TestTarget", working_dir=agent.working_dir)

        fits_out = tmp_path / "out" / "TestTarget_final.fits"
        assert fits_out in exports
        header = _load_header(fits_out)
        # V1.6-1: create_test_fits now includes OBJECT; export preserves it
        assert "OBJECT" in header
        assert "CRVAL1" not in header
        assert rec.events_named("export.header_annotated") == []

    def test_export_with_context_but_no_data_unchanged(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """export mit context ohne Light-Frames und ohne wcs -> Header
        unveraendert, keine Fehler (best effort, AC-F-META)."""
        rec = _LogRecorder()
        monkeypatch.setattr(export_mod, "logger", rec)
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        src = create_test_fits(tmp_path / "stack.fits", rng_seed=1)
        ctx = _make_context(tmp_path, raw_cards=None)

        exports = export(src, "TestTarget", context=ctx, wcs=None,
                         working_dir=agent.working_dir)

        fits_out = tmp_path / "out" / "TestTarget_final.fits"
        assert fits_out in exports
        header = _load_header(fits_out)
        # V1.6-1: create_test_fits now includes OBJECT; export preserves it
        assert "OBJECT" in header
        assert "CRVAL1" not in header


# ═══════════════════════════════════════════════════════════════════
# F-META-1.2-C: Multi-Group-Merge-Export (merged/) analog
# ═══════════════════════════════════════════════════════════════════


class TestMultiGroupMergeExport:
    def test_merge_export_annotated(self, tmp_path: Path, monkeypatch):
        """process_multi_group reichert den Merge-Export (merged/) analog an:
        Light-Header-Keys + WCS im finalen merged-FITS."""
        rec = _LogRecorder()
        monkeypatch.setattr(export_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = make_sample_context(tmp_path / "data", group_count=2, frames_per_group=3)
        # Erster Light-Frame traegt den DWARF-mini-artigen Header (Befund 7)
        context.get_lights().frames[0].header.raw_cards = dict(LIGHT_RAW_CARDS)
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        # DEF-014-Fix: photometric_color_calibration-Step noetig damit PCC laeuft
        pipeline.steps = [
            PipelineStep(name="register_frames"),
            PipelineStep(name="stack_frames"),
            PipelineStep(name="photometric_color_calibration"),
            PipelineStep(name="export"),
        ]

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

        assert result.stacked is not None
        # V1.6 (PCC auf MERGED Stack): process_multi_group biegt merged_path
        # auf out/merged/pcc_applied.fits um (Kopie + PCC); die Header-
        # Annotierung (F-META-1.2) laeuft auf diesem FINALEN Artefakt, nicht
        # auf dem MergeResult-merged.fits (Intermediat).
        annotated_fits = tmp_path / "out" / "merged" / "pcc_applied.fits"
        assert annotated_fits.exists()
        header = _load_header(annotated_fits)
        assert header["OBJECT"] == "M 3"
        assert header["EQMODE"] == 1
        assert header["CRVAL1"] == pytest.approx(180.0)  # make_sample_context ra
        assert header["CRVAL2"] == pytest.approx(30.0)
        assert header["CTYPE1"] == "RA---TAN"

        # Log: annotiert im Merge-Pfad (finale Datei)
        annotated = rec.events_named("export.header_annotated")
        assert len(annotated) >= 1
        assert str(annotated_fits) in annotated[0][1]["path"]

    def test_merge_export_unchanged_without_data(self, tmp_path: Path, monkeypatch):
        """Multi-Group ohne Light-Header/ra/dec -> merged-FITS bleibt
        unveraendert (best effort)."""
        rec = _LogRecorder()
        monkeypatch.setattr(export_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = make_sample_context(tmp_path / "data", group_count=2, frames_per_group=3)
        # Keine raw_cards (make_sample_context setzt nur exptime/gain/filter)
        # und ra/dec -> None, damit kein WCS gebaut wird.
        context.target.ra = None
        context.target.dec = None
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
            agent.process_multi_group(
                context,
                cal_result,
                deb_result,
                pipeline,
                multi_group_config=MultiGroupConfig(),
                merge_agent=merge_agent,
            )

        header = _load_header(merged_fits)
        # V1.6-1: create_test_fits now includes OBJECT; export preserves it
        assert "OBJECT" in header
        assert "CRVAL1" not in header
        assert rec.events_named("export.header_annotated") == []
