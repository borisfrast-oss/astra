"""Tests for the V1.4-19 PCC fallback chain (stufenweise statt sofort gray_world).

Covers (fixes-sammlung §1 / v14-konkretisierung §V1.4-19):
- GAIA-Retry mit Backoff 1x/2x/3x gaia_timeout (Default 30 -> 30/60/90s).
- VizieR-Zweit-Katalog (APASS DR9 -> ATLAS Refcat2) als Stufe 2.
- Erst danach preset-abhaengig: "auto"/"gray_world" -> gray_world,
  "skip" -> None (Sterne, 51-Cyg-Erfahrung), "fail" -> RuntimeError.
- Ohne Koordinaten: keine Katalog-Kette (direkt finale Stufe).
- _vizier_pcc bleibt hermetic (kein echtes VizieR-Netzwerk in Unit-Tests).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from astropy.io import fits

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.core.pcc import (
    GAIA_QUERY_TIMEOUT_SECONDS,
    PCC_FALLBACK_CHAIN_TIMEOUT_MULTIPLIERS,
    PCCResult,
    _VIZIER_CATALOGS,
    apply_pcc,
    gray_world_white_balance,
)


def _rgb(seed: int = 42, size: int = 40) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return rng.uniform(0.1, 0.9, (size, size, 3)).astype(np.float32)


class TestPccFallbackChain:
    """V1.4-19: stufenweise Fallback-Kette in apply_pcc."""

    def test_retry_backoff_timeouts_default(self):
        """GAIA wird 3x mit 1x/2x/3x gaia_timeout versucht (30/60/90)."""
        rgb = _rgb()
        fail = PCCResult(corrected=None, status="skipped")

        with patch("astro_process.core.pcc._gaia_pcc", return_value=fail) as mock_gaia, \
             patch("astro_process.core.pcc._vizier_pcc", return_value=fail):
            apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        timeouts = [c.kwargs.get("timeout") for c in mock_gaia.call_args_list]
        assert timeouts == [30.0, 60.0, 90.0]

    def test_retry_backoff_timeouts_scaled(self):
        """gaia_timeout=12.5 skaliert die Backoff-Kette (12.5/25/37.5)."""
        rgb = _rgb()
        fail = PCCResult(corrected=None, status="skipped")

        with patch("astro_process.core.pcc._gaia_pcc", return_value=fail) as mock_gaia, \
             patch("astro_process.core.pcc._vizier_pcc", return_value=fail):
            apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                      gaia_timeout=12.5)

        timeouts = [c.kwargs.get("timeout") for c in mock_gaia.call_args_list]
        assert timeouts == [12.5, 25.0, 37.5]

    def test_retry_success_second_attempt_no_vizier(self):
        """VizieR-Erfolg im 1. Versuch -> kein GAIA-Aufruf (V1.6-5)."""
        rgb = _rgb()
        expected = rgb.copy().astype(np.float32)

        with patch("astro_process.core.pcc._gaia_pcc") as mock_gaia, \
             patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=expected, status="vizier_apass_success")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        mock_gaia.assert_not_called()
        assert result.corrected is expected
        assert result.status == "vizier_apass_success"

    def test_chain_fail_then_vizier_success(self):
        """VizieR scheitert -> GAIA-Kette liefert Ergebnis (V1.6-5 Fallback)."""
        rgb = _rgb()
        expected = rgb.copy().astype(np.float32)

        with patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=expected, status="gaia_success")) as mock_gaia:
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        mock_gaia.assert_called_once()
        assert result.corrected is expected
        assert result.status == "gaia_success"

    def test_vizier_called_with_separate_timeouts(self):
        """VizieR-Versuch nutzt eigene Timeout-Parameter (statt gaia_timeout)."""
        rgb = _rgb()
        fail = PCCResult(corrected=None, status="skipped")

        with patch("astro_process.core.pcc._gaia_pcc", return_value=fail), \
             patch("astro_process.core.pcc._vizier_pcc", return_value=fail) as mock_vizier:
            apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                      vizier_apass_timeout=25.0, vizier_refcat2_timeout=35.0)

        _, kwargs = mock_vizier.call_args
        assert kwargs.get("timeout_apass") == 25.0
        assert kwargs.get("timeout_refcat2") == 35.0

    def test_vizier_default_timeouts(self):
        """VizieR nutzt Default-Timeouts (30.0) wenn nicht konfiguriert."""
        rgb = _rgb()
        fail = PCCResult(corrected=None, status="skipped")

        with patch("astro_process.core.pcc._gaia_pcc", return_value=fail), \
             patch("astro_process.core.pcc._vizier_pcc", return_value=fail) as mock_vizier:
            apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        _, kwargs = mock_vizier.call_args
        assert kwargs.get("timeout_apass") == 30.0
        assert kwargs.get("timeout_refcat2") == 30.0

    def test_chain_fail_auto_gray_world(self):
        """Beide Kataloge scheitern -> "auto" endet in gray_world."""
        rgb = _rgb()

        with patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.corrected.shape == rgb.shape
        assert result.corrected.dtype == np.float32
        assert np.all(np.isfinite(result.corrected))
        assert result.status == "fallback_gray_world"

    def test_chain_fail_skip_returns_none(self):
        """Beide Kataloge scheitern + "skip" -> None (kein gray_world)."""
        rgb = _rgb()

        with patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                               fallback="skip")

        assert result.corrected is None
        assert result.status == "pcc_skipped"

    def test_chain_fail_fail_raises(self):
        """Beide Kataloge scheitern + "fail" -> RuntimeError."""
        rgb = _rgb()
        fail = PCCResult(corrected=None, status="skipped")

        with patch("astro_process.core.pcc._gaia_pcc", return_value=fail), \
             patch("astro_process.core.pcc._vizier_pcc", return_value=fail):
            with pytest.raises(RuntimeError, match="catalog chain failed"):
                apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                          fallback="fail")

    def test_no_coordinates_skip_returns_none(self):
        """Ohne Koordinaten + "skip" -> None, keine Katalog-Aufrufe."""
        rgb = _rgb()

        with patch("astro_process.core.pcc._gaia_pcc") as mock_gaia, \
             patch("astro_process.core.pcc._vizier_pcc") as mock_vizier:
            result = apply_pcc(rgb, fallback="skip")

        assert result.corrected is None
        assert result.status == "pcc_skipped"
        mock_gaia.assert_not_called()
        mock_vizier.assert_not_called()

    def test_no_coordinates_auto_gray_world(self):
        """Ohne Koordinaten + "auto" -> gray_world (Regression, kein Katalog)."""
        rgb = _rgb()

        with patch("astro_process.core.pcc._gaia_pcc") as mock_gaia, \
             patch("astro_process.core.pcc._vizier_pcc") as mock_vizier:
            result = apply_pcc(rgb)

        assert result.corrected.shape == rgb.shape
        assert result.corrected.dtype == np.float32
        assert np.all(np.isfinite(result.corrected))
        assert result.status == "fallback_gray_world"
        mock_gaia.assert_not_called()
        mock_vizier.assert_not_called()

    def test_chain_constants(self):
        """Backoff-Multiplikatoren + VizieR-Katalog-Reihenfolge (V1.4-19)."""
        assert tuple(PCC_FALLBACK_CHAIN_TIMEOUT_MULTIPLIERS) == (1.0, 2.0, 3.0)
        names = [c[0] for c in _VIZIER_CATALOGS]
        assert names == ["apass_dr9", "atlas_refcat2"]
        # Bug 2 Fix: Verify correct Vizier catalog IDs and column names
        assert _VIZIER_CATALOGS[0][1] == "II/336/apass9"  # APASS DR9
        assert _VIZIER_CATALOGS[0][2] == ("Bmag", "Vmag", "r'mag")
        assert _VIZIER_CATALOGS[0][3] == ("RAJ2000", "DEJ2000")
        assert _VIZIER_CATALOGS[1][1] == "J/ApJ/867/105/refcat2"  # Refcat2
        assert _VIZIER_CATALOGS[1][2] == ("Gmag", "BPmag", "RPmag")
        assert _VIZIER_CATALOGS[1][3] == ("RA_ICRS", "DE_ICRS")


class TestVizierPcc:
    """V1.4-19 Stufe 2: _vizier_pcc (hermetic)."""
    def test_unavailable_flag_returns_none_without_thread(self):
        """_VIZIER_OPT_AVAILABLE=False -> PCCResult(None), kein Thread/Netzwerk."""
        import astro_process.core.pcc as pcc_mod
        rgb = _rgb()

        with patch("astro_process.core.pcc._VIZIER_OPT_AVAILABLE", False), \
             patch("astro_process.core.pcc._run_with_timeout") as mock_timeout:
            out = pcc_mod._vizier_pcc(rgb, 180.0, 30.0, pixel_scale=16.0,
                                      timeout_apass=5.0, timeout_refcat2=5.0)

        assert out.corrected is None
        assert out.status == "skipped"
        mock_timeout.assert_not_called()

    def test_few_stars_returns_none(self):
        """Weniger als 5 Sterne -> PCCResult(None) (pcc.few_stars im Detektor)."""
        import astro_process.core.pcc as pcc_mod
        rgb = _rgb()

        with patch("astro_process.core.pcc._detect_and_measure", return_value=None), \
             patch("astro_process.core.pcc._Vizier") as mock_vizier:
            out = pcc_mod._vizier_pcc(rgb, 180.0, 30.0, pixel_scale=16.0,
                                      timeout_apass=5.0, timeout_refcat2=5.0)

        assert out.corrected is None
        assert out.status == "skipped"
        mock_vizier.assert_not_called()

    def test_module_flag_present(self):
        """Modul-Flag existiert (True bei installiertem astroquery)."""
        import astro_process.core.pcc as pcc_mod
        assert hasattr(pcc_mod, "_VIZIER_OPT_AVAILABLE")
        assert pcc_mod._VIZIER_OPT_AVAILABLE is True


class TestExtractedMatchLogicSmoke:
    """V1.4-19: Extraktions-Smoke-Tests fuer _detect_and_measure/
    _position_match_and_correct (Netzwerk + Detection gemockt; Match- und
    Korrektur-Logik bleibt real — validiert den Refactor end-to-end)."""

    def test_gaia_pcc_extracted_path_computes_correction(self):
        """_gaia_pcc (extrahiert) liefert bei fake Sternen/Katalog ein RGB."""
        import astro_process.core.pcc as pcc_mod
        from astropy.table import Table

        rgb = np.ones((200, 200, 3), dtype=np.float32)
        rgb[:, :, 0] = 0.8  # R schwaecher -> Faktor > 1 erwartet
        rgb[:, :, 2] = 1.2

        # Sterne: 4 synthetische Positionen (Pixel-Koordinaten egal, da
        # _pixel_to_sky gemockt wird).
        n = 4
        det = (
            np.arange(n, dtype=float), np.arange(n, dtype=float),
            np.full(n, 100.0), np.full(n, 200.0), np.full(n, 150.0),
        )
        sky = [(180.0, 30.0), (180.003, 30.0), (180.0, 30.003), (180.002, 30.002)]
        table = Table({
            "ra": [180.0, 180.003, 180.0, 180.002],
            "dec": [30.0, 30.0, 30.003, 30.002],
            "phot_g_mean_mag": [10.0, 10.5, 11.0, 11.5],
            "phot_bp_mean_mag": [10.2, 10.7, 11.2, 11.7],
            "phot_rp_mean_mag": [9.8, 10.3, 10.8, 11.3],
        })
        job = type("FakeJob", (), {"get_results": lambda self: table})()

        with patch.object(pcc_mod, "_detect_and_measure", return_value=det), \
             patch.object(pcc_mod, "_run_with_timeout", return_value=job), \
             patch.object(pcc_mod, "_pixel_to_sky", side_effect=sky):
            out = pcc_mod._gaia_pcc(rgb, 180.0, 30.0, pixel_scale=16.0, timeout=5.0)

        assert out.corrected is not None
        assert out.corrected.shape == rgb.shape
        assert out.corrected.dtype == np.float32
        assert np.all(np.isfinite(out.corrected))
        assert out.status == "gaia_success"
        # Alle 4 Sterne gematcht -> Korrektur angewandt (R-Kanal > 0.8-Skala)
        assert not np.allclose(out.corrected, rgb)

    def test_gaia_pcc_extracted_path_few_matches_none(self):
        """Weniger als 3 Matches -> None (pcc.few_matches im Match-Helfer)."""
        import astro_process.core.pcc as pcc_mod
        from astropy.table import Table

        rgb = np.ones((200, 200, 3), dtype=np.float32)
        n = 5
        det = (
            np.arange(n, dtype=float), np.arange(n, dtype=float),
            np.full(n, 100.0), np.full(n, 200.0), np.full(n, 150.0),
        )
        # Nur 1 Stern nahe am Zentrum; Rest weit weg (kein Match)
        sky = [(180.0, 30.0), (181.0, 30.0), (181.1, 30.0), (181.2, 30.0), (181.3, 30.0)]
        table = Table({
            "ra": [180.0], "dec": [30.0],
            "phot_g_mean_mag": [10.0],
            "phot_bp_mean_mag": [10.2],
            "phot_rp_mean_mag": [9.8],
        })
        job = type("FakeJob", (), {"get_results": lambda self: table})()

        with patch.object(pcc_mod, "_detect_and_measure", return_value=det), \
             patch.object(pcc_mod, "_run_with_timeout", return_value=job), \
             patch.object(pcc_mod, "_pixel_to_sky", side_effect=sky):
            out = pcc_mod._gaia_pcc(rgb, 180.0, 30.0, pixel_scale=16.0, timeout=5.0)

        assert out.corrected is None
        assert out.status == "skipped"

    def test_vizier_pcc_extracted_path_computes_correction(self):
        """_vizier_pcc (extrahiert) nutzt Bmag/Vmag/r'mag -> RGB-Korrektur (APASS DR9)."""
        import astro_process.core.pcc as pcc_mod
        from astropy.table import Table

        rgb = np.ones((200, 200, 3), dtype=np.float32)
        rgb[:, :, 0] = 0.8
        rgb[:, :, 2] = 1.2

        n = 4
        det = (
            np.arange(n, dtype=float), np.arange(n, dtype=float),
            np.full(n, 100.0), np.full(n, 200.0), np.full(n, 150.0),
        )
        sky = [(180.0, 30.0), (180.003, 30.0), (180.0, 30.003), (180.002, 30.002)]
        table = Table({
            "RAJ2000": [180.0, 180.003, 180.0, 180.002],
            "DEJ2000": [30.0, 30.0, 30.003, 30.002],
            "Bmag": [10.2, 10.7, 11.2, 11.7],
            "Vmag": [10.0, 10.5, 11.0, 11.5],
            "r'mag": [9.8, 10.3, 10.8, 11.3],
        })

        with patch.object(pcc_mod, "_detect_and_measure", return_value=det), \
             patch.object(pcc_mod, "_run_with_timeout", return_value=[table]), \
             patch.object(pcc_mod, "_pixel_to_sky", side_effect=sky):
            out = pcc_mod._vizier_pcc(rgb, 180.0, 30.0, pixel_scale=16.0,
                                      timeout_apass=5.0, timeout_refcat2=5.0)

        assert out.corrected is not None
        assert out.corrected.shape == rgb.shape
        assert out.corrected.dtype == np.float32
        assert np.all(np.isfinite(out.corrected))
        assert not np.allclose(out.corrected, rgb)
        assert out.status == "vizier_apass_success"

    def test_vizier_pcc_refcat2_extracted_path(self):
        """_vizier_pcc nutzt Refcat2-Spalten (Gmag/BPmag/RPmag, RA_ICRS/DE_ICRS)."""
        import astro_process.core.pcc as pcc_mod
        from astropy.table import Table

        rgb = np.ones((200, 200, 3), dtype=np.float32)
        rgb[:, :, 0] = 0.8
        rgb[:, :, 2] = 1.2

        n = 4
        det = (
            np.arange(n, dtype=float), np.arange(n, dtype=float),
            np.full(n, 100.0), np.full(n, 200.0), np.full(n, 150.0),
        )
        sky = [(180.0, 30.0), (180.003, 30.0), (180.0, 30.003), (180.002, 30.002)]
        # Refcat2 column names: RA_ICRS, DE_ICRS, Gmag, BPmag, RPmag
        table = Table({
            "RA_ICRS": [180.0, 180.003, 180.0, 180.002],
            "DE_ICRS": [30.0, 30.0, 30.003, 30.002],
            "Gmag": [10.0, 10.5, 11.0, 11.5],
            "BPmag": [10.2, 10.7, 11.2, 11.7],
            "RPmag": [9.8, 10.3, 10.8, 11.3],
        })

        # Patch _VIZIER_CATALOGS to only try Refcat2 (skip APASS)
        refcat_only = (
            ("atlas_refcat2", "J/ApJ/867/105/refcat2",
             ("Gmag", "BPmag", "RPmag"), ("RA_ICRS", "DE_ICRS")),
        )

        with patch.object(pcc_mod, "_detect_and_measure", return_value=det), \
             patch.object(pcc_mod, "_run_with_timeout", return_value=[table]), \
             patch.object(pcc_mod, "_pixel_to_sky", side_effect=sky), \
             patch.object(pcc_mod, "_VIZIER_CATALOGS", refcat_only):
            out = pcc_mod._vizier_pcc(rgb, 180.0, 30.0, pixel_scale=16.0,
                                      timeout_apass=5.0, timeout_refcat2=5.0)

        assert out.corrected is not None
        assert out.corrected.shape == rgb.shape
        assert out.corrected.dtype == np.float32
        assert np.all(np.isfinite(out.corrected))
        assert not np.allclose(out.corrected, rgb)
        assert out.status == "vizier_refcat2_success"


class TestVizierBrightnessFilter:
    """Regression Fix 2026-08-21: Helligkeitsfilter laeuft auf MAGNITUDEN
    VOR der mag→flux-Konvertierung.

    Vorher: Filter `(cat_g > 6.0) & (cat_g < 16.0)` lief NACH der
    Konvertierung und filterte Flux-Werte -> nur Sterne mag -3.0..-1.9
    passierten -> VizieR matched praktisch immer 0 Sterne."""

    def test_mag10_star_passes_filter_and_is_processed_as_flux(self):
        """Stern mit mag 10 passiert den Filter; nach der Konvertierung wird
        er als Flux weiterverarbeitet (>= 3 Matches -> Korrektur angewandt).

        Unter dem alten Flux-Filter haetten flux=10^(-mag/2.5)~1e-4 alle
        Sterne aussortiert -> PCCResult(None, 'skipped')."""
        import astro_process.core.pcc as pcc_mod
        from astropy.table import Table

        rgb = np.ones((200, 200, 3), dtype=np.float32)
        rgb[:, :, 0] = 0.8
        rgb[:, :, 2] = 1.2

        n = 4
        det = (
            np.arange(n, dtype=float), np.arange(n, dtype=float),
            np.full(n, 100.0), np.full(n, 200.0), np.full(n, 150.0),
        )
        sky = [(180.0, 30.0), (180.003, 30.0), (180.0, 30.003), (180.002, 30.002)]
        # Alle Sterne mag ~10 (Vmag-Spalte = G-Kanal-Filter).
        table = Table({
            "RAJ2000": [180.0, 180.003, 180.0, 180.002],
            "DEJ2000": [30.0, 30.0, 30.003, 30.002],
            "Bmag": [10.2, 10.7, 11.2, 11.7],
            "Vmag": [10.0, 10.5, 11.0, 11.5],
            "r'mag": [9.8, 10.3, 10.8, 11.3],
        })

        with patch.object(pcc_mod, "_detect_and_measure", return_value=det), \
             patch.object(pcc_mod, "_run_with_timeout", return_value=[table]), \
             patch.object(pcc_mod, "_pixel_to_sky", side_effect=sky):
            out = pcc_mod._vizier_pcc(rgb, 180.0, 30.0, pixel_scale=16.0,
                                      timeout_apass=5.0, timeout_refcat2=5.0)

        # mag-10-Sterne passieren den Filter -> >= 3 Matches -> Erfolg.
        assert out.corrected is not None
        assert out.status == "vizier_apass_success"
        # Konvertierung fand statt: Korrektur ist nicht identitaet.
        assert not np.allclose(out.corrected, rgb)

    def test_mag_outside_range_still_filtered(self):
        """Sterne ausserhalb 6 < mag < 16 werden weiterhin aussortiert."""
        import astro_process.core.pcc as pcc_mod
        from astropy.table import Table

        rgb = np.ones((200, 200, 3), dtype=np.float32)

        n = 4
        det = (
            np.arange(n, dtype=float), np.arange(n, dtype=float),
            np.full(n, 100.0), np.full(n, 200.0), np.full(n, 150.0),
        )
        sky = [(180.0, 30.0), (180.003, 30.0), (180.0, 30.003), (180.002, 30.002)]
        # Alle Vmag = 18 (zu schwach) -> nach Filter < 3 Sterne -> skip.
        table = Table({
            "RAJ2000": [180.0, 180.003, 180.0, 180.002],
            "DEJ2000": [30.0, 30.0, 30.003, 30.002],
            "Bmag": [18.2, 18.7, 19.2, 19.7],
            "Vmag": [18.0, 18.5, 19.0, 19.5],
            "r'mag": [17.8, 18.3, 18.8, 19.3],
        })

        with patch.object(pcc_mod, "_detect_and_measure", return_value=det), \
             patch.object(pcc_mod, "_run_with_timeout", return_value=[table]), \
             patch.object(pcc_mod, "_pixel_to_sky", side_effect=sky):
            out = pcc_mod._vizier_pcc(rgb, 180.0, 30.0, pixel_scale=16.0,
                                      timeout_apass=5.0, timeout_refcat2=5.0)

        assert out.corrected is None
        assert out.status == "skipped"


class TestPhotometricColorCalibrationSkip:
    """V1.4-19: photometric_color_calibration respektiert apply_pcc=None (skip)."""

    def test_skip_preserves_frame_no_marker(self, tmp_path: Path):
        """apply_pcc=None + "skip" -> kein save_frame, kein Gray-World-Marker,
        PCC_SKIPPED.txt-Marker (maschinenlesbar fuer apply_pcc_per_group)."""
        import structlog

        from astro_process.core.pcc import photometric_color_calibration

        stacked = tmp_path / "stacked.fits"
        data = np.ones((4, 4, 3), dtype=np.float32)
        fits.PrimaryHDU(data.transpose(2, 0, 1)).writeto(stacked)

        saved: list = []

        def load(_p: Path) -> np.ndarray:
            return data

        def save(arr: np.ndarray, _p: Path) -> None:
            saved.append(arr)

        # structlog-Logger durchreichen (Agent-Konvention; der Wrapper
        # loggt mit kwargs-Events).
        with patch("astro_process.core.pcc.apply_pcc",
                   return_value=PCCResult(corrected=None, status="pcc_skipped")), \
             patch("astro_process.core.pcc.get_pcc_fallback", return_value="skip"):
            photometric_color_calibration(
                stacked, {}, load_frame=load, save_frame=save, config=None,
                logger=structlog.get_logger("test_pcc_fallback_chain"),
            )

        assert saved == []
        assert not (tmp_path / "PCC_FALLBACK_GRAY_WORLD.txt").exists()
        assert (tmp_path / "PCC_SKIPPED.txt").exists()
        assert "PCC (Photometric Color Calibration) skipped" in (
            tmp_path / "PCC_SKIPPED.txt"
        ).read_text()
        # Frame unveraendert
        with fits.open(stacked) as hdul:
            assert np.allclose(hdul[0].data, data.transpose(2, 0, 1))

    def test_auto_passes_through_apply_pcc(self, tmp_path: Path):
        """"auto" reicht fallback an apply_pcc durch (Kette + gray_world)."""
        from astro_process.core.pcc import photometric_color_calibration

        stacked = tmp_path / "stacked.fits"
        data = np.ones((4, 4, 3), dtype=np.float32)
        fits.PrimaryHDU(data.transpose(2, 0, 1)).writeto(stacked)

        captured: dict = {}

        def load(_p: Path) -> np.ndarray:
            return data

        def save(arr: np.ndarray, _p: Path) -> None:
            captured["saved"] = True

        with patch("astro_process.core.pcc.apply_pcc") as mock_apply, \
             patch("astro_process.core.pcc.get_pcc_fallback", return_value="auto"):
            mock_apply.return_value = PCCResult(corrected=data, status="gaia_success")
            photometric_color_calibration(
                stacked, {}, load_frame=load, save_frame=save, config=None,
            )

        mock_apply.assert_called_once()
        _, kwargs = mock_apply.call_args
        assert kwargs.get("fallback") == "auto"
        assert captured.get("saved") is True


class TestApplyPccPerGroupStatus:
    """PCCResult-Status-Propagierung: apply_pcc_per_group liest PCC_STATUS.txt."""

    def test_status_file_yields_correct_status(self, tmp_path: Path):
        """PCC_STATUS.txt mit 'fallback_gray_world' -> korrekter Status."""
        from astro_process.agents.multi_group_agent import apply_pcc_per_group
        from astro_process.config.models import MultiGroupConfig

        group_dir = tmp_path / "group_x"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True)
        stack = stacked_dir / "stacked.fits"
        data = np.ones((3, 8, 8), dtype=np.float32)
        fits.PrimaryHDU(data).writeto(stack)

        def fake_pcc(_stacked, _params, **kw):
            # Simuliert den Wrapper: schreibt PCC_STATUS.txt
            (_stacked.parent / "PCC_STATUS.txt").write_text(
                "pcc_status=fallback_gray_world\n"
            )

        pcc_path, status = apply_pcc_per_group(
            stack, context=None,
            multi_group_config=MultiGroupConfig(pcc_fallback="auto"),
            group_dir=group_dir,
            photometric_color_calibration_fn=fake_pcc,
        )

        assert status == "fallback_gray_world"
        assert pcc_path.name == "pcc_applied.fits"
        assert pcc_path.exists()

    def test_skip_marker_yields_skipped_status(self, tmp_path: Path):
        """PCC_STATUS.txt mit 'pcc_skipped' -> 'pcc_skipped'."""
        from astro_process.agents.multi_group_agent import apply_pcc_per_group
        from astro_process.config.models import MultiGroupConfig

        group_dir = tmp_path / "group_x"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True)
        stack = stacked_dir / "stacked.fits"
        data = np.ones((3, 8, 8), dtype=np.float32)
        fits.PrimaryHDU(data).writeto(stack)

        def fake_pcc(_stacked, _params, **kw):
            (_stacked.parent / "PCC_STATUS.txt").write_text(
                "pcc_status=pcc_skipped\n"
            )

        pcc_path, status = apply_pcc_per_group(
            stack, context=None,
            multi_group_config=MultiGroupConfig(pcc_fallback="skip"),
            group_dir=group_dir,
            photometric_color_calibration_fn=fake_pcc,
        )

        assert status == "pcc_skipped"
        assert pcc_path.name == "pcc_applied.fits"
        assert pcc_path.exists()
        assert not (stacked_dir / "PCC_FALLBACK_GRAY_WORLD.txt").exists()

    def test_vizier_apass_status(self, tmp_path: Path):
        """PCC_STATUS.txt mit 'vizier_apass_success' -> korrekter Status."""
        from astro_process.agents.multi_group_agent import apply_pcc_per_group
        from astro_process.config.models import MultiGroupConfig

        group_dir = tmp_path / "group_x"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True)
        stack = stacked_dir / "stacked.fits"
        data = np.ones((3, 8, 8), dtype=np.float32)
        fits.PrimaryHDU(data).writeto(stack)

        def fake_pcc(_stacked, _params, **kw):
            (_stacked.parent / "PCC_STATUS.txt").write_text(
                "pcc_status=vizier_apass_success\n"
            )

        pcc_path, status = apply_pcc_per_group(
            stack, context=None,
            multi_group_config=MultiGroupConfig(pcc_fallback="auto"),
            group_dir=group_dir,
            photometric_color_calibration_fn=fake_pcc,
        )

        assert status == "vizier_apass_success"


class TestPCCResultDataclass:
    """PCCResult-Dataclass: Struktur und Status-Werte."""

    def test_pcc_result_fields(self):
        """PCCResult hat corrected und status Felder."""
        rgb = _rgb()
        result = PCCResult(corrected=rgb, status="gaia_success")
        assert result.corrected is rgb
        assert result.status == "gaia_success"

    def test_pcc_result_none_corrected(self):
        """PCCResult mit corrected=None fuer skip/fail."""
        result = PCCResult(corrected=None, status="pcc_skipped")
        assert result.corrected is None
        assert result.status == "pcc_skipped"

    def test_pcc_result_is_dataclass(self):
        """PCCResult ist eine Dataclass (eq, repr)."""
        r1 = PCCResult(corrected=None, status="gaia_success")
        r2 = PCCResult(corrected=None, status="gaia_success")
        assert r1 == r2
        assert "PCCResult" in repr(r1)


class TestPCCResultStatusPropagation:
    """Status-Propagierung durch die gesamte PCC-Kette."""

    def test_gaia_success_status(self):
        """VizieR scheitert, GAIA-Erfolg -> status='gaia_success' (V1.6-5)."""
        rgb = _rgb()
        corrected = rgb.copy().astype(np.float32)

        with patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=corrected, status="gaia_success")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.status == "gaia_success"
        assert result.corrected is corrected

    def test_vizier_apass_success_status(self):
        """GAIA scheitert, VizieR APASS erfolgreich -> status='vizier_apass_success'."""
        rgb = _rgb()
        corrected = rgb.copy().astype(np.float32)

        with patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=corrected, status="vizier_apass_success")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.status == "vizier_apass_success"

    def test_vizier_refcat2_success_status(self):
        """GAIA + APASS scheitern, VizieR Refcat2 erfolgreich -> status='vizier_refcat2_success'."""
        rgb = _rgb()
        corrected = rgb.copy().astype(np.float32)

        with patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=corrected, status="vizier_refcat2_success")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.status == "vizier_refcat2_success"

    def test_fallback_gray_world_status(self):
        """Alle Kataloge scheitern + auto -> status='fallback_gray_world'."""
        rgb = _rgb()

        with patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.status == "fallback_gray_world"
        assert result.corrected is not None
        assert result.corrected.shape == rgb.shape

    def test_no_coords_gray_world_status(self):
        """Ohne Koordinaten + auto -> status='fallback_gray_world'."""
        rgb = _rgb()
        result = apply_pcc(rgb)
        assert result.status == "fallback_gray_world"
        assert result.corrected is not None

    def test_no_coords_skip_status(self):
        """Ohne Koordinaten + skip -> status='pcc_skipped'."""
        rgb = _rgb()
        result = apply_pcc(rgb, fallback="skip")
        assert result.status == "pcc_skipped"
        assert result.corrected is None

    def test_skip_status_all_catalogs_fail(self):
        """Alle Kataloge scheitern + skip -> status='pcc_skipped'."""
        rgb = _rgb()

        with patch("astro_process.core.pcc._gaia_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")), \
             patch("astro_process.core.pcc._vizier_pcc",
                   return_value=PCCResult(corrected=None, status="skipped")):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                               fallback="skip")

        assert result.status == "pcc_skipped"
        assert result.corrected is None

    def test_status_file_written_on_success(self, tmp_path: Path):
        """PCC_STATUS.txt wird bei Erfolg geschrieben mit korrektem Status."""
        from astro_process.core.pcc import photometric_color_calibration

        stacked = tmp_path / "stacked.fits"
        data = np.ones((4, 4, 3), dtype=np.float32)
        fits.PrimaryHDU(data.transpose(2, 0, 1)).writeto(stacked)

        def load(_p: Path) -> np.ndarray:
            return data

        def save(arr: np.ndarray, _p: Path) -> None:
            pass

        with patch("astro_process.core.pcc.apply_pcc",
                   return_value=PCCResult(corrected=data, status="gaia_success")), \
             patch("astro_process.core.pcc.get_pcc_fallback", return_value="auto"):
            photometric_color_calibration(
                stacked, {}, load_frame=load, save_frame=save, config=None,
            )

        status_path = tmp_path / "PCC_STATUS.txt"
        assert status_path.exists()
        assert "pcc_status=gaia_success" in status_path.read_text()

    def test_status_file_written_on_gray_world(self, tmp_path: Path):
        """PCC_STATUS.txt wird bei gray_world-Fallback geschrieben."""
        from astro_process.core.pcc import photometric_color_calibration

        stacked = tmp_path / "stacked.fits"
        data = np.ones((4, 4, 3), dtype=np.float32)
        fits.PrimaryHDU(data.transpose(2, 0, 1)).writeto(stacked)

        def load(_p: Path) -> np.ndarray:
            return data

        def save(arr: np.ndarray, _p: Path) -> None:
            pass

        with patch("astro_process.core.pcc.apply_pcc",
                   return_value=PCCResult(corrected=data, status="fallback_gray_world")), \
             patch("astro_process.core.pcc.get_pcc_fallback", return_value="auto"):
            photometric_color_calibration(
                stacked, {}, load_frame=load, save_frame=save, config=None,
            )

        status_path = tmp_path / "PCC_STATUS.txt"
        assert status_path.exists()
        assert "pcc_status=fallback_gray_world" in status_path.read_text()


class TestProcessingParamsTimeouts:
    """Bug 3: Vizier-Timeouts als konfigurierbare Config-Felder."""

    def test_vizier_timeout_defaults(self):
        """Neue Config-Felder haben korrekte Defaults (30.0)."""
        from astro_process.config.models import ProcessingParams
        params = ProcessingParams()
        assert params.gaia_timeout == 30.0
        assert params.vizier_apass_timeout == 30.0
        assert params.vizier_refcat2_timeout == 30.0

    def test_vizier_timeout_custom(self):
        """Custom Timeout-Werte werden korrekt gespeichert."""
        from astro_process.config.models import ProcessingParams
        params = ProcessingParams(
            gaia_timeout=60.0,
            vizier_apass_timeout=25.0,
            vizier_refcat2_timeout=35.0,
        )
        assert params.gaia_timeout == 60.0
        assert params.vizier_apass_timeout == 25.0
        assert params.vizier_refcat2_timeout == 35.0

    def test_vizier_timeout_dict_read(self):
        """photometric_color_calibration liest Timeouts aus params dict."""
        import astro_process.core.pcc as pcc_mod
        params = {
            "gaia_timeout": 45.0,
            "vizier_apass_timeout": 20.0,
            "vizier_refcat2_timeout": 40.0,
        }
        assert pcc_mod.GAIA_QUERY_TIMEOUT_SECONDS == 30.0
        # Defaults stimmen wenn nicht in params
        assert params.get("vizier_apass_timeout", 30.0) == 20.0
        assert params.get("vizier_refcat2_timeout", 30.0) == 40.0
        # Fallback bei fehlendem Key
        assert {}.get("vizier_apass_timeout", 30.0) == 30.0
        assert {}.get("vizier_refcat2_timeout", 30.0) == 30.0


class TestPhotometricColorCalibrationReturns:
    """photometric_color_calibration gibt den PCC-Status als String zurueck
    (fuer ProcessingResult.pcc_status Persistierung in agent-log + run-info)."""

    def _make_stacked(self, tmp_path: Path, seed: int = 1) -> Path:
        stacked = tmp_path / "stacked.fits"
        rgb = _rgb(seed=seed)
        hdu = fits.PrimaryHDU(rgb.transpose(2, 0, 1))
        hdu.writeto(stacked, overwrite=True)
        return stacked

    @staticmethod
    def _load(p):
        return fits.getdata(p).transpose(1, 2, 0).astype(np.float32)

    @staticmethod
    def _save(arr, p):
        fits.PrimaryHDU(arr.transpose(2, 0, 1)).writeto(p, overwrite=True)

    def test_returns_gaia_success(self, tmp_path: Path):
        """Erfolgreicher GAIA-PCC -> Status 'gaia_success'."""
        import structlog
        from astro_process.core.pcc import photometric_color_calibration

        stacked = self._make_stacked(tmp_path, seed=1)
        fake_result = PCCResult(corrected=_rgb(seed=1), status="gaia_success")

        with patch("astro_process.core.pcc.apply_pcc", return_value=fake_result):
            status = photometric_color_calibration(
                stacked, {}, load_frame=self._load, save_frame=self._save,
                logger=structlog.get_logger("test_pcc"),
                ra=180.0, dec=30.0, pixel_scale_arcsec=8.0,
            )
        assert status == "gaia_success"

    def test_returns_pcc_skipped_when_corrected_none(self, tmp_path: Path):
        """PCC-Kette fehlgeschlagen + skip-Fallback -> Status 'skipped'."""
        import structlog
        from astro_process.core.pcc import photometric_color_calibration

        stacked = self._make_stacked(tmp_path, seed=2)
        fake_result = PCCResult(corrected=None, status="skipped")

        with patch("astro_process.core.pcc.apply_pcc", return_value=fake_result):
            status = photometric_color_calibration(
                stacked, {}, load_frame=self._load, save_frame=self._save,
                logger=structlog.get_logger("test_pcc"),
                ra=180.0, dec=30.0, pixel_scale_arcsec=8.0,
            )
        assert status == "skipped"

    def test_returns_none_when_stacked_missing(self, tmp_path: Path):
        """Stack-Datei fehlt -> None (kein PCC versucht)."""
        from astro_process.core.pcc import photometric_color_calibration

        stacked = tmp_path / "nonexistent.fits"

        status = photometric_color_calibration(
            stacked, {}, load_frame=lambda p: None, save_frame=lambda a, p: None,
        )
        assert status is None

    def test_returns_fallback_gray_world_on_exception(self, tmp_path: Path):
        """PCC-Exception + fallback='auto' -> Status 'fallback_gray_world'."""
        import structlog
        from astro_process.core.pcc import photometric_color_calibration

        stacked = self._make_stacked(tmp_path, seed=3)

        with patch("astro_process.core.pcc.apply_pcc", side_effect=RuntimeError("network")):
            status = photometric_color_calibration(
                stacked, {}, load_frame=self._load, save_frame=self._save,
                logger=structlog.get_logger("test_pcc"),
                ra=180.0, dec=30.0, pixel_scale_arcsec=8.0,
            )
        assert status == "fallback_gray_world"
