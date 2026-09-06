"""PCC-Timeout-Config-Flow: AppConfig -> photometric_color_calibration.

Tests, dass die Timeout-Werte aus config.yaml tatsaechlich im Code ankommen:
1. AppConfig hat die Timeout-Felder mit korrekten Defaults
2. Config-Werte fliessen in apply_pcc ein (Precedence: AppConfig > Preset Default)
3. Preset-Werte mit explizitem Timeout != Default ueberschreiben Config-Werte
4. Multi-Group-Pfad (proc_params = {}) nutzt ebenfalls Config-Werte
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.config.models import AppConfig, ProcessingParams
from astro_process.core.pcc import (
    GAIA_QUERY_TIMEOUT_SECONDS,
    PCCResult,
    photometric_color_calibration,
)


class TestAppConfigTimeoutFields:
    """AppConfig enthaelt die Timeout-Felder mit korrekten Defaults."""

    def test_appconfig_has_gaia_timeout_default_30(self):
        """AppConfig Default: gaia_timeout = 30.0."""
        cfg = AppConfig()
        assert cfg.gaia_timeout == 30.0

    def test_appconfig_has_vizier_apass_timeout_default_30(self):
        cfg = AppConfig()
        assert cfg.vizier_apass_timeout == 30.0

    def test_appconfig_has_vizier_refcat2_timeout_default_30(self):
        cfg = AppConfig()
        assert cfg.vizier_refcat2_timeout == 30.0

    def test_appconfig_custom_timeouts(self):
        """AppConfig parst benutzerdefinierte Timeout-Werte."""
        cfg = AppConfig(gaia_timeout=60.0, vizier_apass_timeout=20.0, vizier_refcat2_timeout=45.0)
        assert cfg.gaia_timeout == 60.0
        assert cfg.vizier_apass_timeout == 20.0
        assert cfg.vizier_refcat2_timeout == 45.0


class TestConfigTimeoutFlow:
    """Config-Werte fliessen in photometric_color_calibration / apply_pcc ein."""

    def _make_stacked(self, tmp_path: Path) -> Path:
        """Erzeuge eine minimale 3D-RGB-FITS als PCC-Input."""
        stacked = tmp_path / "stacked.fits"
        data = np.zeros((4, 4, 3), dtype=np.float32)
        fits.PrimaryHDU(data.transpose(2, 0, 1)).writeto(stacked)
        return stacked

    def test_config_overrides_preset_default(
        self, tmp_path, monkeypatch,
    ):
        """AppConfig gaia_timeout=60.0 ueberschreibt den Preset-Default 30.0.

        Wenn der Preset den Default-Wert (30.0) hat, soll der Config-Wert
        gelten.
        """
        import astro_process.core.pcc as pcc_mod

        stacked = self._make_stacked(tmp_path)
        cfg = AppConfig(gaia_timeout=60.0)
        captured: dict = {}

        def fake_apply_pcc(data_, **kwargs):
            captured.update(kwargs)
            return PCCResult(corrected=data_, status="gaia_success")

        monkeypatch.setattr(pcc_mod, "apply_pcc", fake_apply_pcc)

        # Preset hat den Default 30.0 -> Config 60.0 soll gewinnen
        preset_params = ProcessingParams().model_dump()
        assert preset_params["gaia_timeout"] == 30.0

        photometric_color_calibration(
            stacked, preset_params,
            load_frame=lambda p: np.zeros((4, 4, 3), dtype=np.float32),
            save_frame=lambda a, p: None,
            config=cfg,
            ra=1.0, dec=2.0,
        )
        assert captured.get("gaia_timeout") == 60.0

    def test_preset_explicit_value_wins_over_config(
        self, tmp_path, monkeypatch,
    ):
        """Preset gaia_timeout=15.0 ueberschreibt Config gaia_timeout=60.0.

        Wenn der Preset einen expliziten Wert != Default hat, soll dieser
        behalten werden.
        """
        import astro_process.core.pcc as pcc_mod

        stacked = self._make_stacked(tmp_path)
        cfg = AppConfig(gaia_timeout=60.0)
        captured: dict = {}

        def fake_apply_pcc(data_, **kwargs):
            captured.update(kwargs)
            return PCCResult(corrected=data_, status="gaia_success")

        monkeypatch.setattr(pcc_mod, "apply_pcc", fake_apply_pcc)

        # Preset hat expliziten Wert != Default -> Preset behaelt seinen Wert
        preset_params = ProcessingParams(gaia_timeout=15.0).model_dump()
        assert preset_params["gaia_timeout"] == 15.0

        photometric_color_calibration(
            stacked, preset_params,
            load_frame=lambda p: np.zeros((4, 4, 3), dtype=np.float32),
            save_frame=lambda a, p: None,
            config=cfg,
            ra=1.0, dec=2.0,
        )
        assert captured.get("gaia_timeout") == 15.0

    def test_config_overrides_vizier_timeouts(
        self, tmp_path, monkeypatch,
    ):
        """AppConfig vizier_*_timeout ueberschreibt Preset-Defaults."""
        import astro_process.core.pcc as pcc_mod

        stacked = self._make_stacked(tmp_path)
        cfg = AppConfig(vizier_apass_timeout=25.0, vizier_refcat2_timeout=45.0)
        captured: dict = {}

        def fake_apply_pcc(data_, **kwargs):
            captured.update(kwargs)
            return PCCResult(corrected=data_, status="gaia_success")

        monkeypatch.setattr(pcc_mod, "apply_pcc", fake_apply_pcc)

        preset_params = ProcessingParams().model_dump()

        photometric_color_calibration(
            stacked, preset_params,
            load_frame=lambda p: np.zeros((4, 4, 3), dtype=np.float32),
            save_frame=lambda a, p: None,
            config=cfg,
            ra=1.0, dec=2.0,
        )
        assert captured.get("vizier_apass_timeout") == 25.0
        assert captured.get("vizier_refcat2_timeout") == 45.0

    def test_empty_params_config_fills_in(
        self, tmp_path, monkeypatch,
    ):
        """Leerer params-dict (Multi-Group-Pfad): Config-Werte werden eingefuegt.

        Im Multi-Group-Pfad erstellt apply_pcc_per_group proc_params = {}.
        Config-Werte sollen trotzdem ankommen.
        """
        import astro_process.core.pcc as pcc_mod

        stacked = self._make_stacked(tmp_path)
        cfg = AppConfig(gaia_timeout=90.0, vizier_apass_timeout=15.0, vizier_refcat2_timeout=55.0)
        captured: dict = {}

        def fake_apply_pcc(data_, **kwargs):
            captured.update(kwargs)
            return PCCResult(corrected=data_, status="gaia_success")

        monkeypatch.setattr(pcc_mod, "apply_pcc", fake_apply_pcc)

        # Leerer params-dict (wie in apply_pcc_per_group)
        photometric_color_calibration(
            stacked, {},
            load_frame=lambda p: np.zeros((4, 4, 3), dtype=np.float32),
            save_frame=lambda a, p: None,
            config=cfg,
            ra=1.0, dec=2.0,
        )
        assert captured.get("gaia_timeout") == 90.0
        assert captured.get("vizier_apass_timeout") == 15.0
        assert captured.get("vizier_refcat2_timeout") == 55.0

    def test_no_config_keeps_preset_values(
        self, tmp_path, monkeypatch,
    ):
        """Ohne Config (config=None): Preset-Werte bleiben unveraendert."""
        import astro_process.core.pcc as pcc_mod

        stacked = self._make_stacked(tmp_path)
        captured: dict = {}

        def fake_apply_pcc(data_, **kwargs):
            captured.update(kwargs)
            return PCCResult(corrected=data_, status="gaia_success")

        monkeypatch.setattr(pcc_mod, "apply_pcc", fake_apply_pcc)

        preset_params = ProcessingParams(gaia_timeout=12.5).model_dump()

        photometric_color_calibration(
            stacked, preset_params,
            load_frame=lambda p: np.zeros((4, 4, 3), dtype=np.float32),
            save_frame=lambda a, p: None,
            config=None,
            ra=1.0, dec=2.0,
        )
        assert captured.get("gaia_timeout") == 12.5

    def test_defaults_without_config_or_preset_override(
        self, tmp_path, monkeypatch,
    ):
        """Ohne Config + Preset-Default: Code-Default (30.0) bleibt."""
        import astro_process.core.pcc as pcc_mod

        stacked = self._make_stacked(tmp_path)
        captured: dict = {}

        def fake_apply_pcc(data_, **kwargs):
            captured.update(kwargs)
            return PCCResult(corrected=data_, status="gaia_success")

        monkeypatch.setattr(pcc_mod, "apply_pcc", fake_apply_pcc)

        photometric_color_calibration(
            stacked, {},
            load_frame=lambda p: np.zeros((4, 4, 3), dtype=np.float32),
            save_frame=lambda a, p: None,
            config=None,
            ra=1.0, dec=2.0,
        )
        assert captured.get("gaia_timeout") == GAIA_QUERY_TIMEOUT_SECONDS
        assert captured.get("vizier_apass_timeout") == 30.0
        assert captured.get("vizier_refcat2_timeout") == 30.0
