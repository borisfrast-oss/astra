"""Tests for GAIA query timeout handling and gray-world fallback (T1).

Covers:
- _run_with_timeout: success, exception, and hang-then-TimeoutError behaviour.
- apply_pcc: falls back to gray-world when _gaia_pcc times out / returns
  None, forwards the gaia_timeout parameter, and keeps the untouched
  no-coordinates gray-world regression path.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from astropy.io import fits

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.core.pcc import (
    GAIA_QUERY_TIMEOUT_SECONDS,
    PCCResult,
    _run_with_timeout,
    apply_pcc,
)


class TestGaiaTimeout:
    """T1: GAIA query timeout + gray-world fallback."""

    def test_run_with_timeout_success(self):
        """fast function returns its result."""
        assert _run_with_timeout(lambda: 42, timeout=1.0) == 42

    def test_run_with_timeout_exception(self):
        """exception from the function is re-raised in the caller thread."""

        def boom():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_with_timeout(boom, timeout=1.0)

    def test_run_with_timeout_hangs(self):
        """hanging function raises TimeoutError within the timeout window.

        V1.1-Hardening (m7): _run_with_timeout wirft TimeoutError statt
        None zurueckzugeben (konsistent mit cli._run_with_timeout).
        """
        start = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            _run_with_timeout(lambda: time.sleep(5), timeout=0.2)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0

    def test_apply_pcc_falls_back_to_gray_world_on_timeout(self):
        """apply_pcc returns a gray-world result when the catalog chain fails.

        V1.4-19: apply_pcc versucht GAIA mit Backoff (1x/2x/3x timeout) und
        danach den VizieR-Zweit-Katalog, BEVOR gray_world greift. Der Test
        patcht _gaia_pcc (3 Versuche) UND _vizier_pcc (hermetic, kein echtes
        VizieR-Netzwerk) → gray_world.
        """
        rng = np.random.RandomState(42)
        rgb = rng.uniform(0.1, 0.9, (50, 50, 3)).astype(np.float32)
        fail = PCCResult(corrected=None, status="skipped")

        # Path 1: _gaia_pcc patched to return PCCResult(None) (failure path)
        with patch("astro_process.core.pcc._gaia_pcc", return_value=fail) as mock_gaia, \
             patch("astro_process.core.pcc._vizier_pcc", return_value=fail) as mock_vizier:
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)
            # V1.4-19: GAIA wird mit Backoff 3x versucht, dann VizieR
            assert mock_gaia.call_count == 3
            mock_vizier.assert_called_once()

        assert result.corrected.shape == rgb.shape
        assert result.corrected.dtype == np.float32
        assert np.all(np.isfinite(result.corrected))
        assert result.status == "fallback_gray_world"

        # Path 2: _gaia_pcc goes through the real _run_with_timeout timeout path
        def timeout_gaia(rgb_, ra_, dec_, pixel_scale=0.0, timeout=GAIA_QUERY_TIMEOUT_SECONDS):
            try:
                _run_with_timeout(lambda: time.sleep(5), timeout=0.2)
            except TimeoutError:
                return PCCResult(corrected=None, status="skipped")
            return PCCResult(corrected=rgb_.copy(), status="gaia_success")

        with patch("astro_process.core.pcc._gaia_pcc", side_effect=timeout_gaia), \
             patch("astro_process.core.pcc._vizier_pcc", return_value=fail):
            result2 = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result2.corrected.shape == rgb.shape
        assert result2.corrected.dtype == np.float32
        assert np.all(np.isfinite(result2.corrected))

    def test_apply_pcc_gaia_success_uses_timeout_param(self):
        """gaia_timeout is forwarded to _gaia_pcc as the timeout argument."""
        rgb = np.zeros((20, 20, 3), dtype=np.float32)

        with patch("astro_process.core.pcc._gaia_pcc") as mock_gaia:
            mock_gaia.return_value = PCCResult(corrected=rgb.copy().astype(np.float32), status="gaia_success")
            apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0, gaia_timeout=12.5)

        mock_gaia.assert_called_once()
        _, kwargs = mock_gaia.call_args
        assert kwargs.get("timeout") == 12.5

    def test_apply_pcc_no_coordinates_regression(self):
        """apply_pcc without coordinates still returns a gray-world result."""
        rng = np.random.RandomState(7)
        rgb = rng.uniform(0.1, 0.9, (40, 40, 3)).astype(np.float32)

        with patch("astro_process.core.pcc._gaia_pcc") as mock_gaia:
            result = apply_pcc(rgb)

        mock_gaia.assert_not_called()
        assert result.corrected.shape == rgb.shape
        assert result.corrected.dtype == np.float32
        assert np.all(np.isfinite(result.corrected))
        assert result.status == "fallback_gray_world"

    # ═══════════════════════════════════════════════════════════════
    # M2 (ray-Review v1.1): Optional-Dependency fehlt -> kein Thread-Crash
    # ═══════════════════════════════════════════════════════════════

    def test_gaia_unavailable_falls_back_without_thread(self):
        """Optional-Deps fehlen (Flag False) -> _gaia_pcc None, Gray-World aktiv.

        Kern des M2-Fixes: Der Worker-Thread wird bei fehlendem
        astroquery/sep gar nicht erst gestartet (kein ImportError im Thread,
        kein stummer Crash) — der Gray-World-Fallback greift direkt.
        """
        rng = np.random.RandomState(42)
        rgb = rng.uniform(0.1, 0.9, (50, 50, 3)).astype(np.float32)

        with patch("astro_process.core.pcc._GAIA_OPT_AVAILABLE", False), \
             patch("astro_process.core.pcc._run_with_timeout") as mock_timeout:
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        # Thread darf nie starten: _run_with_timeout wird nicht aufgerufen
        mock_timeout.assert_not_called()
        assert result.corrected.shape == rgb.shape
        assert result.corrected.dtype == np.float32
        assert np.all(np.isfinite(result.corrected))
        assert result.status == "fallback_gray_world"

    def test_gaia_pcc_returns_none_when_flag_false(self):
        """_gaia_pcc gibt PCCResult(None) zurueck, wenn die Optional-Deps fehlen."""
        from astro_process.core import pcc as pcc_mod

        rng = np.random.RandomState(1)
        rgb = rng.uniform(0.1, 0.9, (30, 30, 3)).astype(np.float32)

        with patch("astro_process.core.pcc._GAIA_OPT_AVAILABLE", False), \
             patch("astro_process.core.pcc._run_with_timeout") as mock_timeout:
            out = pcc_mod._gaia_pcc(rgb, 180.0, 30.0, pixel_scale=16.0, timeout=5.0)

        assert out.corrected is None
        assert out.status == "skipped"
        mock_timeout.assert_not_called()

    def test_module_import_graceful_without_optional_deps(self, monkeypatch):
        """Modul-Import ohne astroquery -> _GAIA_OPT_AVAILABLE=False, kein Crash.

        Simuliert ein System ohne das Optional-Dependency: Der pcc-Modulimport
        schlaegt beim astroquery-Import NICHT fehl, sondern setzt das Flag und
        laesst GAIA-PCC deaktiviert (Gray-World-Fallback).
        """
        import builtins
        import importlib

        import astro_process.core.pcc as pcc

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "astroquery" or name.startswith("astroquery."):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        saved = {
            m: sys.modules.pop(m, None)
            for m in ("astroquery", "astroquery.gaia", "sep")
        }
        monkeypatch.setattr(builtins, "__import__", fake_import)
        try:
            reloaded = importlib.reload(pcc)
            assert reloaded._GAIA_OPT_AVAILABLE is False
        finally:
            for mod, val in saved.items():
                if val is not None:
                    sys.modules[mod] = val
            # fake_import vor dem Restore-Reload deaktivieren, sonst bleibt
            # das Flag False (der Reload wuerde erneut astroquery blocken).
            builtins.__import__ = real_import
            importlib.reload(pcc)
            assert pcc._GAIA_OPT_AVAILABLE is True


class TestGaiaTimeoutConfigField:
    """F-P2-GAIA-TIMEOUT (S3-C5): Config-Feld `gaia_timeout`."""

    def test_processing_params_has_gaia_timeout_default_30(self):
        """Config-Feld existiert mit Default 30.0 (rueckwaertskompatibel)."""
        from astro_process.config.models import ProcessingParams

        params = ProcessingParams()
        assert params.gaia_timeout == 30.0
        assert params.model_dump()["gaia_timeout"] == 30.0

    def test_processing_params_gaia_timeout_override(self):
        from astro_process.config.models import ProcessingParams

        assert ProcessingParams(gaia_timeout=12.5).gaia_timeout == 12.5

    def test_agent_forwards_gaia_timeout_to_apply_pcc(
        self, tmp_path: Path, monkeypatch
    ):
        """Agent reicht `params['gaia_timeout']` an apply_pcc durch.

        Ohne Feld gilt der bisherige Default (GAIA_QUERY_TIMEOUT_SECONDS =
        30.0) — alte Presets bleiben v1.1-identisch.
        """
        # Refactor 2026-08-14 (Cluster 5): Kern-Logik von
        # `_photometric_color_calibration` liegt jetzt in core/pcc.py
        # (photometric_color_calibration) -> apply_pcc wird im
        # core.pcc-Namespace aufgeloest, deshalb dort patchen.
        import astro_process.core.pcc as pcc_mod
        from astro_process.agents.processing_agent import ProcessingAgent
        from astro_process.core.pcc import GAIA_QUERY_TIMEOUT_SECONDS

        agent = ProcessingAgent(working_dir=tmp_path, config=None)
        stacked = tmp_path / "stacked.fits"
        data = np.zeros((4, 4, 3), dtype=np.float32)
        fits.PrimaryHDU(data.transpose(2, 0, 1)).writeto(stacked)

        captured: dict = {}

        def fake_apply_pcc(data_, **kwargs):
            captured.update(kwargs)
            return PCCResult(corrected=data_, status="gaia_success")

        monkeypatch.setattr(pcc_mod, "apply_pcc", fake_apply_pcc)

        # Config-Wert wird durchgereicht
        agent._photometric_color_calibration(
            stacked, {"gaia_timeout": 12.5}, ra=1.0, dec=2.0
        )
        assert captured.get("gaia_timeout") == 12.5

        # Rueckwaertskompatibel: ohne Feld -> Default 30.0
        captured.clear()
        agent._photometric_color_calibration(stacked, {}, ra=1.0, dec=2.0)
        assert captured.get("gaia_timeout") == GAIA_QUERY_TIMEOUT_SECONDS
