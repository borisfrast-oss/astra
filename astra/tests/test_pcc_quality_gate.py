"""Tests: PCC Quality Gate (2026-08-21) — plausible Farb-Faktoren erzwingen.

Spec: orion/_work/stella/issue-pcc-quality-gate.md.
Hintergrund: M92-Lauf 171059 wandte r_factor=-9.73 an und meldete trotzdem
'gaia_success' (Stack katastrophal). Das Gate lehnt Katalog-Ergebnisse mit
Faktoren <= 0 oder ausserhalb [min_factor, max_factor] ab — zentral fuer
GAIA- UND VizieR-Pfad, NACH Faktor-Berechnung, VOR Apply/Overwrite.
leo-Entscheidung: Eine Gate-Ablehnung ENDET die PCC-Kette (kein weiterer
Katalog-Fallback, kein gray_world).
"""

from __future__ import annotations

import json
import sys
import yaml
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from astro_process.core.pcc import (
    PCCResult,
    _factors_plausible,
    apply_pcc,
    photometric_color_calibration,
)
from test_multi_group import create_test_fits, make_sample_context  # noqa: E402


def _rgb(seed: int = 42, size: int = 40) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return rng.uniform(0.1, 0.9, (size, size, 3)).astype(np.float32)


def _vizier_result(
    r: float, g: float, b: float, seed: int = 1
) -> PCCResult:
    return PCCResult(
        corrected=_rgb(seed=seed), status="vizier_apass_success",
        r_factor=r, g_factor=g, b_factor=b,
    )


class TestFactorsPlausible:
    """Unit: _factors_plausible Grenzen."""

    def test_negative_rejected(self):
        assert not _factors_plausible(-1.0, 1.0, 1.0, 0.5, 2.0)

    def test_zero_rejected(self):
        assert not _factors_plausible(1.0, 0.0, 1.0, 0.5, 2.0)

    def test_too_large_rejected(self):
        assert not _factors_plausible(1.0, 2.5, 1.0, 0.5, 2.0)

    def test_too_small_rejected(self):
        assert not _factors_plausible(1.0, 0.3, 1.0, 0.5, 2.0)

    def test_boundary_values_pass(self):
        assert _factors_plausible(0.5, 2.0, 1.0, 0.5, 2.0)

    def test_nan_rejected(self):
        assert not _factors_plausible(float("nan"), 1.0, 1.0, 0.5, 2.0)


class TestApplyPccQualityGate:
    """Zentrale Gate-Pruefung in apply_pcc (GAIA UND VizieR)."""

    def test_negative_factor_rejected(self):
        """AC: Negativer Faktor -> rejected_implausible_factors, corrected=None."""
        rgb = _rgb()
        with patch("astro_process.core.pcc._vizier_pcc",
                   return_value=_vizier_result(-9.73, 0.27, -0.76)), \
             patch("astro_process.core.pcc._gaia_pcc") as mock_gaia:
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.corrected is None
        assert result.status == "rejected_implausible_factors"
        assert result.r_factor == -9.73
        mock_gaia.assert_not_called()

    def test_too_large_factor_rejected(self):
        """AC: Faktor > max (3.0 > 2.0) -> rejected."""
        rgb = _rgb()
        with patch("astro_process.core.pcc._vizier_pcc",
                   return_value=_vizier_result(1.0, 3.0, 1.0)):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.status == "rejected_implausible_factors"
        assert result.g_factor == 3.0

    def test_too_small_factor_rejected(self):
        """AC: Faktor < min (0.3 < 0.5) -> rejected."""
        rgb = _rgb()
        with patch("astro_process.core.pcc._vizier_pcc",
                   return_value=_vizier_result(1.0, 0.3, 1.0)):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.status == "rejected_implausible_factors"
        assert result.g_factor == 0.3

    def test_plausible_factors_pass_through_unchanged(self):
        """AC: Alle Faktoren in Range -> Verhalten unveraendert."""
        rgb = _rgb()
        ok = _vizier_result(1.47, 0.69, 1.15)
        with patch("astro_process.core.pcc._vizier_pcc", return_value=ok), \
             patch("astro_process.core.pcc._gaia_pcc") as mock_gaia:
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result is ok
        assert result.status == "vizier_apass_success"
        mock_gaia.assert_not_called()

    def test_custom_bounds_applied(self):
        """Konfigurierte Grenzen werden genutzt (hier: 0.8–1.2)."""
        rgb = _rgb()
        with patch("astro_process.core.pcc._vizier_pcc",
                   return_value=_vizier_result(1.4, 1.0, 1.0)):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                               quality_gate_min_factor=0.8,
                               quality_gate_max_factor=1.2)

        assert result.status == "rejected_implausible_factors"

    def test_gate_disabled_passes_bad_factors(self):
        """enabled=False -> Verhalten wie v1.6 (Faktoren ungeprueft)."""
        rgb = _rgb()
        bad = _vizier_result(-9.73, 0.27, -0.76)
        with patch("astro_process.core.pcc._vizier_pcc", return_value=bad):
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                               quality_gate_enabled=False)

        assert result is bad

    def test_rejection_ends_chain_no_gray_world_no_next_catalog(self):
        """leo-Entscheidung: Ablehnung endet die Kette — kein GAIA-Retry,
        kein gray_world (fallback='auto')."""
        rgb = _rgb()
        with patch("astro_process.core.pcc._vizier_pcc",
                   return_value=_vizier_result(-1.0, 1.0, 1.0)), \
             patch("astro_process.core.pcc._gaia_pcc") as mock_gaia:
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0,
                               fallback="auto")

        assert result.status == "rejected_implausible_factors"
        mock_gaia.assert_not_called()

    def test_gaia_path_also_gated_single_attempt(self):
        """VizieR scheitert, GAIA liefert Muell-Faktoren -> rejected;
        keine weiteren GAIA-Retries (Kette beendet)."""
        rgb = _rgb()
        fail = PCCResult(corrected=None, status="skipped")
        gaia_bad = PCCResult(
            corrected=_rgb(seed=2), status="gaia_success",
            r_factor=-2.93, g_factor=0.14, b_factor=-0.28,
        )
        with patch("astro_process.core.pcc._vizier_pcc", return_value=fail), \
             patch("astro_process.core.pcc._gaia_pcc",
                   return_value=gaia_bad) as mock_gaia:
            result = apply_pcc(rgb, ra=180.0, dec=30.0, pixel_scale_arcsec=16.0)

        assert result.status == "rejected_implausible_factors"
        assert result.r_factor == -2.93
        assert mock_gaia.call_count == 1


class TestPhotometricColorCalibrationGate:
    """Wrapper-Level: Stack bleibt linear, Marker, Status-Rueckgabe."""

    def _make_stacked(self, tmp_path: Path, seed: int = 1) -> tuple[Path, np.ndarray]:
        stacked = tmp_path / "stacked.fits"
        rgb = _rgb(seed=seed)
        fits.PrimaryHDU(rgb.transpose(2, 0, 1)).writeto(stacked, overwrite=True)
        return stacked, rgb

    @staticmethod
    def _load(p):
        return fits.getdata(p).transpose(1, 2, 0).astype(np.float32)

    @staticmethod
    def _save(arr, p):
        fits.PrimaryHDU(arr.transpose(2, 0, 1)).writeto(p, overwrite=True)

    def test_rejected_stack_stays_linear_marker_and_status(self, tmp_path: Path):
        """AC: Bei Ablehnung wird der Stack NICHT ueberschrieben (bleibt
        linear), Marker PCC_REJECTED_FACTORS.txt enthaelt die Faktoren,
        Rueckgabe 'rejected_implausible_factors'."""
        import structlog

        stacked, original = self._make_stacked(tmp_path)
        rejected = PCCResult(
            corrected=None, status="rejected_implausible_factors",
            r_factor=-9.73, g_factor=0.27, b_factor=-0.76,
        )

        saved: list = []

        def save_spy(arr, p):
            saved.append(arr)
            self._save(arr, p)

        with patch("astro_process.core.pcc.apply_pcc", return_value=rejected):
            status = photometric_color_calibration(
                stacked, {}, load_frame=self._load, save_frame=save_spy,
                logger=structlog.get_logger("test_qg"),
                ra=180.0, dec=30.0, pixel_scale_arcsec=8.0,
            )

        # Status korrekt (fliesst via ProcessingResult.pcc_status in
        # agent-log.yaml UND run-info.json).
        assert status == "rejected_implausible_factors"
        # Stack NICHT ueberschrieben (kein save_frame-Aufruf).
        assert saved == []
        with fits.open(stacked) as hdul:
            assert np.allclose(hdul[0].data, original.transpose(2, 0, 1))
        # Marker mit Faktoren.
        marker = tmp_path / "PCC_REJECTED_FACTORS.txt"
        assert marker.exists()
        text = marker.read_text(encoding="utf-8")
        assert "r_factor=-9.73" in text
        assert "g_factor=0.27" in text
        assert "b_factor=-0.76" in text
        # Kein Skip-Marker (unterscheidbare Zustaende).
        assert not (tmp_path / "PCC_SKIPPED.txt").exists()
        # PCC_STATUS.txt mit Rejection-Status (apply_pcc_per_group leitet
        # den Gruppen-Status daraus ab — sonst faelschlich gaia_success).
        status_file = tmp_path / "PCC_STATUS.txt"
        assert status_file.exists()
        assert "pcc_status=rejected_implausible_factors" in (
            status_file.read_text(encoding="utf-8")
        )


class TestQualityGatePersistence:
    """Status-Persistenz: agent-log.yaml UND run-info.json (beide!)."""

    def _context(self) -> SimpleNamespace:
        return SimpleNamespace(
            target=SimpleNamespace(
                name="M92",
                target_type=SimpleNamespace(value="globular_cluster"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(dark_count=0, flat_count=0, bias_count=0),
            get_lights=SimpleNamespace(group_by_params=lambda: {}),
        )

    def _proc_result(self) -> SimpleNamespace:
        return SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=Path("/tmp/stacked.fits"),
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
            gradient_removal=None,
            registration_metrics=None,
            pcc_status="rejected_implausible_factors",
        )

    def test_agent_log_and_run_info_both_carry_rejected_status(self, tmp_path: Path):
        """pcc_status='rejected_implausible_factors' landt in agent-log.yaml
        (processing.pcc_status) UND run-info.json (Top-Level)."""
        import yaml

        from astro_process.agents.archive import ArchiveAgent

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        agent = ArchiveAgent(output_root=output_dir, config=None)

        log_path = agent._create_agent_log(
            output_dir, self._context(), self._proc_result(),
            SimpleNamespace(master_dark=None, calibrated_lights=["a.fits"]),
        )
        run_info_path = agent._write_run_info(
            output_dir, self._context(),
            proc_result=self._proc_result(), discovery_result=None,
        )

        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["pcc_status"] == "rejected_implausible_factors"

        data = json.loads(run_info_path.read_text(encoding="utf-8"))
        assert data["pcc_status"] == "rejected_implausible_factors"


class TestQualityGateConfig:
    """Config-Modelle: pcc.quality_gate Defaults + Custom-Werte."""

    def test_defaults(self):
        from astro_process.config.models import (
            AppConfig, PCCConfig, PCCQualityGateConfig,
        )

        qg = PCCQualityGateConfig()
        assert qg.enabled is True
        assert qg.min_factor == 0.5
        assert qg.max_factor == 2.0
        assert isinstance(AppConfig().pcc, PCCConfig)

    def test_custom_values_from_dict(self):
        from astro_process.config.models import AppConfig

        cfg = AppConfig.model_validate({
            "pcc": {"quality_gate": {"enabled": False, "min_factor": 0.8,
                                     "max_factor": 1.25}},
        })
        assert cfg.pcc.quality_gate.enabled is False
        assert cfg.pcc.quality_gate.min_factor == 0.8
        assert cfg.pcc.quality_gate.max_factor == 1.25

    def test_wrapper_respects_disabled_gate(self, tmp_path: Path):
        """photometric_color_calibration liest pcc.quality_gate.enabled=False
        und reicht es an apply_pcc durch."""
        import structlog

        from astro_process.config.models import AppConfig

        stacked = tmp_path / "stacked.fits"
        rgb = _rgb(seed=5)
        fits.PrimaryHDU(rgb.transpose(2, 0, 1)).writeto(stacked, overwrite=True)
        bad = PCCResult(
            corrected=_rgb(seed=3), status="gaia_success",
            r_factor=-9.73, g_factor=0.27, b_factor=-0.76,
        )
        captured: dict = {}

        def fake_apply(*args, **kwargs):
            captured.update(kwargs)
            return bad

        cfg = AppConfig.model_validate({
            "pcc": {"quality_gate": {"enabled": False}},
        })
        with patch("astro_process.core.pcc.apply_pcc", side_effect=fake_apply):
            status = photometric_color_calibration(
                stacked, {},
                load_frame=lambda p: fits.getdata(p).transpose(1, 2, 0).astype(np.float32),
                save_frame=lambda arr, p: fits.PrimaryHDU(
                    arr.transpose(2, 0, 1)).writeto(p, overwrite=True),
                logger=structlog.get_logger("test_qg"), config=cfg,
                ra=180.0, dec=30.0, pixel_scale_arcsec=8.0,
            )

        assert captured.get("quality_gate_enabled") is False
        # Gate aus -> Erfolg-Status bleibt unveraendert (v1.6-Verhalten).
        assert status == "gaia_success"


# ═══════════════════════════════════════════════════════════════════
# ray Review Fixes 1+2 (2026-08-21): Merged-Pfad & Re-Run-Schutz
# ═══════════════════════════════════════════════════════════════════


class TestMergedPccStatusPersistence:
    """ray Review Fix 1 (CRITICAL): Im Merged-PCC-Modus (pcc_per_group=
    False) warf process_multi_group den Rueckgabewert von
    _apply_pcc_per_group weg → pcc_status blieb "pending" und
    rejected_implausible_factors erreichte agent-log.yaml/run-info.json
    NIE (Critical-1-Luecke aus Lauf 171059).

    ray Review Fix 2 (MAJOR): MG-Header (MGCNTGRP) nur bei Erfolgsstatus;
    Idempotenz-Check und standalone `merge` werten Rejection-Marker VOR
    MG-Headern aus — sonst meldet ein Re-Run fälschlich gaia_success.
    """

    def _run_merged_pipeline(self, tmp_path: Path):
        """Echter Merged-Pfad: Registrierung/Stacking gemockt, aber die
        REALER PCC-Kette laeuft (nur core.apply_pcc gemockt → Gate-
        Rejection). Der Wrapper schreibt echte Marker/Status-Dateien."""
        from astro_process.agents.merge_agent import MergeResult
        from astro_process.agents.processing_agent import ProcessingAgent
        from astro_process.config.models import MultiGroupConfig, ProcessingParams
        from astro_process.core.registration import (
            RegisterFramesResult,
            RegistrationResult,
        )

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = make_sample_context(
            tmp_path / "data", group_count=2, frames_per_group=3
        )
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        # DEF-014-Fix: photometric_color_calibration-Step noetig damit PCC laeuft
        from astro_process.config.models import PipelineStep  # noqa: F401
        pipeline.steps = [
            PipelineStep(name="register_frames"),
            PipelineStep(name="stack_frames"),
            PipelineStep(name="photometric_color_calibration"),
            PipelineStep(name="export"),
        ]

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
        merged_fits = create_test_fits(
            tmp_path / "merged.fits", exptime=60.0, gain=40, rng_seed=3
        )
        merge_agent = MagicMock()
        merge_agent.run.return_value = MergeResult(
            merged_path=merged_fits, merge_report={}
        )

        rejected = PCCResult(
            corrected=None, status="rejected_implausible_factors",
            r_factor=-9.73, g_factor=0.27, b_factor=-0.76,
        )

        with (
            patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg,
            patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack,
            patch.object(agent, "_register_to_reference_stack") as mock_cross,
            patch("astro_process.core.pcc.apply_pcc", return_value=rejected),
        ):
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], shift_y=0.0, shift_x=0.0,
                correlation=0.9, corr_hp=0.9, status="ok",
            )
            result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=MultiGroupConfig(),
                merge_agent=merge_agent,
            )
        return context, result

    def test_gate_rejection_reaches_agent_log_and_run_info(self, tmp_path):
        """PFLICHT (ray): Echter Merged-Pfad mit Gate-Rejection — der Status
        muss in ProcessingResult UND beiden Persistenz-Artefakten ankommen
        (agent-log.yaml UND run-info.json)."""
        import structlog  # noqa: F401

        from astro_process.agents.archive import ArchiveAgent

        context, result = self._run_merged_pipeline(tmp_path)

        # 1) Fix 1: Status bis ProcessingResult durchgekommen
        assert result.pcc_status == "rejected_implausible_factors"

        merged_dir = tmp_path / "out" / "merged"
        # apply_pcc_per_group arbeitet auf merged/04_stacked/pcc_applied.fits
        # (Kopie); dort schreibt der Wrapper Marker + PCC_STATUS.txt.
        work_dir = merged_dir / "04_stacked"
        # 2) Echter Wrapper lief: Marker + PCC_STATUS.txt im Arbeits-Dir
        assert (work_dir / "PCC_REJECTED_FACTORS.txt").exists()
        assert (work_dir / "PCC_STATUS.txt").read_text(
            encoding="utf-8").strip() == "pcc_status=rejected_implausible_factors"

        # 3) Fix 2: KEINE MG-Header bei Rejection — weder im Arbeits-FITS
        #    noch in der Rohkopie (Re-Run-Schutz)
        for f in (work_dir / "pcc_applied.fits", merged_dir / "pcc_applied.fits"):
            with fits.open(f) as hdul:
                assert "MGCNTGRP" not in hdul[0].header

        # 4) Persistenz: agent-log.yaml UND run-info.json (Critical-Luecke)
        arch_out = tmp_path / "archive"
        arch_out.mkdir(parents=True)
        archive = ArchiveAgent(output_root=arch_out, config=None)
        cal_ns = SimpleNamespace(master_dark=None, calibrated_lights=[])
        deb_ns = SimpleNamespace(debayered_frames=[], method="bilinear")

        log_path = archive._create_agent_log(
            arch_out, context, result, cal_ns,
            debayer_result=deb_ns,
            multi_group_metadata=result.multi_group_metadata,
        )
        run_info_path = archive._write_run_info(
            arch_out, context, proc_result=result,
            multi_group_metadata=result.multi_group_metadata,
        )

        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["pcc_status"] == "rejected_implausible_factors"
        data = json.loads(run_info_path.read_text(encoding="utf-8"))
        assert data["pcc_status"] == "rejected_implausible_factors"

    def test_apply_pcc_per_group_rejection_writes_no_mg_headers(self, tmp_path):
        """Fix 2a: apply_pcc_per_group schreibt bei Nicht-Erfolgsstatus
        KEINE MGCNTGRP/MGMETHOD-Header in pcc_applied.fits."""
        from astro_process.agents.multi_group_agent import apply_pcc_per_group
        from astro_process.config.models import MultiGroupConfig

        group_dir = tmp_path / "group_x"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True)
        stack = stacked_dir / "stacked.fits"
        fits.PrimaryHDU(np.ones((3, 8, 8), dtype=np.float32)).writeto(stack)

        def fake_wrapper(stacked, params, **kwargs):
            (stacked.parent / "PCC_STATUS.txt").write_text(
                "pcc_status=rejected_implausible_factors\n", encoding="utf-8")

        pcc_path, status = apply_pcc_per_group(
            stack, None, MultiGroupConfig(), group_dir,
            photometric_color_calibration_fn=fake_wrapper,
        )

        assert status == "rejected_implausible_factors"
        with fits.open(pcc_path) as hdul:
            assert "MGCNTGRP" not in hdul[0].header
            assert "MGMETHOD" not in hdul[0].header

    def test_apply_pcc_per_group_success_still_writes_mg_headers(self, tmp_path):
        """Fix 2 Regressionsschutz: gaia_success schreibt die MG-Marker-
        Header weiterhin (standalone merge bleibt funktionsfaehig)."""
        from astro_process.agents.multi_group_agent import apply_pcc_per_group
        from astro_process.config.models import MultiGroupConfig

        group_dir = tmp_path / "group_y"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True)
        stack = stacked_dir / "stacked.fits"
        fits.PrimaryHDU(np.ones((3, 8, 8), dtype=np.float32)).writeto(stack)

        def fake_wrapper(stacked, params, **kwargs):
            (stacked.parent / "PCC_STATUS.txt").write_text(
                "pcc_status=gaia_success\n", encoding="utf-8")

        pcc_path, status = apply_pcc_per_group(
            stack, None, MultiGroupConfig(), group_dir,
            photometric_color_calibration_fn=fake_wrapper,
            group_metadata={"frame_count": 5, "total_exposure": 75.0},
        )

        assert status == "gaia_success"
        with fits.open(pcc_path) as hdul:
            assert hdul[0].header["MGCNTGRP"] == 1
            assert hdul[0].header["MGMETHOD"] == "pcc"
            assert hdul[0].header["MGFRAME"] == 5

    def test_idempotency_rejection_marker_beats_mg_headers(self, tmp_path):
        """Fix 2b: Vorhandenes pcc_applied.fits MIT MGCNTGRP, aber
        Rejection-Marker vorhanden → Idempotenz-Check meldet rejected
        (Marker ist autoritativ, PCC läuft nicht erneut)."""
        from astro_process.agents.multi_group_agent import apply_pcc_per_group
        from astro_process.config.models import MultiGroupConfig

        group_dir = tmp_path / "group_z"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True)

        hdr = fits.Header()
        hdr["MGCNTGRP"] = 1  # Legacy-/fälschlicher Erfolgs-Marker
        hdr["MGMETHOD"] = "pcc"
        pcc_path = stacked_dir / "pcc_applied.fits"
        fits.PrimaryHDU(
            data=np.ones((3, 8, 8), dtype=np.float32), header=hdr
        ).writeto(pcc_path)
        (stacked_dir / "PCC_REJECTED_FACTORS.txt").write_text(
            "r=-9.73 g=0.27 b=-0.76\n", encoding="utf-8")
        stack = stacked_dir / "stacked.fits"
        fits.PrimaryHDU(np.ones((3, 8, 8), dtype=np.float32)).writeto(stack)

        def must_not_run(*args, **kwargs):
            raise AssertionError("PCC darf bei Rejection-Marker nicht erneut laufen")

        _, status = apply_pcc_per_group(
            stack, None, MultiGroupConfig(), group_dir,
            photometric_color_calibration_fn=must_not_run,
        )
        assert status == "rejected_implausible_factors"

    def test_cli_merge_metadata_marker_first(self, tmp_path):
        """Fix 2c: standalone `merge` liest Marker VOR MG-Headern — eine
        abgelehnte Gruppe wird nicht als gaia_success gemeldet."""
        from click.testing import CliRunner

        from astro_process.cli import cli  # click-Gruppe (nicht das Modul)

        ts_dir = tmp_path / "M92" / "generated" / "20260820-171059"
        groups = (("15s60", True), ("60s40", False))
        for name, was_rejected in groups:
            gd = ts_dir / f"group_{name}" / "04_stacked"
            gd.mkdir(parents=True)
            hdr = fits.Header()
            hdr["EXPTIME"] = 15.0 if was_rejected else 60.0
            hdr["GAIN"] = 60 if was_rejected else 40
            hdr["MGCNTGRP"] = 1  # beide haben MG-Header ...
            hdr["MGFRAME"] = 3
            fits.PrimaryHDU(
                data=np.ones((8, 8), dtype=np.float32), header=hdr
            ).writeto(gd / "pcc_applied.fits")
            if was_rejected:
                # ... aber nur die erste hat den autoritativen Marker
                (gd / "PCC_REJECTED_FACTORS.txt").write_text(
                    "r=-9.73 g=0.27 b=-0.76\n", encoding="utf-8")

        runner = CliRunner()
        with patch("astro_process.cli.MergeAgent") as MockMerge:
            MockMerge.return_value.run.return_value = SimpleNamespace(
                merged_path=None, preview_path=None)
            runner.invoke(cli, ["merge", str(tmp_path / "M92")])

            captured = MockMerge.return_value.run.call_args.kwargs
        meta = captured["group_metadata"]
        assert meta["15s60"]["pcc_status"] == "rejected_implausible_factors"
        assert meta["60s40"]["pcc_status"] == "gaia_success"
