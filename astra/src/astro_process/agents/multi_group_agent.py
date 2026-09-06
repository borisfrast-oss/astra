"""Multi-Group Processing — MultiGroupProcessor (Phase 2: T5–T8).

Refactor 2026-08-14 (Cluster 6): Ausgelagert aus
``astro_process/agents/processing_agent.py`` (ProcessingAgent-Methoden
``process_multi_group`` + Cross-Group-Helfer). Rein verschoben, KEINE
Verhaltensaenderung: Logik, Event-Namen, Report-Schemata und
Datei-Semantik identisch. Jede ausgelagerte Funktion traegt einen
``# Refactor: moved from processing_agent.py (Cluster 6)``-Marker.

V1.7-5 (Always Multi-Group): Es gibt keinen Single-Group-Fallback mehr —
genau 1 Gruppe laeuft durch denselben Pfad wie N Gruppen (Info-Log
``multi_group.single_group_unified`` dokumentiert das); der finale Stack
wird kanonisch nach ``merged/{safe_target}_merged.fits`` materialisiert.

Der Agent delegiert: ``ProcessingAgent.process_multi_group`` erzeugt einen
``MultiGroupProcessor`` und reicht seine Methoden als Callables durch
(``load_frame``/``save_frame``/``run_plugin_steps`` sowie die beiden
test-patchbaren Hooks ``_register_to_reference_stack``/
``_apply_pcc_per_group``).

Dieses Modul importiert NIE ``processing_agent`` (kein Import-Zyklus).
``ProcessingResult`` wird als ``processing_result_class``-Callable injiziert
(das Agent-Modul definiert die Klasse und reicht sie beim Konstruieren durch).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import structlog
from astropy.io import fits
from scipy.ndimage import gaussian_filter
from scipy.ndimage import shift as scipy_shift

from ..config.loader import (
    is_merge_filter_match,
    normalize_merge_filters,
    resolve_cfa_drizzle,
    resolve_export_config,
    resolve_preview_export_config,
)
from ..config.models import (
    CFADrizzleConfig,
    MultiGroupConfig,
    PipelinePreset,
)
from ..core.debayer import debayer_fits
from ..core.export import annotate_export_header, export_stretched_fits
from ..core.gradient_removal import background_extraction
from ..core.pcc import compute_pixel_scale, photometric_color_calibration
from ..core.preview import create_preview_jpg
from ..core.quality import (
    FrameQuality,
    qual_to_dict,
    summarize_qualities,
)
from ..core.registration import (
    AstroalignUnavailableError,
    RegistrationResult,
    RegistrationSanityError,
    RegistrationTransform,
    _apply_registration_transform,
    _corr_pearson,
    apply_rotation_shift,
    corr_grid_shift,
    create_registration,
    register_frames,
    select_registration_channel,
)
from ..core.selection import (
    _apply_selection_and_rejection,
    _resolve_frame_selection_config,
    _resolve_min_corr_hp_config,
    _resolve_rejection_config,
)
from ..core.stacking import stack_frames
from ..models.core import GroupInfo, ObservationContext, compute_group_hash
from .cross_group import (
    apply_cross_group_skip_filter,
    apply_pcc_per_group,
    cleanup_group_dirs,
    compute_group_signal_scores,
    consolidate_eqmode_values,
    quality_winner_if_any,
    select_reference_group,
    signal_winner_if_any,
)

if TYPE_CHECKING:
    from ..agents.merge_agent import MergeAgent

logger = structlog.get_logger(__name__)


def build_reference_selection(
    groups: dict[str, GroupInfo],
    strategy: str,
    ref_hash: str,
    group_stacks: dict[str, Path],
    registration_metrics: dict[str, dict] | None = None,
    *,
    logger=None,
) -> dict:
    """CR-001 W14 (AC-W14-2) + V1.3-5: Referenz-Wahl im Report dokumentieren.

    Sektion `reference_selection`: {method, group, signal_scores?,
    quality_scores?}.
    method: "signal" | "quality" | "frame_count" | "user".
      "signal"      — Signal-basierte Wahl (oder intern auf
                      meiste-Frames gefallen, siehe group/fallback_reason).
      "quality"     — Registrierungs-Qualitäts-Wahl (V1.3-5, Default);
                      quality_scores dokumentiert je Gruppe
                      zero_shift_ratio/n_control_points_median/
                      corr_hp_median/frames_registered (deterministisch
                      sortiert). Fallback-reasons: "no_metrics" (Metriken
                      fehlten → largest) | "no_candidates" (keine Gruppe
                      mit frames_registered >= 3 → largest).
      "frame_count" — meiste-Frames-Regel (Config "largest" oder Fallback).
      "user"        — manuelle Übersteuerung per Config (Hash).
    fallback_reason (optional): "no_stacks" | "degenerate_signal" |
    "user_group_failed" | "no_metrics" | "no_candidates" — nur bei
    tatsächlichem Fallback.

    Refactor: moved from ``ProcessingAgent._build_reference_selection``
    (Cluster 6, unveraendert — Modul-Funktion statt Methode).

    Args:
        groups: Dict mapping group hash → GroupInfo.
        strategy: Konfigurierte Referenz-Strategie.
        ref_hash: Effektiv gewählte Referenz (nach allen Fallbacks).
        group_stacks: {group_hash: stacked.fits path}.
        registration_metrics: {group_hash: Metriken-Dict} (V1.3-3) —
                  für strategy == "quality" (None/leer → Fallback-Reason
                  "no_metrics" im Report).
        logger: Optional structlog-Logger (Agent reicht seinen durch).

    Returns:
        Report-Sektion dict.
    """
    log = logger or structlog.get_logger(__name__)
    sel: dict = {"method": "frame_count", "group": ref_hash, "signal_scores": {}}

    if strategy in groups:
        # Manuelle Übersteuerung (AC-W14-1)
        if strategy == ref_hash:
            sel["method"] = "user"
        else:
            sel["method"] = "frame_count"
            sel["fallback_reason"] = "user_group_failed"
        return sel

    if strategy == "quality":
        sel["method"] = "quality"
        metrics_by_group = registration_metrics or {}
        # quality_scores je Gruppe (dokumentiert; deterministisch
        # sortiert wie signal_scores). Gerundete Werte; fehlende Felder
        # (Legacy) als None dokumentiert.
        quality_scores: dict[str, dict] = {}
        for gh in sorted(metrics_by_group):
            m = metrics_by_group[gh] or {}
            frames_registered = int(m.get("frames_registered") or 0)
            zero_shift_count = int(m.get("zero_shift_count") or 0)
            zero_shift_ratio = zero_shift_count / max(frames_registered, 1)
            cp = m.get("n_control_points") or {}
            cp_median = cp.get("median")
            hp = m.get("corr_hp") or {}
            hp_median = hp.get("median")
            quality_scores[gh] = {
                "zero_shift_ratio": round(zero_shift_ratio, 6),
                "n_control_points_median": (
                    round(float(cp_median), 1)
                    if cp_median is not None else None
                ),
                "corr_hp_median": (
                    round(float(hp_median), 4)
                    if hp_median is not None else None
                ),
                "frames_registered": frames_registered,
            }
        sel["quality_scores"] = quality_scores
        if not any(metrics_by_group.values()):
            # V1.3-5: Metriken fehlten (Legacy/Mocks/Dry-Run) →
            # select_reference_group fiel intern auf largest; method
            # bleibt "quality" (gewählte Strategie), der Fallback ist
            # über fallback_reason + quality_scores sichtbar.
            sel["fallback_reason"] = "no_metrics"
        else:
            winner = quality_winner_if_any(
                groups, group_stacks, metrics_by_group,
            )
            if winner != ref_hash:
                sel["fallback_reason"] = "no_candidates"
        return sel

    if strategy == "signal":
        sel["method"] = "signal"
        scores: dict[str, float] = {}
        try:
            scores = compute_group_signal_scores(group_stacks, logger=log)
            sel["signal_scores"] = {
                k: round(v, 6) for k, v in sorted(scores.items())
            }
        except Exception as e:
            log.warning("multi_group.reference_signal_scores_failed",
                        error=str(e))
        # Degenerierter Fall (kein Stack / gleiche Score / keine
        # Kandidaten): select_reference_group fiel intern auf
        # meiste-Frames zurück — method bleibt "signal" (die gewählte
        # Strategie), group zeigt die effektive Gruppe; der Fallback ist
        # über fallback_reason + signal_scores sichtbar.
        if not group_stacks:
            sel["fallback_reason"] = "no_stacks"
        else:
            winner = signal_winner_if_any(
                groups, group_stacks, scores,
            )
            if winner != ref_hash:
                sel["fallback_reason"] = "degenerate_signal"
        return sel

    # "largest" oder unbekannte Strategie (bereits gefallbackt)
    return sel


# ═════════════════════════════════════════════════════════════════════
# Cross-Group Registration (Refactor: moved from processing_agent.py,
# Cluster 6 — ProcessingAgent._register_to_reference_stack/_copy_wcs_headers)
# ═══════════════════════════════════════════════════════════════════


def copy_wcs_headers(
    source_path: Path, target_path: Path, rotation_deg: float = 0.0,
    *,
    logger=None,
) -> None:
    """Copy WCS header keywords from source FITS to target FITS.

    V1.5-4 / DADR-014 (REG_ROT): bei rotation_deg != 0 wird die
    Provenienz-Rotation als separates Keyword ``REG_ROT`` (Grad) in den
    FITS-Header geschrieben — NICHT in der CD-Matrix. Das WCS bleibt
    sauber (CDELT-only = tatsaechliche Pixel-Skalierung), damit
    Platesolving, Annotation und Mosaik ohne verdrehte Himmelspositionen
    funktionieren.

    Test-Invariante: rotation_deg = 0 -> identisches Verhalten wie bisher
    (CDELT-Kopie, kein REG_ROT). Fehlt die CDELT-Basis in der Quelle:
    REG_ROT wird trotzdem gesetzt (best effort, Fehler -> Warning
    pipeline.wcs_copy_failed, unveraenderter Header).

    Refactor: moved from ``ProcessingAgent._copy_wcs_headers``
    (Cluster 6, unveraendert — Modul-Funktion statt @staticmethod).

    Args:
        source_path: FITS with authoritative WCS (reference stack)
        target_path: FITS to update (aligned stack)
        rotation_deg: Rotation in Grad, die auf die Stack-Pixel angewendet
            wurde (0.0 = keine Rotation -> CDELT wie bisher).
        logger: Optional structlog-Logger (Agent reicht seinen durch).
    """
    log = logger or structlog.get_logger(__name__)
    wcs_keys = [
        "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2",
        "CDELT1", "CDELT2", "CTYPE1", "CTYPE2",
        "CUNIT1", "CUNIT2",
    ]
    try:
        with fits.open(source_path) as src:
            src_header = src[0].header
            with fits.open(target_path, mode='update') as tgt:
                header = tgt[0].header
                for key in wcs_keys:
                    if key in src_header:
                        header[key] = src_header[key]
                # V1.5-4 / DADR-014: Provenienz-Rotation als separates
                # Keyword REG_ROT statt CD-Matrix. WCS bleibt CDELT-only
                # (semantisch korrekt: CDELT = Pixel-Skalierung, kein
                # Rotation-Claim in der CD-Matrix).
                if rotation_deg != 0.0:
                    header["REG_ROT"] = float(rotation_deg)
                    header.add_comment(
                        "REG_ROT: registration rotation "
                        f"{rotation_deg:.4f} deg (DADR-014, V1.5-4)"
                    )
    except Exception as e:
        log.warning("pipeline.wcs_copy_failed", error=str(e))


def register_to_reference_stack(
    stack_path: Path, ref_stack_path: Path,
    filter_name: str, output_dir: Path,
    *,
    load_frame,
    save_frame,
    logger=None,
    params: dict | None = None,
    eq: bool | None = None,
) -> RegistrationResult:
    """Register a group stack to a reference stack (cross-group, stack-level).

    W1: Shift-Berechnung auf HOCHPASS (mono − gaussian_filter(mono, 30.0))
    statt Rohdaten — korrelationsbasierte Grob-zu-Fein-Suche
    (_corr_grid_shift, Methode B). FFT-Phase-Correlation auf Rohdaten war
    der Root-Cause (F2/M13-Ghosting): sie lockt auf das dominante
    Grossstruktur-Muster (Hintergrund/Vignettierung, zwischen Nächten
    verschoben). Star-Centroiding wird für Cross-Group nicht mehr genutzt.
    Intra-group registration (_register_frames) nutzt seit W11 dieselbe
    Hochpass+Grid-Methode (_corr_grid_shift) — _compute_shift_star_centroid
    hat keinen aktiven Aufrufer mehr (bleibt als Referenz).
    W1 Zero-Shift-Fallback: corr_hp < konfigurierter Schwelle (Default
    0.0) → Shift (0,0) + status warning (Gruppen sind im Normalfall
    ~aligniert; ein schlechter Peak ist gefährlicher als Zero-Shift).
    KEIN Skip (Abgrenzung W3).
    W2 QC: corr_hp (Hochpass, post-shift) ist die Hauptmetrik und
    klassifiziert status (ok/warning, Schwelle 0.3); correlation/corr_roh
    (Roh-Mono, post-shift) bleibt als Diagnosefeld im Report.
    W12 (AC-W12-1): corr_hp/corr_roh werden auf dem G-Kanal gemessen
    (höchste QE bei OSC), Schwellen unverändert (AC-W12-2).
    max_shift-Validierung (max(shape)//4) bleibt als Sicherheitsnetz.
    Uses mode='nearest' for scipy shift (hal AQ5 — avoids sharp edges from
    negative calibrated pixels).

    V1.3-5-Hinweis: Die Cross-Group-Registration nutzt bei
    astroalign-Fehlschlag einen Translation-only-Fallback (fft-Shift —
    Rotation bleibt 0.0, Scale 1.0). V1.4-2: Bei method="rotation_fft"
    (oder als zusaetzliche Fallback-Stufe bei method="astroalign" wenn
    astroalign nicht gewinnt) wird die Rotation per Log-Polar-FFT
    (RotationFftRegistration) geschaetzt und angewendet; die WCS-
    Persistierung erfolgt via CD-Matrix statt CDELT (copy_wcs_headers,
    V1.4-2).

    Refactor: moved from ``ProcessingAgent._register_to_reference_stack``
    (Cluster 6, unveraendert — Modul-Funktion statt Methode; Frame-I/O
    ueber die Callables ``load_frame``/``save_frame``).

    Args:
        stack_path: Path to the group stack to register
        ref_stack_path: Path to the reference stack
        filter_name: Filter name for channel selection
        output_dir: Directory to save the aligned stack
        load_frame: Callable Path -> RGB array (H×W×C).
        save_frame: Callable (array, Path) -> None.
        logger: Optional structlog-Logger (Agent reicht seinen durch).
        params: Processing params (ProcessingParams.model_dump()); die
            `registration`-Sektion steuert die Methode (AC-W9-D1). None
            oder fehlende Sektion -> "fft" (v1.1-Verhalten, AC-W9-D3/C5).
        eq: EQ-Modus der Ziel-Gruppe (V1.4-20, additiv): True=EQ,
            False=AZ, None=unbekannt. Steuert die `unexpected_rotation`-
            Diagnose (nur bei EQ ist eine grobe Cross-Group-Rotation
            unerwartet — AZ hat Feldrotation).

    Returns:
        RegistrationResult with aligned FITS path, shift, post-shift
        corr_hp/correlation, ok/warning status, status_reasons
        (V1.4-20) and W9-D2-Metadaten
        (method/rotation_deg/scale/n_control_points).
    """
    log = logger or structlog.get_logger(__name__)
    # Load both stacks (float32, H×W×C)
    stack_data = load_frame(stack_path)
    ref_data = load_frame(ref_stack_path)

    # Select mono channels for registration
    if stack_data.ndim == 3 and stack_data.shape[-1] == 3:
        stack_mono, _ = select_registration_channel(stack_data, filter_name)
        ref_mono, _ = select_registration_channel(ref_data, filter_name)
    else:
        # Already 2D (e.g., calibrated-only, no debayer)
        stack_mono = stack_data
        ref_mono = ref_data

    # W9-D (AC-W9-D1/D4, ADR-022): Registrations-Strategie wie S1-A7.
    # method="fft" (Default) -> FftGridRegistration kapselt
    # _corr_grid_shift UNVERAENDERT (AC-W9-C5, byte-identisch).
    # method="astroalign" -> Strategy auf dem W11-Hochpass-Mono, mit
    # Compute-both-Arbitration + Fallback identisch AC-W9-C3.
    # method="rotation_fft" (V1.4-2) -> RotationFftRegistration
    # (Log-Polar-FFT) mit Compute-both-Arbitration gegen fft (Gewinn
    # nur bei corr_hp_rot >= corr_hp + 0.02, sonst fft-Shift).
    reg_cfg = (params or {}).get("registration", {}) or {}
    reg_method = reg_cfg.get("method", "fft") or "fft"
    strategy = create_registration(
        reg_method,
        reg_cfg.get("max_control_points"),
        grid_shift_fn=corr_grid_shift,
        max_rotation_deg=reg_cfg.get("max_rotation_deg", 2.0),
        max_scale_dev=reg_cfg.get("max_scale_dev", 0.02),
    )
    # available() emittiert die einmalige astroalign_unavailable-Warning,
    # wenn das Extra fehlt (nur wenn method == "astroalign" geprueft wird).
    use_astroalign = reg_method == "astroalign" and strategy.available()
    # V1.4-2: rotation_fft als gewaehlte Methode (immer) oder als
    # zusaetzliche Fallback-Stufe bei method="astroalign" (nur wenn
    # astroalign nicht gewinnt -> winner bleibt "fft").
    use_rotation_fft = reg_method == "rotation_fft"
    rotation_fft_fallback = reg_method == "astroalign"

    # RE-F (V1.3-24, AC-RE-F3) + V19-FIX-12 P1 Mandatory Gate 0.05:
    # Default 0.05 = Guard aktiv (entkoppelt von frame_selection.enabled),
    # Fallback/Reject greift bei corr_hp < 0.05 (V1.8-8 DEF-006, V19-FIX-12).
    zero_shift_threshold = float(reg_cfg.get("zero_shift_threshold", 0.05))
    zero_shift_fallback_enabled = bool(reg_cfg.get("zero_shift_fallback", True))

    # CR-001 P3-M1 (ray follow-up): Shape-Mismatch-Guard. Abweichende
    # Mono-Shapes würden _compute_shift (nutzt ref.shape für h/w) mit einem
    # rohen Broadcasting-/FFT-Fehler crashen lassen (z.B. gemischtes Binning).
    # Guard: Zero-Shift + status "warning" + gültiges RegistrationResult,
    # PCC-/Corr-Berechnung übersprungen (aligned = Zero-Shift-Kopie).
    # win_transform = Gewinner-Transform (astroalign/rotation_fft) fuer
    # Reject-/Apply-/Log-/Return-/WCS-Pfade; None bei fft/Guards.
    win_transform: RegistrationTransform | None = None
    if stack_mono.shape != ref_mono.shape:
        log.warning("registration.shape_mismatch",
                    stack_shape=list(stack_mono.shape),
                    ref_shape=list(ref_mono.shape),
                    action="zero_shift_warning")
        shift_y, shift_x = 0.0, 0.0
        corr_roh = 0.0
        corr_hp = 0.0
        status = "warning"
        status_reasons: list[str] = []  # V1.4-20 (additiv; Guard-Fall)
        # Zero-Shift-Kopie: aligned bleibt der unveränderte Stack
        aligned = stack_data
        # W9-D (AC-W9-D2): Guard-Fall zaehlt als fft (kein astroalign-
        # Transform berechnet) — method-Feld im Report bleibt "fft".
        winner = "fft"
    else:
        # W1: Shift-Berechnung auf Hochpass statt Rohdaten (F2-Root-Cause).
        # gaussian_filter(mono, 30.0) entfernt das dominante Grossstruktur-
        # Muster (Hintergrundgradient/Vignettierung, zwischen Nächten
        # verschoben) — darauf lockte der alte PCC (falsche Peaks, M13-
        # Ghosting). Referenz/Beweis: _work/stella/diag-m13-real-stacks.py.
        ref_hp = ref_mono - gaussian_filter(ref_mono, 30.0)
        stack_hp = stack_mono - gaussian_filter(stack_mono, 30.0)

        # Methode B (W1, Empfehlung): korrelationsbasierte Grob-zu-Fein-
        # Suche (mehrstufig, _corr_grid_shift), Kriterium corr_hp. Liefert
        # die Ground-Truth auf den M13-Stacks (0.75-Beweis).
        _search_corr, shift_y, shift_x = corr_grid_shift(ref_hp, stack_hp)

        # Validate shift: fallback to no-shift if unreasonable
        max_shift = max(ref_mono.shape) // 4
        if abs(shift_y) > max_shift or abs(shift_x) > max_shift:
            log.warning("registration.shift_too_large",
                        shift_y=round(shift_y, 3), shift_x=round(shift_x, 3),
                        max_shift=max_shift, fallback="no_shift")
            shift_y, shift_x = 0.0, 0.0

        # W12 (AC-W12-1): QC auf G-Kanal statt Luminance — corr_hp/corr_roh
        # werden auf dem G-Kanal gemessen (höchste QE bei OSC; Luminance
        # verwässert durch schwächere R/B-Kanäle; stella G.3: G 0.111 vs.
        # Luminance 0.0995 bei (0,0) auf 180s60). Die Shift-Berechnung
        # bleibt auf dem Registrations-Mono (Luminance für broadband) —
        # nur die QC-Messung nutzt G. Für 2D (kein Debayer) ist Mono das
        # G-Äquivalent.
        if stack_data.ndim == 3 and stack_data.shape[-1] == 3:
            g_stack = stack_data[:, :, 1]
            g_ref = ref_data[:, :, 1]
        else:
            g_stack = stack_mono
            g_ref = ref_mono

        if shift_y != 0.0 or shift_x != 0.0:
            g_aligned = scipy_shift(g_stack, (shift_y, shift_x),
                                    order=3, mode="nearest")
        else:
            g_aligned = g_stack
        corr_hp = _corr_pearson(
            g_aligned - gaussian_filter(g_aligned, 30.0),
            g_ref - gaussian_filter(g_ref, 30.0),
        )
        corr_roh = _corr_pearson(g_aligned, g_ref)

        # W9-D4 (AC-W9-C3): Compute-both-Arbitration identisch zur
        # Intra-Group (S1-A7). Bei method="astroalign" wird der
        # astroalign-Transform auf dem Hochpass-Mono berechnet und gegen
        # den fft-Transform auf dem G-Kanal-Hochpass verglichen (beide
        # Transforms anwenden, corr_hp messen): astroalign gewinnt nur bei
        # corr_hp_aa >= corr_hp_fft - 0.05 (Toleranz RANSAC-Jitter),
        # sonst fft + Warning registration.astroalign_downgraded.
        # Fallback-Warnings kommen aus der Strategie (astroalign_fallback /
        # astroalign_sanity_rejected / astroalign_unavailable einmalig).
        winner = "fft"
        aa_transform: RegistrationTransform | None = None
        rot_transform: RegistrationTransform | None = None
        if use_astroalign:
            corr_hp_aa = -1e9
            try:
                aa_transform = strategy.compute(ref_hp, stack_hp)
                g_aligned_aa = _apply_registration_transform(
                    g_stack, aa_transform.transform, g_ref,
                )
                corr_hp_aa = _corr_pearson(
                    g_aligned_aa - gaussian_filter(g_aligned_aa, 30.0),
                    g_ref - gaussian_filter(g_ref, 30.0),
                )
            except (AstroalignUnavailableError, RegistrationSanityError):
                # Warnings kamen bereits aus der Strategie; fft gewinnt.
                aa_transform = None
            except Exception:  # noqa: BLE001 - unbekannte astroalign-Fehler -> fft
                aa_transform = None
            if aa_transform is not None and corr_hp_aa >= corr_hp - 0.05:
                winner = "astroalign"
                shift_y, shift_x = aa_transform.shift_y, aa_transform.shift_x
                corr_hp = corr_hp_aa
            elif aa_transform is not None:
                log.warning(
                    "registration.astroalign_downgraded",
                    stack=str(stack_path.name),
                    corr_hp_aa=round(corr_hp_aa, 3),
                    corr_hp_fft=round(corr_hp, 3),
                    tolerance=0.05,
                )

        # V1.4-2 (Rotation-FFT): Compute-both-Arbitration gegen fft.
        # Aktivierung: method == "rotation_fft" (immer) ODER
        # method == "astroalign" als zusaetzliche Fallback-Stufe, wenn
        # astroalign nicht gewonnen hat (winner == "fft"; V1.3-5-Hinweis:
        # Translation-only-Fallback -> verdrehtes Merge-Bild bei
        # AZ-Feldrotation). rotation_fft gewinnt NUR bei
        # corr_hp_rot >= corr_hp + 0.02 (deutliche Verbesserung gegenueber
        # dem fft-Shift — der fft-Pfad ist die sichere Baseline; die
        # Strategie verwarf unplausible Transforms bereits per
        # Sanity-Guard) und status "ok".
        if use_rotation_fft or (rotation_fft_fallback and winner == "fft"):
            corr_hp_rot = -1e9
            try:
                rot_strategy = create_registration(
                    "rotation_fft",
                    grid_shift_fn=corr_grid_shift,
                    max_rotation_deg=reg_cfg.get("max_rotation_deg", 2.0),
                    max_scale_dev=reg_cfg.get("max_scale_dev", 0.02),
                )
                rot_transform = rot_strategy.compute(ref_hp, stack_hp)
                g_aligned_rot = apply_rotation_shift(
                    g_stack, rot_transform.rotation_deg,
                    rot_transform.shift_y, rot_transform.shift_x,
                )
                corr_hp_rot = _corr_pearson(
                    g_aligned_rot - gaussian_filter(g_aligned_rot, 30.0),
                    g_ref - gaussian_filter(g_ref, 30.0),
                )
            except RegistrationSanityError:
                # Warning kam aus der Strategie; fft gewinnt.
                rot_transform = None
            except Exception:  # noqa: BLE001 - unbekannte rotation_fft-Fehler -> fft
                rot_transform = None
            if rot_transform is not None and corr_hp_rot >= corr_hp + 0.02:
                winner = "rotation_fft"
                shift_y, shift_x = rot_transform.shift_y, rot_transform.shift_x
                corr_hp = corr_hp_rot
            elif rot_transform is not None:
                log.warning(
                    "registration.rotation_fft_downgraded",
                    stack=str(stack_path.name),
                    corr_hp_rot=round(corr_hp_rot, 3),
                    corr_hp_fft=round(corr_hp, 3),
                    tolerance=0.02,
                )

        # Gewinner-Transform fuer Reject-/Apply-/Log-/Return-Pfade
        # (V1.4-2: rot_transform oder aa_transform, je nach winner).
        win_transform = (
            aa_transform if winner == "astroalign"
            else rot_transform if winner == "rotation_fft"
            else None
        )

        # W1 Zero-Shift-Guard (AC-W11-2) — RE-F (V1.3-24, AC-RE-F1/F2):
        # methodenbewusst, analog zur Intra-Group-Stelle. corr_hp
        # (G-Kanal, post-shift) < Schwelle (Default 0.0):
        #   fft-Zweig          -> Shift (0,0) + zero_shift_fallback (v1.2)
        #   astroalign-/rotation_fft-Gewinner -> Stack VERWERFEN
        #       (status "rejected"):
        #       kein (0,0)-Transform, kein zero_shift_fallback-Event;
        #       der Aufrufer schliesst den Stack aus dem Merge aus
        #       (R1-Semantik auf Stack-Ebene: "verwerfen" = kein
        #       Merge-Beitrag; Stacks bleiben unaligniert unter
        #       group_*/04_stacked/ erhalten).
        # AC-RE-F3: --zero-shift-threshold / --no-zero-shift-fallback
        # wirken identisch zur Intra-Group-Stelle.
        if zero_shift_fallback_enabled and corr_hp < zero_shift_threshold:
            if winner == "fft":
                log.warning("registration.zero_shift_fallback",
                            stack=str(stack_path.name),
                            corr_hp=round(corr_hp, 3),
                            threshold=zero_shift_threshold,
                            reason="low_hp_correlation")
                shift_y, shift_x = 0.0, 0.0
                winner = "fft"
                # QC bei (0,0) neu messen (konsistent: post-shift corr_hp)
                corr_hp = _corr_pearson(
                    g_stack - gaussian_filter(g_stack, 30.0),
                    g_ref - gaussian_filter(g_ref, 30.0),
                )
                corr_roh = _corr_pearson(g_stack, g_ref)
            else:
                # astroalign-/rotation_fft-Gewinner (AC-RE-F1): Stack
                # verwerfen statt zeroshift-stapeln — UGC-10822-Beleg
                # (Frames 1-23 mit corr_hp_aa 0.14-0.29 trotz gültigem
                # astroalign-Transform). RegistrationResult mit
                # status="rejected"; path zeigt auf den unalignierten
                # Original-Stack (Marker: kein aligned.fits erzeugt; der
                # Aufrufer nimmt die Gruppe nicht in aligned_stacks auf).
                log.warning(
                    "registration.stack_rejected",
                    stack=str(stack_path.name),
                    corr_hp=round(corr_hp, 3),
                    threshold=zero_shift_threshold,
                    reason=(
                        f"{winner} winner below zero-shift threshold "
                        "(RE-F): low corr_hp on G-channel — stack "
                        "excluded from merge"
                    ),
                )
                return RegistrationResult(
                    path=stack_path,
                    shift_y=win_transform.shift_y if win_transform else 0.0,
                    shift_x=win_transform.shift_x if win_transform else 0.0,
                    correlation=corr_roh,
                    corr_hp=corr_hp,
                    status="rejected",
                    method=winner,
                    rotation_deg=(
                        win_transform.rotation_deg if win_transform else 0.0
                    ),
                    scale=win_transform.scale if win_transform else 1.0,
                    n_control_points=(
                        win_transform.n_control_points if win_transform else None
                    ),
                )

        # Apply: rotation_fft -> Rotation + Shift via apply_rotation_shift
        # (V1.4-2); astroalign-Transform als Ganzes (ADR-020-Falle b/c,
        # pro Kanal via Helper); sonst fft-Shift (unverändert, mode='nearest'
        # hal AQ5 — avoids cval=0.0 edge artifacts).
        if winner == "rotation_fft":
            aligned = apply_rotation_shift(
                stack_data, rot_transform.rotation_deg,
                rot_transform.shift_y, rot_transform.shift_x,
            )
        elif winner == "astroalign":
            aligned = _apply_registration_transform(
                stack_data, aa_transform.transform, g_ref,
            )
        else:
            shift_vec = (shift_y, shift_x) + (0,) * (stack_data.ndim - 2)
            aligned = scipy_shift(stack_data, shift_vec, order=3, mode='nearest')

        # W2 QC (AC-W2-1/2): status aus corr_hp (G-Kanal, Schwelle 0.3);
        # corr_roh bleibt Diagnosefeld im Report.
        # V1.4-20 (LDN 935): corr_hp allein kann eine falsche
        # Transformation durchlassen (corr_hp 0.538, aber corr_roh 0.005,
        # n_CP 23, Rotation 2.26° bei EQ). status_reasons dokumentiert
        # die zusaetzlichen Qualitaetsgruende additiv (status bleibt
        # rueckwaertskompatibel corr_hp-basiert; die Ausschluss-
        # Entscheidung faellt im W3-Gate apply_cross_group_skip_filter).
        qc_rotation_deg = (
            win_transform.rotation_deg
            if winner in ("rotation_fft", "astroalign") and win_transform
            else 0.0
        )
        qc_n_cp = (
            win_transform.n_control_points
            if winner in ("rotation_fft", "astroalign") and win_transform
            else None
        )
        status_reasons: list[str] = []
        if corr_roh < 0.05:
            status_reasons.append("low_corr_roh")
        if qc_n_cp is not None and qc_n_cp < 30:
            status_reasons.append("few_control_points")
        if eq is True and abs(qc_rotation_deg) > 1.0:
            status_reasons.append("unexpected_rotation")
        status = "ok" if corr_hp >= 0.3 else "warning"
        log.info("registration.cross_group_qc",
                 shift_y=round(shift_y, 3), shift_x=round(shift_x, 3),
                 corr_hp=round(corr_hp, 3), corr_roh=round(corr_roh, 3),
                 status=status,
                 status_reasons=status_reasons or None,
                 qc_channel="G", method=winner)
        if corr_hp < 0.3:
            log.warning("registration.qc_low",
                        corr_hp=round(corr_hp, 3), threshold=0.3,
                        action="proceed_with_warning")
        elif corr_hp < 0.5:
            log.info("registration.qc_acceptable",
                     corr_hp=round(corr_hp, 3), threshold=0.5)

        # W9-D2 (AC-W9-D2, OQ-W9-5): Transform-Metadaten pro Stack
        # (tatsächlich verwendete Methode — diagnostizierbar im Mixed-Run).
        if winner == "rotation_fft":
            log.info(
                "registration.transform",
                stack=str(stack_path.name),
                method=winner,
                rotation_deg=round(rot_transform.rotation_deg, 4),
                scale=round(rot_transform.scale, 5),
                shift_y=round(shift_y, 3),
                shift_x=round(shift_x, 3),
                n_control_points=None,
            )
        elif winner == "astroalign":
            log.info(
                "registration.transform",
                stack=str(stack_path.name),
                method=winner,
                rotation_deg=round(aa_transform.rotation_deg, 4),
                scale=round(aa_transform.scale, 5),
                shift_y=round(shift_y, 3),
                shift_x=round(shift_x, 3),
                n_control_points=aa_transform.n_control_points,
            )
        else:
            log.info(
                "registration.transform",
                stack=str(stack_path.name),
                method="fft",
                rotation_deg=0.0,
                scale=1.0,
                shift_y=round(shift_y, 3),
                shift_x=round(shift_x, 3),
                n_control_points=None,
            )

    # Save aligned stack
    output_dir.mkdir(parents=True, exist_ok=True)
    aligned_path = output_dir / "aligned.fits"
    save_frame(aligned, aligned_path)

    # Copy WCS headers from reference to aligned stack. V1.5-4 / DADR-014:
    # bei Rotation (rotation_fft/astroalign-Gewinn) wird REG_ROT (Grad)
    # als separates Keyword gesetzt — WCS bleibt CDELT-only (keine
    # CD-Matrix), damit Platesolving funktioniert.
    winner_rotation_deg = (
        win_transform.rotation_deg
        if winner in ("rotation_fft", "astroalign") and win_transform
        else 0.0
    )
    copy_wcs_headers(ref_stack_path, aligned_path, rotation_deg=winner_rotation_deg, logger=log)

    log.info("registration.cross_group_complete",
             stack=str(stack_path.name), ref=str(ref_stack_path.name),
             output=str(aligned_path.name), shift=(round(shift_y, 3), round(shift_x, 3)),
             method=winner)
    return RegistrationResult(
        path=aligned_path,
        shift_y=shift_y,
        shift_x=shift_x,
        correlation=corr_roh,
        corr_hp=corr_hp,
        status=status,
        status_reasons=status_reasons,
        method=winner,
        rotation_deg=(
            win_transform.rotation_deg
            if winner in ("rotation_fft", "astroalign") and win_transform
            else 0.0
        ),
        scale=(
            win_transform.scale
            if winner in ("rotation_fft", "astroalign") and win_transform
            else 1.0
        ),
        n_control_points=(
            win_transform.n_control_points
            if winner in ("rotation_fft", "astroalign") and win_transform
            else None
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# Per-Group PCC (T6) + Cleanup (Refactor: moved from processing_agent.py,
# Cluster 6 — ProcessingAgent._apply_pcc_per_group/_cleanup_group_dirs)
# ═══════════════════════════════════════════════════════════════════
# NOW IMPORTED FROM .cross_group (V1.7-7 Split Step 2b):
#   apply_pcc_per_group, cleanup_group_dirs, PCC_NON_SUCCESS_STATUSES


# ═══════════════════════════════════════════════════════════════════
# MultiGroupProcessor — Kern-Klasse (Phase 2 — T5–T8)
# ═══════════════════════════════════════════════════════════════════


class MultiGroupProcessor:
    """Multi-Group-Stacking (Phase 2 — T5–T8) — Kern-Logik.

    Refactor 2026-08-14 (Cluster 6): aus ``ProcessingAgent``
    (``astro_process/agents/processing_agent.py``) ausgelagert; der Agent
    delegiert ``process_multi_group`` hierher. Dieses Modul importiert NIE
    ``processing_agent`` (kein Import-Zyklus) — Daten/Callables werden
    explizit injiziert:

    - ``load_frame``/``save_frame``: Frame-I/O des Agents.
    - ``run_plugin_steps``: Plugin-Schritte auf dem finalen Merge.
    - ``processing_result_class``: ``ProcessingResult``-Klasse des Agents
      (das Modul darf den Agent nicht importieren).
    - ``register_to_reference_stack``/``apply_pcc_per_group``:
      ``select_reference_group``: optionale Hooks (der Agent reicht seine
      Methoden durch; Tests patchen diese auf dem Agent) — ohne Hook nutzt
      der Processor seine eigenen Delegationen auf die Modul-Funktionen.
    """

    def __init__(
        self,
        working_dir: Path,
        config,
        *,
        load_frame,
        save_frame,
        run_plugin_steps,
        processing_result_class,
        select_reference_group=None,
        register_to_reference_stack=None,
        apply_pcc_per_group=None,
        has_plugin_steps=None,
        logger=None,
    ):
        self.working_dir = Path(working_dir)
        self.config = config
        self.load_frame = load_frame
        self.save_frame = save_frame
        self.run_plugin_steps = run_plugin_steps
        self.processing_result_class = processing_result_class
        self.logger = logger or structlog.get_logger(__name__)

        # Fix-Sammlung v1.3 §3 (P0): optionaler Hook (Callable pipeline ->
        # bool), der dem Processor mitteilt, ob der Preset Plugin-Steps
        # enthaelt. Nur dann wird der gemergte Stack fuer die Plugin-Input-
        # Konvention (SE-B2) als Root-`04_stacked/stacked.fits` materialisiert
        # (Root-Ordner werden im Multi-Group-Modus NICHT mehr in
        # ProcessingAgent.__init__ angelegt). None = Default (unbedingt
        # materialisieren, bisheriges Verhalten fuer Direkt-Nutzer/Tests).
        self.has_plugin_steps = has_plugin_steps

        # V1.3-3-Semantik: Zustands-Attribute analog ProcessingAgent —
        # werden waehrend des Laufs befuellt und vom Agent zurueck-
        # uebernommen (Restaurierung der _last_*-Attribute).
        self.registered_dir = self.working_dir / "03_registered"
        self.stacked_dir = self.working_dir / "04_stacked"
        self.last_frame_qualities: list[FrameQuality] = []
        self.last_frame_rejected = 0
        self.last_registration_metrics: dict = {}
        # ray Review Fix 1 (2026-08-21): PCC-Status des MERGED-Pfad-Laufs
        # (pcc_per_group=False). Der Return von _apply_pcc_per_group wurde
        # previously verworfen -> pcc_status blieb "pending" und erreichte
        # agent-log.yaml/run-info.json nie (z.B. rejected_implausible_factors).
        self.last_merged_pcc_status: str | None = None

        # Test-/Hook-Pfad: Der Agent reicht seine (ggf. gepatchten)
        # Methoden durch; die Instanz-Attribute schatten die Klassen-
        # Methoden (Python-Idiom), sodass process_multi_group den Hook
        # statt der eigenen Delegation nutzt.
        if select_reference_group is not None:
            self._select_reference_group = select_reference_group
        if register_to_reference_stack is not None:
            self._register_to_reference_stack = register_to_reference_stack
        if apply_pcc_per_group is not None:
            self._apply_pcc_per_group = apply_pcc_per_group

    # ── Dünne Delegationen auf die Modul-Funktionen ──────────

    def _select_reference_group(
        self,
        groups: dict[str, GroupInfo],
        strategy: str = "largest",
        group_stacks: dict[str, Path] | None = None,
        registration_metrics: dict[str, dict] | None = None,
    ) -> str:
        return select_reference_group(
            groups, strategy, group_stacks, registration_metrics,
            logger=self.logger,
        )

    def _build_reference_selection(
        self,
        groups: dict[str, GroupInfo],
        strategy: str,
        ref_hash: str,
        group_stacks: dict[str, Path],
        registration_metrics: dict[str, dict] | None = None,
    ) -> dict:
        return build_reference_selection(
            groups, strategy, ref_hash, group_stacks,
            registration_metrics=registration_metrics,
            logger=self.logger,
        )

    def _apply_cross_group_skip_filter(
        self,
        aligned_stacks: dict[str, Path],
        cross_group_registrations: list[dict],
        ref_hash: str,
        min_correlation: float,
        group_metadata: dict | None = None,
        preview_paths: dict | None = None,
        working_dir: Path | None = None,
        group_eqmode: dict | None = None,
        group_avg_rotation: float = 0.0,
    ) -> tuple[dict[str, Path], list[dict]]:
        return apply_cross_group_skip_filter(
            aligned_stacks, cross_group_registrations, ref_hash,
            min_correlation,
            group_metadata=group_metadata,
            preview_paths=preview_paths,
            working_dir=working_dir,
            group_eqmode=group_eqmode,
            group_avg_rotation=group_avg_rotation,
            logger=self.logger,
        )

    def _register_to_reference_stack(
        self, stack_path: Path, ref_stack_path: Path,
        filter_name: str, output_dir: Path,
        params: dict | None = None,
        eq: bool | None = None,
    ) -> RegistrationResult:
        return register_to_reference_stack(
            stack_path, ref_stack_path, filter_name, output_dir,
            load_frame=self.load_frame,
            save_frame=self.save_frame,
            logger=self.logger,
            params=params,
            eq=eq,
        )

    def _apply_pcc_per_group(
        self, stack_path: Path, context: ObservationContext,
        multi_group_config: MultiGroupConfig, group_dir: Path,
        pixel_scale_arcsec: float = 0.0,
        ra: float | None = None, dec: float | None = None,
        group_metadata: dict | None = None,
    ) -> tuple[Path, str]:
        return apply_pcc_per_group(
            stack_path, context, multi_group_config, group_dir,
            photometric_color_calibration_fn=self._photometric_color_calibration,
            logger=self.logger,
            pixel_scale_arcsec=pixel_scale_arcsec,
            ra=ra, dec=dec,
            group_metadata=group_metadata,
        )

    def _photometric_color_calibration(
        self, stacked, params: dict,
        ra=None, dec=None, pixel_scale_arcsec: float = 0.0,
    ) -> None:
        photometric_color_calibration(
            stacked, params,
            load_frame=self.load_frame,
            save_frame=self.save_frame,
            config=self.config,
            logger=self.logger,
            ra=ra, dec=dec,
            pixel_scale_arcsec=pixel_scale_arcsec,
        )

    def _background_extraction(self, stacked, params: dict):
        return background_extraction(
            stacked, params,
            load_frame=self.load_frame,
            save_frame=self.save_frame,
            logger=self.logger,
        )

    # ── Multi-Group Pipeline (Phase 2 — T5–T8) ──────────────

    def process_multi_group(
        self, context: ObservationContext,
        calibration_result, debayer_result,
        pipeline: PipelinePreset,
        multi_group_config: MultiGroupConfig,
        merge_agent: MergeAgent | None = None,
        target_name: str = "",
    ):
        """Multi-Group Pipeline: Discovery → Pass 1 (intra-group) → Pass 2 (cross-group) → PCC → Merge.

        Refactor 2026-08-14 (Cluster 6): moved from
        ``ProcessingAgent.process_multi_group`` — rein verschoben, KEINE
        Verhaltensaenderung (Event-Namen, Report-Schemata, Datei-Semantik
        identisch). Der Rueckgabetyp ist der vom Agent injizierte
        ``processing_result_class`` (ProcessingResult).

        Args:
            context: Full observation context with all frames
            calibration_result: Result from CalibrationAgent
            debayer_result: Result from DebayerAgent (may be None for 2D)
            pipeline: Pipeline preset with steps and processing params
            multi_group_config: Multi-group configuration

        Returns:
            ProcessingResult with merged stack path and exports
        """
        from ..agents.discovery import DiscoveryAgent

        # 1. Discover groups from context metadata
        discovery = DiscoveryAgent(self.config)
        groups: dict[str, GroupInfo] = discovery.discover_groups(context)
        self.logger.info("multi_group.start", group_count=len(groups), groups=list(groups.keys()))

        if len(groups) == 0:
            raise ValueError("No groups found for multi-group processing — no light frames")

        # V1.7-5 (Always Multi-Group, AC-A1): Kein Single-Group-Fallback
        # mehr. Genau 1 Gruppe laeuft durch denselben Pfad wie N Gruppen —
        # der fruehere Delegations-Zweig (warning ``multi_group.single_group``
        # -> ``run_single``) ist entfernt. Info-Log dokumentiert die
        # vereinheitlichte Verarbeitung (AC-A2).
        if len(groups) == 1:
            self.logger.info(
                "multi_group.single_group_unified",
                group_count=1,
                groups=list(groups.keys()),
                msg="Single acquisition group — unified multi-group path",
            )

        # 2. Determine input frames (debayered 3D or calibrated 2D)
        input_frames = (debayer_result.debayered_frames
                        if debayer_result and debayer_result.debayered_frames
                        else calibration_result.calibrated_lights)
        is_3d = bool(debayer_result and debayer_result.debayered_frames)
        proc_params = pipeline.processing_params.model_dump() if pipeline.processing_params else {}

        # V1.8-2 (AC-PREV-A4/A5): effektive Preview/Export-Pipeline Config
        # aufloesen. Wird fuer alle Gruppen-Previews und den Merge-Preview
        # verwendet; None -> Asinh-only (byte-identisch v1.6).
        preview_cfg = resolve_preview_export_config(
            self.config, pipeline
        ) if self.config is not None else None

        # V1.8-3 (AC-FITS-A1..A4): effektive Export-Config aufloesen
        # (stretched_fits + stretch). None -> Default false.
        export_cfg = resolve_export_config(
            self.config, pipeline
        ) if self.config is not None else None

        # 3. Build frame-to-group mapping from original context metadata
        # Debayered files may not preserve FITS headers, so we use index-based mapping
        lights = context.get_lights()
        frame_groups: dict[str, list[Path]] = {h: [] for h in groups}
        # V1.4-21 (M13): EQMODE-Header je Light pro Gruppe sammeln
        # (0=AZ, 1=EQ, None=unbekannt; fits_parser liest ihn best effort,
        # Fix-Sammlung v1.3 §2) — Fundament fuer eqmode_majority/
        # eqmode_consistent + Mix-Warnung VOR dem Lauf.
        eqmode_values_by_group: dict[str, list[int | None]] = {h: [] for h in groups}
        if len(lights.frames) != len(input_frames):
            self.logger.warning("multi_group.frame_count_mismatch",
                                lights=len(lights.frames), inputs=len(input_frames),
                                msg="Frame count mismatch — mapping may be offset")
        for i, f in enumerate(lights.frames):
            if not f.header:
                continue
            exptime = f.header.exptime if f.header.exptime is not None else 0.0
            gain = f.header.gain if f.header.gain is not None else 0
            filter_name = f.header.filter_name if f.header.filter_name else ""
            gh = compute_group_hash(float(exptime), int(gain), str(filter_name))
            if gh in frame_groups and i < len(input_frames):
                frame_groups[gh].append(input_frames[i])
                eqmode_values_by_group[gh].append(f.header.eq_mode)

        # V1.4-21: EQMODE je Gruppe konsolidieren (majority/consistent/counts)
        eqmode_by_group: dict[str, dict] = {
            h: consolidate_eqmode_values(v)
            for h, v in eqmode_values_by_group.items()
        }

        # V1.4-21 (M13): Warnung VOR dem Lauf — AZ/EQ-Mix unter den
        # Gruppen frueh melden (nicht erst im Merge; Nutzer kann Serie
        # ausschliessen oder Split-Lauf machen). Additiv, nie Abbruch —
        # das Cross-Group-Gate (Pass 2/W3) schuetzt den Merge zusaetzlich.
        known_eq_modes = {
            h: d["majority"] for h, d in eqmode_by_group.items()
            if d["majority"] in (0, 1)
        }
        if len(set(known_eq_modes.values())) >= 2:
            self.logger.warning(
                "multi_group.eqmode_mix",
                modes=sorted(set(known_eq_modes.values())),
                groups=sorted(known_eq_modes),
                hint=(
                    "AZ/EQ-Mix erkannt: Gruppen mit unterschiedlichem "
                    "Aufnahmemodus (EQMODE-Header). Abweichende Gruppen "
                    "werden vom Cross-Group-Qualitaets-Gate behandelt "
                    "(eigener Stack bleibt). Empfohlen: Serie ausschliessen "
                    "oder Split-Lauf."
                ),
            )

        # V1.8-1 CFA-Drizzle (AC-DRZ-1): wenn enabled false -> byte-identisch v1.7 (kein Overhead, Pass-through).
        # Resolver: CLI > Config > Default (enabled false). Wenn enabled true -> CFA-Drizzle vor Debayer (Pass 1 je Gruppe).
        try:
            drz_cfg: CFADrizzleConfig = resolve_cfa_drizzle(self.config)  # type: ignore
        except Exception:
            from ..config.models import CFADrizzleConfig as _DC
            drz_cfg = _DC()

        # Build calibrated CFA groups mapping for drizzle (index-based wie frame_groups)
        calibrated_groups: dict[str, list[Path]] = {h: [] for h in groups}
        _calibrated_lights = getattr(calibration_result, "calibrated_lights", []) or []
        if len(lights.frames) != len(_calibrated_lights):
            self.logger.warning("multi_group.calibrated_count_mismatch",
                                lights=len(lights.frames), calibrated=len(_calibrated_lights))
        for i, f in enumerate(lights.frames):
            if not f.header:
                continue
            exptime = f.header.exptime if f.header.exptime is not None else 0.0
            gain = f.header.gain if f.header.gain is not None else 0
            filter_name = f.header.filter_name if f.header.filter_name else ""
            gh = compute_group_hash(float(exptime), int(gain), str(filter_name))
            if gh in calibrated_groups and i < len(_calibrated_lights):
                calibrated_groups[gh].append(_calibrated_lights[i])

        # Track drizzle results for merge / reporting
        cfa_drizzle_results: dict[str, dict] = {}
        drizzle_fallback_skipped: list[dict] = []

        # 4. Pass 1: Intra-group registration + stacking per group
        group_stacks: dict[str, Path] = {}      # group_hash → stacked.fits path
        group_metadata: dict[str, dict] = {}     # group_hash → metadata dict
        group_qualities: dict[str, list[FrameQuality]] = {}  # QF-B: Frame-Metriken je Gruppe
        group_selection: dict[str, dict] = {}  # V1.7-2 FSEL-C/D: Trichter + per-frame Entscheidungen je Gruppe
        # P2-1 (ray-Review, R3-Randfall): Intra-Group-Skips mit
        # registration.frame_rejected-Zaehlung — Report-Eintrag analog
        # skipped_groups (W7) / rejected_groups (RE-F).
        skipped_intra_groups: list[dict] = []

        def _has_step(name: str) -> bool:
            return any(s.name == name for s in pipeline.steps)

        # GR-01 (E1-Close): GR enabled (CLI/Config) aber Preset ohne GR-Step
        # -> genau EINE Warning pro Lauf statt stiller Ignoranz (Muster
        # pipeline.step_unhandled, S2-B10). Kein Abbruch.
        if (proc_params.get("gradient_removal") or {}).get("enabled") and not (
            _has_step("background_extraction") or _has_step("gradient_removal")
        ):
            self.logger.warning(
                "pipeline.gradient_removal_unhandled",
                msg=(
                    "Gradient removal enabled but preset has no "
                    "background_extraction/gradient_removal step — "
                    "verify the pipeline preset"
                ),
            )

        # V19-REG-SMART E5: Per-group registration config + Cross-Group always astroalign 20°
        # Compute per-group configs via resolver (CLI > Profil > Auto > Config > fft)
        _per_group_reg_configs: dict[str, dict] = {}
        _cross_group_reg_cfg: dict = {"method": "astroalign", "max_rotation_deg": 20.0, "max_scale_dev": 0.05}
        try:
            from ..config.loader import (  # type: ignore
                get_cross_group_registration_config,
                resolve_group_registration_configs,
            )
            _cli_override = getattr(self.config, "_registration_cli_override", None) if self.config else None  # type: ignore
            # Also fallback to proc_params method if CLI was set via pipeline but attribute missing
            if _cli_override is None:
                _reg_cli = (proc_params.get("registration", {}) or {}).get("method")
                # Only treat as CLI override if it differs from config default? Use explicit attribute prefer
            # global_equipment attempted from context.equipment (if resolved) — best effort
            _global_equip = None
            try:
                if context and hasattr(context, "equipment") and context.equipment:
                    _global_equip = {
                        "mount_type": getattr(context.equipment, "mount_type", None),
                        "preferred_registration": getattr(context.equipment, "preferred_registration", None) if hasattr(context.equipment, "preferred_registration") else None,
                    }
                    # Clean Nones
                    _global_equip = {k: v for k, v in _global_equip.items() if v is not None} or None
            except Exception:
                _global_equip = None
            _per_group_reg_configs = resolve_group_registration_configs(
                cfg=self.config,  # type: ignore
                groups=frame_groups,
                cli_override=_cli_override,
                global_equipment=_global_equip,
                # DEF-009: EQMODE-Mehrheit aus Original-Light-Headers durchreichen,
                # damit Zwischen-Dateien ohne EQMODE keine irrefuehrenden
                # discovery.mount_unknown-Warnungen erzeugen.
                eqmode_by_group=eqmode_by_group,
            )
            _cross_group_reg_cfg = get_cross_group_registration_config()
            self.logger.info(
                "multi_group.cross_group_config",
                method=_cross_group_reg_cfg.get("method"),
                max_rotation_deg=_cross_group_reg_cfg.get("max_rotation_deg"),
                source="fixed_astroalign_20deg",
            )
        except Exception as _e5_exc:
            self.logger.warning("multi_group.group_registration_resolve_failed", error=str(_e5_exc))
            _per_group_reg_configs = {}
            _cross_group_reg_cfg = {"method": "astroalign", "max_rotation_deg": 20.0, "max_scale_dev": 0.05}

        for group_hash, info in groups.items():
            frames = frame_groups.get(group_hash, [])
            if len(frames) < 2:
                self.logger.warning("multi_group.skip_group", hash=group_hash,
                                    frames=len(frames), reason="insufficient_frames")
                continue

            # Apply per-group registration config (E5): override proc_params["registration"] for this group
            _group_proc_params = proc_params
            try:
                if group_hash in _per_group_reg_configs:
                    _grp_cfg = _per_group_reg_configs[group_hash]
                    # Shallow copy proc_params for this group (avoid cross-group bleed)
                    import copy as _copy_e5
                    _group_proc_params = _copy_e5.deepcopy(proc_params)
                    # Map resolver dict to RegistrationConfig-like dict inside proc_params
                    _reg_dict = _group_proc_params.get("registration", {}) or {}
                    # Resolver provides method, max_rotation_deg, max_scale_dev, max_exptime etc.
                    for _k in ("method", "max_control_points", "max_rotation_deg", "max_scale_dev",
                               "zero_shift_threshold", "zero_shift_fallback", "stack_scale_factor"):
                        if _k in _grp_cfg and _grp_cfg[_k] is not None:
                            _reg_dict[_k] = _grp_cfg[_k]
                    _group_proc_params["registration"] = _reg_dict
                    self.logger.info(
                        "multi_group.group_registration_applied",
                        group=group_hash,
                        method=_reg_dict.get("method"),
                        max_rotation_deg=_reg_dict.get("max_rotation_deg"),
                    )
                else:
                    _group_proc_params = proc_params
            except Exception:
                _group_proc_params = proc_params

            # Create group working directory structure
            group_dir = self.working_dir / f"group_{group_hash}"
            group_dir.mkdir(parents=True, exist_ok=True)
            info.working_dir = group_dir

            reg_dir = group_dir / "03_registered"
            stack_dir = group_dir / "04_stacked"
            reg_dir.mkdir(parents=True, exist_ok=True)
            stack_dir.mkdir(parents=True, exist_ok=True)

            # Temporarily redirect output dirs to group-specific paths
            orig_reg = self.registered_dir
            orig_stack = self.stacked_dir
            self.registered_dir = reg_dir
            self.stacked_dir = stack_dir

            # ── V1.8-1 CFA-Drizzle (nach QualityGate, vor Debayer) ──
            drizzle_attempted = False
            drizzle_success = False
            drizzle_stacked: Path | None = None
            drizzle_meta: dict | None = None
            # Per-group overrides: fallback materialization can change the
            # effective input frames (re-debayered CFA) and their scale factor.
            group_is_3d = is_3d
            group_stack_scale_factor: float | None = None
            if drz_cfg.enabled:
                cfa_paths = calibrated_groups.get(group_hash, [])
                # Guard: is_3d irrelevant for drizzle (needs CFA 2D)
                # If calibrated lights missing or already RGB, fallback to normal path
                try:
                    drizzle_attempted = True
                    # Quality Gate filtering (nur non-outlier) before drizzle (AC-DRZ-5)
                    from ..agents.cfa_drizzle_agent import (
                        cfa_drizzle,
                        compute_pixfrac,
                        register_cfa_subpixel,
                    )
                    from ..core.quality import compute_frame_quality, reject_outlier_frames

                    # Load CFA frames (float32, 2D)
                    cfa_frames: list[np.ndarray] = []
                    cfa_valid: list[Path] = []
                    for p in cfa_paths:
                        try:
                            with fits.open(p) as hdul:
                                d = hdul[0].data.astype(np.float32)
                                if d.ndim == 3:
                                    raise ValueError("already RGB")
                                hdr = hdul[0].header
                                bzero = hdr.get("BZERO", 0.0)
                                if bzero != 0.0:
                                    d = d - bzero
                                cfa_frames.append(d)
                                cfa_valid.append(p)
                        except Exception as e:
                            self.logger.warning("cfa_drizzle.frame_load_failed", group=group_hash, path=str(p), error=str(e))
                    n_in = len(cfa_paths)
                    n_loaded = len(cfa_frames)
                    if n_loaded >= 2:
                        # Quality gate — V19-CFA-GATE G5: Resolver statt direkter Config (mode + cli_overrides + thresholds rekursiv)
                        qg = drz_cfg.quality_gate
                        # Resolver path: compute effective gate (CFA defaults 1/0.1/5 vs debayered 20/0.3/10)
                        _eff_gate = None
                        _eff_thresholds = None
                        _eff_min_stars = getattr(qg, "min_stars_cfa", 3) if qg else 3
                        _eff_elong = bool(getattr(qg, "elongation_unusable", True)) if qg else True
                        _eff_rejection = bool(getattr(qg, "rejection_enabled", True)) if qg else True
                        _resolver = None
                        try:
                            from ..agents.cfa_drizzle_agent import (
                                resolve_cfa_drizzle_quality_gate as _resolver,  # type: ignore
                            )
                        except Exception:
                            try:
                                from ..core.cfa_drizzle import (
                                    resolve_cfa_drizzle_quality_gate as _resolver,  # type: ignore
                                )
                            except Exception:
                                _resolver = None
                        if _resolver is not None and qg is not None:
                            try:
                                mode = getattr(qg, "mode", "auto")
                                is_cfa_eff = (mode == "auto" and True) or mode == "cfa"
                                if mode == "debayered":
                                    is_cfa_eff = False
                                # user_gate as dict (inkl. thresholds, mode, etc.)
                                try:
                                    user_gate = qg.model_dump() if hasattr(qg, "model_dump") else dict(qg)  # type: ignore
                                except Exception:
                                    user_gate = {
                                        "thresholds": dict(qg.thresholds) if getattr(qg, "thresholds", None) else {},
                                        "rejection_enabled": getattr(qg, "rejection_enabled", True),
                                        "elongation_unusable": getattr(qg, "elongation_unusable", True),
                                        "min_stars_cfa": getattr(qg, "min_stars_cfa", 3),
                                    }
                                cli_over = getattr(self.config, "_cfa_cli_overrides", None) if self.config else None
                                _eff_gate = _resolver(user_gate, is_cfa=is_cfa_eff, cli_overrides=cli_over)
                                _eff_thresholds = dict(_eff_gate.get("thresholds", {}))
                                _eff_min_stars = _eff_gate.get("min_stars_cfa", _eff_min_stars)
                                _eff_elong = bool(_eff_gate.get("elongation_unusable", _eff_elong))
                                _eff_rejection = bool(_eff_gate.get("rejection_enabled", _eff_rejection))
                            except Exception:
                                _eff_gate = None
                        # Compute qualities with effective min_stars (CFA-aware)
                        qualities = []
                        for arr, pp in zip(cfa_frames, cfa_valid):
                            try:
                                q = compute_frame_quality(
                                    arr,
                                    min_stars=_eff_min_stars,
                                    cfa_mode=True,
                                    cfa_highpass_sigma=getattr(qg, "highpass_sigma", 30.0) if qg else 30.0,
                                )
                                q.frame = str(pp)
                                qualities.append(q)
                            except Exception:
                                from ..core.quality import FrameQuality as _FQ
                                qualities.append(_FQ(frame=str(pp)))
                        if _eff_thresholds is not None:
                            thresholds = _eff_thresholds
                            elong_enabled = _eff_elong
                            rejection_enabled = _eff_rejection
                        else:
                            thresholds = dict(qg.thresholds) if qg and getattr(qg, "thresholds", None) else {}
                            if qg is not None and getattr(qg, "star_count_cfa", None) is not None:
                                thresholds["star_count"] = qg.star_count_cfa
                                self.logger.info(
                                    "cfa_drizzle.star_count_cfa_override",
                                    group=group_hash,
                                    star_count_cfa=qg.star_count_cfa,
                                    threshold=str(qg.star_count_cfa),
                                )
                            elong_enabled = _eff_elong
                            rejection_enabled = _eff_rejection
                        try:
                            filtered = reject_outlier_frames(qualities, thresholds=thresholds, elongation_unusable_enabled=elong_enabled)  # type: ignore
                        except Exception:
                            filtered = qualities
                        if not rejection_enabled:
                            filtered = qualities
                            good_idx = list(range(len(cfa_frames)))
                        else:
                            good_idx = [i for i, q in enumerate(filtered) if not getattr(q, "outlier_excluded", False)]
                        good_frames = [cfa_frames[i] for i in good_idx]
                        n_out = len(good_frames)
                        # Dithering scale/pixfrac from drz_cfg
                        if drz_cfg.pixfrac_mode == "fixed":
                            pixfrac = float(drz_cfg.pixfrac)
                        else:
                            pixfrac = compute_pixfrac(n_out, scale=float(drz_cfg.scale))
                        # min_frames Guard + fallback (AC-DRZ-6)
                        if n_out < drz_cfg.min_frames:
                            fb = drz_cfg.fallback
                            if fb == "skip":
                                self.logger.warning("cfa_drizzle.min_frames_skip", group=group_hash, n_in=n_loaded, n_out=n_out, min_frames=drz_cfg.min_frames)
                                drizzle_fallback_skipped.append({"group": group_hash, "reason": "cfa_drizzle_min_frames_skip", "n_frames_in": n_in, "n_frames_out": n_out})
                                skipped_intra_groups.append({"group": group_hash, "reason": "cfa_drizzle_min_frames_skip", "n_frames_in": n_in, "n_frames_out": n_out})
                                # Skip group entirely (continue outer loop after finally)
                                # Use exception to break? Instead mark and handle after try/finally via flag
                                raise RuntimeError("cfa_drizzle_skip_group")
                            elif fb in ("malvar", "superpixel"):
                                self.logger.warning("cfa_drizzle.min_frames_fallback", group=group_hash, n_in=n_loaded, n_out=n_out, min_frames=drz_cfg.min_frames, fallback=fb)
                                # V1.8-1 (DEF-005): Materialize the configured fallback.
                                # The upstream DebayerAgent already produced frames with the
                                # CLI/default method; for the fallback we re-debayer the CFA
                                # frames with the configured method so log and behavior match.
                                fb_debayer_dir = group_dir / "02_debayered_fallback"
                                fb_debayer_dir.mkdir(parents=True, exist_ok=True)
                                fb_frames: list[Path] = []
                                for i, cfa_p in enumerate(cfa_paths):
                                    out_p = fb_debayer_dir / f"fb_{i:04d}.fits"
                                    try:
                                        debayer_fits(cfa_p, out_p, method=fb)
                                        fb_frames.append(out_p)
                                    except Exception as deb_e:
                                        self.logger.warning("cfa_drizzle.fallback_debayer_failed", group=group_hash, path=str(cfa_p), fallback=fb, error=str(deb_e))
                                if fb_frames:
                                    frames = fb_frames
                                    group_is_3d = True
                                    group_stack_scale_factor = 1.0 if fb == "malvar" else 2.0
                                    drizzle_meta = {
                                        "fallback": fb,
                                        "materialized": True,
                                        "stack_scale_factor": group_stack_scale_factor,
                                        "n_frames_in": n_in,
                                        "n_frames_out": n_out,
                                    }
                                    self.logger.info(
                                        "cfa_drizzle.fallback_materialized",
                                        group=group_hash,
                                        fallback=fb,
                                        stack_scale_factor=group_stack_scale_factor,
                                        n_frames=len(fb_frames),
                                    )
                                else:
                                    # F-03: alle debayer_fits failed -> nicht cfa_paths mit falschem Scale verwenden
                                    _fb_scale = 1.0 if fb == "malvar" else 2.0
                                    self.logger.warning(
                                        "cfa_drizzle.fallback_debayer_all_failed",
                                        group=group_hash,
                                        fallback=fb,
                                        n_frames_in=n_in,
                                        n_frames_out=n_out,
                                        stack_scale_factor=_fb_scale,
                                    )
                                    drizzle_meta = {
                                        "fallback": fb,
                                        "materialized": False,
                                        "stack_scale_factor": _fb_scale,
                                        "n_frames_in": n_in,
                                        "n_frames_out": n_out,
                                        "error": "all_debayer_failed",
                                    }
                                    # frames bleibt unveraendert (frame_groups, nicht cfa_paths);
                                    # group_is_3d und stack_scale_factor unveraendert
                                    group_stack_scale_factor = None
                                # Fall through to normal registration (do not drizzle)
                                drizzle_attempted = False
                            else:
                                drizzle_attempted = False
                        else:
                            # Shifts via register_cfa_subpixel
                            ref = good_frames[0]
                            shifts: list[tuple[float,float]] = [(0.0, 0.0)]
                            for tgt in good_frames[1:]:
                                try:
                                    sy, sx = register_cfa_subpixel(ref, tgt, upsample_factor=10)
                                    shifts.append((sy, sx))
                                except Exception:
                                    shifts.append((0.0, 0.0))
                            rgb = cfa_drizzle(good_frames, shifts, scale=float(drz_cfg.scale), pixfrac=pixfrac, kernel=drz_cfg.kernel)
                            # Save to 01c_drizzle and 04_stacked (so merge uses drizzled master)
                            drizzle_dir = group_dir / "01c_drizzle"
                            drizzle_dir.mkdir(parents=True, exist_ok=True)
                            drizzled_master_path = drizzle_dir / "drizzled_master.fits"
                            drizzled_cfa_path = drizzle_dir / "drizzled_cfa.fits"
                            out = rgb.astype(np.float32)
                            hdu = fits.PrimaryHDU(out.transpose(2,0,1))
                            hdu.header["CTYPE3"] = "RGB"
                            hdu.header["DRZSCALE"] = float(drz_cfg.scale)
                            hdu.header["DRZPIXFR"] = float(pixfrac)
                            hdu.header["DRZKERNL"] = drz_cfg.kernel
                            hdu.header["NFRAMES"] = n_out
                            hdu.header["BAYERPAT"] = "RGGB"
                            hdu.writeto(drizzled_master_path, overwrite=True)
                            # Optional cfa 2D
                            try:
                                out_H, out_W = rgb.shape[0], rgb.shape[1]
                                cfa2d = np.zeros((out_H, out_W), dtype=np.float32)
                                cfa2d[0::2, 0::2] = rgb[0::2, 0::2, 0]
                                cfa2d[0::2, 1::2] = rgb[0::2, 1::2, 1]
                                cfa2d[1::2, 0::2] = rgb[1::2, 0::2, 1]
                                cfa2d[1::2, 1::2] = rgb[1::2, 1::2, 2]
                                hdu2 = fits.PrimaryHDU(cfa2d)
                                hdu2.header["BAYERPAT"] = "RGGB"
                                hdu2.header["DRZSCALE"] = float(drz_cfg.scale)
                                hdu2.writeto(drizzled_cfa_path, overwrite=True)
                            except Exception:
                                pass
                            # Also copy to stack_dir/stacked.fits for downstream (PCC, merge)
                            stacked_path = stack_dir / "stacked.fits"
                            # Drizzled master is already RGB 3840x2160, shape matches final merge expectation
                            # Save to stacked.fits (copy)
                            import shutil as _sh
                            _sh.copy2(drizzled_master_path, stacked_path)
                            drizzle_stacked = stacked_path
                            drizzle_success = True
                            drizzle_meta = {"scale": float(drz_cfg.scale), "pixfrac": float(pixfrac), "kernel": drz_cfg.kernel, "n_frames_in": n_loaded, "n_frames_out": n_out}
                            self.logger.info("cfa_drizzle.complete", group=group_hash, scale=float(drz_cfg.scale), pixfrac=float(pixfrac), kernel=drz_cfg.kernel, n_frames_in=n_loaded, n_frames_out=n_out)
                            cfa_drizzle_results[group_hash] = {"scale": float(drz_cfg.scale), "pixfrac": float(pixfrac), "kernel": drz_cfg.kernel, "n_frames_in": n_loaded, "n_frames_out": n_out, "status": "ok"}
                except RuntimeError as e:
                    if str(e) == "cfa_drizzle_skip_group":
                        # Ensure finally runs then we skip group
                        self.logger.warning("cfa_drizzle.skip_group", group=group_hash)
                    else:
                        self.logger.warning("cfa_drizzle.failed", group=group_hash, error=str(e))
                except Exception as e:
                    self.logger.warning("cfa_drizzle.failed", group=group_hash, error=str(e))
                    # Fall through to normal path

            # If drizzle succeeded, short-circuit normal registration/stack
            if drizzle_success and drizzle_stacked is not None:
                # Need to handle finally for dir restore, then populate metadata and continue outer loop
                # We are still inside try before reg_result, so we can set stacked and skip reg
                # Use variables to propagate after try
                drizzle_short_circuit = True
            else:
                drizzle_short_circuit = False
                # Handle skip case: if we raised skip, we already appended to skipped_intra_groups and should abort this group
                if drizzle_attempted and not drizzle_success and any(d.get("group")==group_hash for d in drizzle_fallback_skipped):
                    # We already logged skip, ensure dir reset then continue outer loop
                    self.registered_dir = orig_reg
                    self.stacked_dir = orig_stack
                    continue

            # Stacked placeholder for inner try/finally handling
            stacked: Path | None = None
            if drizzle_short_circuit:
                # Drizzle short-circuit: no registration, drizzled master is already stacked
                stacked = drizzle_stacked  # type: ignore
                self.last_frame_qualities = []
                self.last_frame_rejected = 0
                self.last_registration_metrics = {}
            try:
                if not drizzle_short_circuit:
                    # Refactor 2026-08-14 (Cluster 3): register_frames ist
                    # Modul-Funktion in core/registration.py; der Registrierungs-
                    # Zustand wird aus dem RegisterFramesResult in die
                    # _last_*-Attribute uebernommen (V1.3-3-Semantik erhalten).
                    reg_result = register_frames(
                        frames, _group_proc_params, is_3d=group_is_3d,
                        registered_dir=self.registered_dir,
                        load_frame=self.load_frame,
                        save_frame=self.save_frame,
                    )
                    registered = reg_result.registered
                    self.last_frame_qualities = reg_result.last_frame_qualities
                    self.last_frame_rejected = reg_result.last_frame_rejected
                    self.last_registration_metrics = reg_result.last_registration_metrics
                    rejected_count = self.last_frame_rejected

                    # P2-1 (ray-Review, R3-Randfall): nur der Referenz-Frame
                    # registriert (ALLE Nicht-Referenz-Frames per
                    # registration.frame_rejected verworfen — RE-F/R3, nur bei
                    # nicht-Default-zero_shift_threshold erreichbar, oder
                    # fehlgeschlagen) -> Gruppe sauber skippen statt
                    # ValueError ("Need at least 2 frames to stack") im
                    # Stacking. Report-Eintrag mit frame_rejected-Zaehlung
                    # (analog skipped_groups/rejected_groups); Default-Pfad
                    # (>= 2 registrierte Frames) unveraendert. Guard exakt auf
                    # den 1-Frame-Randfall: len == 0 ist in Produktion nicht
                    # erreichbar (Registration behaelt immer die Referenz) und
                    # faellt wie bisher in den stack_failed-Skip von
                    # stack_frames (Mock-Aufrufer/Tests unveraendert).
                    if len(registered) == 1:
                        reason = (
                            "all_frames_rejected_below_zero_shift_threshold"
                            if rejected_count > 0
                            else "insufficient_registered_frames"
                        )
                        self.logger.warning(
                            "multi_group.skip_group",
                            hash=group_hash,
                            frames=len(frames),
                            reason=reason,
                            frame_rejected=rejected_count,
                        )
                        skipped_intra_groups.append({
                            "group": group_hash,
                            "reason": reason,
                            "frame_rejected": rejected_count,
                            "registered_frames": len(registered),
                        })
                        continue

                    # V1.7-2 FSEL-C + D: Perzentil → Threshold Pipeline (AC-FSEL-C1..C3, D1).
                    # Reihenfolge: zuerst Perzentil-Selektion (relativ, session-intern),
                    # danach Threshold-Rejection (absolut, Sicherheitsnetz) auf dem Rest
                    # — keine Doppelt-Verwerfung in einer Stufe. Trichter-Zaehlung
                    # total → percentile_rejected → threshold_rejected → stacked
                    # (AC-FSEL-C2, je Gruppe) + per-frame Score/Entscheidung/Grund
                    # (AC-FSEL-D1). Unabhängige Schalter (AC-FSEL-C3).
                    _selection_report: dict | None = None
                    try:
                        _fs_cfg = _resolve_frame_selection_config(proc_params, self.config)
                        _rej_enabled, _rej_thresh, _rej_elong = _resolve_rejection_config(proc_params, self.config)
                        _min_corr_hp = _resolve_min_corr_hp_config(proc_params, self.config)
                        # V1.8-8 (DEF-006): Mandatory Gate für average (stella a+c)
                        # Auch bei Default rejection_enabled=False muss katastrophale corr_hp <0.05 verworfen werden
                        # Analog V1.4-20 min_correlation (0.1), intra-group vor Stacking.
                        # Kombiniert: outlier_excluded==True ODER corr_hp<Schwelle.
                        # Precedence: Config > Preset > Default 0.05 (None deaktiviert).
                        needs_mandatory = _min_corr_hp is not None
                        # FSEL-C3: unabhängige Schalter — erweitert V1.8-8: mandatory Gate auch bei beide aus
                        if _fs_cfg.enabled or _rej_enabled or needs_mandatory:
                            _orig_registered = list(registered)
                            registered, _selection_report = _apply_selection_and_rejection(
                                registered,
                                self.last_frame_qualities,
                                _fs_cfg,
                                _rej_enabled,
                                _rej_thresh,
                                _rej_elong,
                                group_hash,
                                logger=self.logger,
                                mandatory_min_corr_hp=_min_corr_hp,
                            )
                            group_selection[group_hash] = _selection_report
                            # Kompatibilitaets-Log fuer Batch-A (frame_selection_applied)
                            if _selection_report and _selection_report.get("percentile_rejected", 0) > 0:
                                self.logger.info(
                                    "multi_group.frame_selection_applied",
                                    group=group_hash,
                                    before=_selection_report["total"],
                                    after=_selection_report["total"] - _selection_report["percentile_rejected"],
                                    keep_percentile=_fs_cfg.keep_percentile,
                                )
                            # Trichter-Log bereits in _apply_selection_and_rejection (selection.funnel)
                            # V1.8-8: zusätzlich mandatory_rejected im Log (selection.mandatory_rejected)
                        else:
                            # Beide aus und kein mandatory Gate — leeren Report fuer Transparenz (inspect/doctor)
                            group_selection[group_hash] = {
                                "total": len(registered),
                                "percentile_rejected": 0,
                                "threshold_rejected": 0,
                                "stacked": len(registered),
                                "keep_percentile": _fs_cfg.keep_percentile,
                                "enabled": False,
                                "weights": dict(_fs_cfg.weights) if _fs_cfg.weights else None,
                                "min_frames": _fs_cfg.min_frames,
                                "skipped_min_frames": False,
                                "score_min": None,
                                "score_max": None,
                                "score_median": None,
                                "cutoff_score": None,
                                "frames": [],
                                "rejection_enabled": False,
                                "rejection_thresholds": {},
                                "mandatory_rejected": 0,
                                "min_corr_hp": _min_corr_hp,
                            }
                    except Exception as e:
                        self.logger.warning(
                            "multi_group.frame_selection_failed",
                            group=group_hash,
                            error=str(e),
                            action="all_frames_stacked",
                        )
                        # Fallback: leeren Report, registered unveraendert
                        if group_hash not in group_selection:
                            group_selection[group_hash] = {
                                "total": len(registered),
                                "percentile_rejected": 0,
                                "threshold_rejected": 0,
                                "stacked": len(registered),
                                "keep_percentile": 92,
                                "enabled": False,
                                "weights": None,
                                "min_frames": 3,
                                "skipped_min_frames": False,
                                "score_min": None,
                                "score_max": None,
                                "score_median": None,
                                "cutoff_score": None,
                                "frames": [],
                                "rejection_enabled": False,
                                "rejection_thresholds": {},
                            }

                    stacked = stack_frames(
                        registered, _group_proc_params, is_3d=group_is_3d,
                        stacked_dir=self.stacked_dir,
                        load_frame=self.load_frame,
                        save_frame=self.save_frame,
                    )
            except Exception as e:
                # F-01: logger.error -> warning (_LogRecorder hat kein error())
                self.logger.warning("multi_group.group_failed", hash=group_hash, error=str(e))
                continue
            finally:
                self.registered_dir = orig_reg
                self.stacked_dir = orig_stack

            # QF-B (AC-QF-B1): Frame-Metriken des Registrations-Passes
            # dieser Gruppe festhalten (Outlier sind bereits geflaggt).
            group_qualities[group_hash] = self.last_frame_qualities

            # GR-D (AC-GR-D1, OQ-GR-5): Gradient Removal pro Gruppen-Stack —
            # NACH dem Stacking (Pass 1) und VOR der Cross-Group-Registration
            # (Pass 2, `_register_to_reference_stack`). Der Stack wird
            # In-Place ersetzt; die `group_*/04_stacked/`-Struktur bleibt
            # unveraendert. Fehler/Skip (min_samples, 2D) lassen die Gruppe
            # trotzdem weiterlaufen (AC-GR-B3/E1).
            gr_report: dict | None = None
            if stacked and stacked.exists():
                if _has_step("background_extraction") or _has_step("gradient_removal"):
                    gr_report = self._background_extraction(stacked, _group_proc_params)
                group_stacks[group_hash] = stacked
            else:
                self.logger.warning("multi_group.skip_group", hash=group_hash, reason="stack_failed")
                continue

            # Collect group metadata (T8)
            exptime = info.key[0] if len(info.key) > 0 else 0.0
            gain = info.key[1] if len(info.key) > 1 else 0
            filter_name = info.key[2] if len(info.key) > 2 else ""
            # T3: Per-Group dark_source aus CalibrationResult (group_hash -> Quelle).
            # Legacy-Fallback (Mock/None-Result ohne dict-Feld): globaler Wert.
            dark_source = "master_dark" if context.calibration.dark_available else "none"
            if calibration_result is not None:
                sources = getattr(calibration_result, "master_dark_sources", None)
                if isinstance(sources, dict):
                    dark_source = sources.get(group_hash, "none")

            # Weight calculation (architecture §3, AQ3/hal)
            if multi_group_config.merge.weight_by == "total_exposure":
                weight = info.total_exposure
            else:
                weight = float(info.frame_count)

            group_metadata[group_hash] = {
                "group_hash": group_hash,
                "frame_count": info.frame_count,
                "exptime": float(exptime),
                "gain": int(gain),
                "filter": filter_name if filter_name not in ("none", "") else None,
                "total_exposure": info.total_exposure,
                "weight": weight,
                "pcc_status": "pending",
                "dark_source": dark_source,
                # QF-B (AC-QF-B1/B2): je Frame + Stack-Zusammenfassung.
                # Fliesst additiv in agent-log (via multi_group_metadata)
                # und in den merge_report-quality-Block (merge_agent).
                # Refactor 2026-08-14 (Cluster 4): qual_to_dict/
                # summarize_qualities sind Modul-Funktionen in core/quality.py.
                "frame_quality": [
                    qual_to_dict(q) for q in group_qualities.get(group_hash, [])
                ],
                "quality": summarize_qualities(
                    group_qualities.get(group_hash, [])
                ),
                # V1.3-3: Registrierungs-Metriken dieser Gruppe (analog
                # frame_quality; nach dem _register_frames-Aufruf oben
                # befuellt). dict()-Wrap KOPIERT, damit group_metadata
                # konsistent bleibt, wenn der naechste Gruppen-Loop das
                # Instanz-Attribut ueberschreibt (shallow copy genuegt —
                # Werte sind primitiv).
                "registration_metrics": dict(self.last_registration_metrics or {}),
                # V1.4-21 (M13): EQMODE-Konsolidierung dieser Gruppe —
                # {majority: 0|1|None, consistent: bool, counts: {0,1,None}}.
                # Fliesst additiv in merge_report/agent-log (Modus-Mix
                # nachvollziehbar; Fix-Sammlung v1.3 §4).
                "eqmode": eqmode_by_group.get(group_hash) or {
                    "majority": None, "consistent": True,
                    "counts": {"0": 0, "1": 0, "None": 0},
                },
                # V1.7-2 FSEL-C/D: Frame-Selection Trichter + per-frame Entscheidungen.
                # AC-FSEL-C2: total → percentile_rejected → threshold_rejected → stacked
                # AC-FSEL-D1: je Light-Frame score + Entscheidung (kept|percentile_rejected|threshold_rejected) + Grund
                # Additiv — Legacy-Gruppen ohne selection bleiben valide (leeres dict).
                "selection": dict(group_selection.get(group_hash) or {}),
                # V1.8-1 (DEF-005): Effective stack_scale_factor for this group
                # (fallback materialization may change it vs. the global default).
                "effective_stack_scale_factor": group_stack_scale_factor,
                # V1.8-1 (AC-DRZ-9): drizzle metadata / fallback materialization.
                "drizzle": drizzle_meta or {},
            }

            # GR-E (AC-GR-E1, AC-GR-D2): Gradient-Removal-Report pro Gruppe
            # (applied + Modell-Parameter). Additiv — Gruppen ohne GR-Attempt
            # (disabled / kein Step / kein Stack) erhalten keinen Eintrag
            # (Legacy-Ergebnisse bleiben valide).
            if gr_report is not None:
                group_metadata[group_hash]["gradient_removal"] = gr_report

        # If all groups failed, abort (error-propagation §8)
        if not group_stacks:
            raise ValueError("All groups failed during intra-group processing — nothing to merge")

        # CR-001 W7-Erweiterung (AC-W7-2): Preview für ALLE Gruppen mit Stack
        # (04_stacked/stacked.fits) VOR dem Skip-Filter erzeugen — unabhängig
        # vom PCC-Hook (sonst fehlt preview_{hash}.jpg bei geskippten Gruppen,
        # weil pcc_applied.fits dort nie existiert). AC-P2 bleibt erhalten:
        # gemergte Gruppen bekommen nach PCC zusätzlich das farbkalibrierte
        # Preview (überschreibt preview_{hash}.jpg, Dateiname identisch).
        # preview_paths wird an den Skip-Filter durchgereicht, damit
        # skipped_groups[].preview_path auf diese Previews zeigt.
        preview_paths: dict[str, Path] = {}
        for group_hash, stacked_path in group_stacks.items():
            info = groups[group_hash]
            group_dir = (info.working_dir
                         if info.working_dir
                         else self.working_dir / f"group_{group_hash}")
            try:
                preview_path = create_preview_jpg(
                    stacked_path,
                    group_dir / "04_stacked" / f"preview_{group_hash}.jpg",
                    preview_config=preview_cfg,
                )
                if preview_path is None:
                    self.logger.warning("multi_group.preview_failed", hash=group_hash,
                                        reason="create_preview_jpg_returned_none")
                else:
                    preview_paths[group_hash] = preview_path
            except Exception as e:
                self.logger.warning("multi_group.preview_failed", hash=group_hash, error=str(e))

        # V1.7-1 FSM-B (OQ-FSM-1 A, AC-FSM-B1..B6): Filter-Auswahl FRÜH vor Referenzwahl/Pass2/PCC.
        # Nur Kandidaten (is_merge_filter_match) gehen in Referenzwahl/Pass2/PCC/Merge;
        # Excluded → skipped_groups reason="filter_excluded" (inkl. hash+filter), Stacks bleiben erhalten (AC-FSM-B3/B4).
        # Bei filters=None unverändert (AC-FSM-B5, kein Ballast).
        effective_filters = None
        filter_excluded_skipped: list[dict] = []
        candidate_hashes: set[str] | None = None
        if multi_group_config.merge is not None:
            effective_filters = normalize_merge_filters(multi_group_config.merge.filters)
        if effective_filters is not None:
            candidate_hashes = set()
            for gh in list(group_stacks.keys()):
                meta = group_metadata.get(gh, {})
                fv = meta.get("filter")
                if is_merge_filter_match(fv, effective_filters):
                    candidate_hashes.add(gh)
                else:
                    entry: dict = {"group": gh, "reason": "filter_excluded", "filter": fv}
                    pp = preview_paths.get(gh)
                    if pp is not None:
                        try:
                            entry["preview_path"] = str(pp.relative_to(self.working_dir))
                        except ValueError:
                            entry["preview_path"] = str(pp)
                    filter_excluded_skipped.append(entry)
                    self.logger.info("multi_group.filter_excluded", group=gh, filter=fv, filters=effective_filters)
            if filter_excluded_skipped:
                self.logger.info(
                    "multi_group.filter_summary",
                    filters=effective_filters,
                    candidates=sorted(candidate_hashes),
                    excluded=[e["group"] for e in filter_excluded_skipped],
                )
            # V1.7-1 FSM-C3: Tippfehler-Warning — Filterwert matcht keine Gruppe (Verdacht Tippfehler), ohne Lauf zu blockieren
            # Normalisierte Gruppen-FILTER-Werte (trim+lower, analog is_merge_filter_match)
            _group_normalized_filters: set[str] = set()
            for _gh, _meta in group_metadata.items():
                _fv = _meta.get("filter")
                if _fv is None:
                    _cand = ""
                else:
                    _cand = str(_fv).strip().lower()
                _group_normalized_filters.add(_cand)
            for _flt in set(effective_filters or []):
                if _flt not in _group_normalized_filters:
                    self.logger.warning(
                        "multi_group.merge_filter_no_match",
                        filter=_flt,
                        effective=effective_filters,
                        groups=sorted(_group_normalized_filters),
                        hint="Verdacht Tippfehler: Filter-Wert passt zu keiner Gruppe — Pruefe Schreibweise (case-insensitive, getrimmt)",
                    )
            _filtered_group_stacks: dict[str, Path] = {gh: p for gh, p in group_stacks.items() if gh in candidate_hashes}
            _filtered_groups: dict[str, GroupInfo] = {gh: g for gh, g in groups.items() if gh in candidate_hashes}
            _filtered_group_metadata: dict[str, dict] = {gh: m for gh, m in group_metadata.items() if gh in candidate_hashes}
        else:
            _filtered_group_stacks = group_stacks
            _filtered_groups = groups
            _filtered_group_metadata = group_metadata

        # 5. Select reference group (quality-based by default — V1.3-5,
        # signal-based (W14) or user-specified via Config-Override)
        # V1.3-5: Registrierungs-Metriken je Gruppe als Map
        # group_hash → Metriken-Dict für die quality-Referenzwahl.
        # Leere/fehlende dicts (Legacy/Mocks) sind erlaubt — der
        # _select_reference_group-Fallback greift (reason="no_metrics").
        registration_metrics_by_group = {
            gh: dict(meta.get("registration_metrics") or {})
            for gh, meta in group_metadata.items()
        }
        # FSM-B: Für Referenzwahl nur Kandidaten-Metriken (AC-FSM-B6)
        _ref_registration_metrics = (
            {gh: m for gh, m in registration_metrics_by_group.items() if gh in candidate_hashes}
            if candidate_hashes is not None else registration_metrics_by_group
        )
        # Keine Kandidaten → Merge-Skip (OQ-FSM-4 A), keine Referenzwahl
        if candidate_hashes is not None and not candidate_hashes:
            self.logger.warning(
                "multi_group.filter_no_candidates",
                filters=effective_filters,
                msg="No groups match filter — merge skipped (OQ-FSM-4 A)",
            )
            ref_hash = ""
            ref_stack_path = None
            ref_info = None
        else:
            ref_hash = self._select_reference_group(
                _filtered_groups, multi_group_config.reference_group, _filtered_group_stacks,
                registration_metrics=_ref_registration_metrics,
            )
            if ref_hash not in _filtered_group_stacks:
                # Fallback if user-specified group failed (auf Kandidatenmenge)
                ref_hash = max(_filtered_group_stacks.keys(), key=lambda h: _filtered_groups[h].frame_count)
                self.logger.warning("multi_group.reference_fallback", ref_hash=ref_hash)
            ref_stack_path = _filtered_group_stacks[ref_hash]
            ref_info = _filtered_groups[ref_hash]
        # Nur loggen wenn Referenz existiert (Kandidaten vorhanden)
        if ref_info is not None:
            ref_log_kwargs = {
                "group_hash": ref_hash,
                "strategy": multi_group_config.reference_group,
                "frame_count": ref_info.frame_count,
                "exptime": ref_info.key[0] if ref_info.key else 0,
            }
            # V1.3-5: zero_shift_ratio der Gewinner-Gruppe additiv loggen, sofern
            # quality-Strategie und Metriken vorhanden (diagnostisch für die
            # Qualitäts-Wahl; andere Strategien unverändert).
            if multi_group_config.reference_group == "quality":
                ref_metrics = _ref_registration_metrics.get(ref_hash) or {}
                ref_frames_registered = int(ref_metrics.get("frames_registered") or 0)
                if ref_frames_registered > 0:
                    ref_log_kwargs["zero_shift_ratio"] = round(
                        int(ref_metrics.get("zero_shift_count") or 0)
                        / ref_frames_registered,
                        6,
                    )
            self.logger.info("multi_group.reference_group", **ref_log_kwargs)

        # 6. Pass 2: Cross-group registration on stack level
        # V1.3-5-Hinweis: Die Cross-Group-Registration nutzt bei
        # astroalign-Fehlschlag einen Translation-only-Fallback (fft-Shift);
        # bei starker Feldrotation (M13, AZ bis 13°) kann das zu einem
        # verdrehten Merge-Bild führen. V1.4-2: rotation_fft (Log-Polar-FFT)
        # schätzt und wendet die Rotation als Cross-Group-Methode oder
        # zusätzliche Fallback-Stufe an; WCS-Persistierung via CD-Matrix.
        # FSM-B: Pass2 nur für Kandidaten (AC-FSM-B6 — keine Metriken für excluded)
        if candidate_hashes is not None and not candidate_hashes:
            aligned_stacks: dict[str, Path] = {}
            cross_group_registrations: list[dict] = []
            rejected_groups: list[dict] = []
        else:
            aligned_stacks: dict[str, Path] = {ref_hash: ref_stack_path}  # ref needs no alignment
            cross_group_registrations: list[dict] = []  # CR-001 P3-B: Metriken pro Registration (AC-P3-2)
            rejected_groups: list[dict] = []  # RE-F (V1.3-24): astroalign-Rejects (Report, additiv)

        for group_hash, stack_path in _filtered_group_stacks.items():
            if group_hash == ref_hash:
                continue

            info = _filtered_groups[group_hash]
            filter_name = info.key[2] if len(info.key) > 2 else ""
            stack_dir = (info.working_dir / "04_stacked"
                         if info.working_dir
                         else self.working_dir / f"group_{group_hash}" / "04_stacked")

            # V1.4-20: EQ-Modus der Ziel-Gruppe (True=EQ, False=AZ,
            # unbekannt=None) — Basis fuer die unexpected_rotation-
            # Diagnose in der W2-QC. Nur bei bekanntem Modus durchreichen
            # (best effort: bestehende Mocks/Aufrufer ohne eq-kwarg bleiben
            # kompatibel, wenn die EQMODE-Infos fehlen).
            eqmode_majority = eqmode_by_group.get(group_hash, {}).get("majority")
            reg_eq_kwargs: dict = {}
            if eqmode_majority in (0, 1):
                reg_eq_kwargs["eq"] = eqmode_majority == 1
            # V19-REG-SMART E5 Cross-Group immer astroalign 20° (fixed, unabhaengig von Intra-Group)
            _cross_params = proc_params
            try:
                import copy as _copy_cg
                _cross_params = _copy_cg.deepcopy(proc_params)
                _cg_reg = _cross_params.get("registration", {}) or {}
                _cg_reg.update({
                    "method": _cross_group_reg_cfg.get("method", "astroalign"),
                    "max_rotation_deg": float(_cross_group_reg_cfg.get("max_rotation_deg", 20.0)),
                    "max_scale_dev": float(_cross_group_reg_cfg.get("max_scale_dev", 0.05)),
                })
                _cross_params["registration"] = _cg_reg
            except Exception:
                _cross_params = proc_params
            reg_result = self._register_to_reference_stack(
                stack_path, ref_stack_path, str(filter_name), stack_dir,
                params=_cross_params,
                **reg_eq_kwargs,
            )
            if reg_result.status == "rejected":
                # RE-F (V1.3-24, AC-RE-F1): astroalign-Gewinner unter der
                # Zero-Shift-Schwelle — Stack wird NICHT registriert (kein
                # Merge-Beitrag; R1-Semantik: "verwerfen" auf Stack-Ebene =
                # Ausschluss aus aligned_stacks). Grund landet additiv in
                # skipped_groups (Report-Sektion, W7) — Metriken bleiben in
                # cross_group_registrations sichtbar (status="rejected").
                rejected_groups.append({
                    "group": group_hash,
                    "reason": "astroalign_below_zero_shift_threshold",
                    "corr_hp": reg_result.corr_hp,
                })
            else:
                aligned_stacks[group_hash] = reg_result.path
            cross_group_registrations.append({
                "group": group_hash,
                "reference": ref_hash,
                "shift_y": reg_result.shift_y,
                "shift_x": reg_result.shift_x,
                "correlation": reg_result.correlation,   # rückwärtskompatibel (P3-B)
                "corr_roh": reg_result.correlation,      # W2: Diagnose (Roh, post-shift)
                "corr_hp": reg_result.corr_hp,           # W2: Hauptmetrik (Hochpass, post-shift)
                "status": reg_result.status,
                # W9-D2 (AC-W9-D2, OQ-W9-5): Transform-Parameter additiv —
                # bestehende Felder unverändert, keine Umbenennung.
                "method": reg_result.method,             # "fft" | "astroalign" | "rotation_fft"
                "rotation_deg": reg_result.rotation_deg,
                "scale": reg_result.scale,
                "n_control_points": reg_result.n_control_points,
                # V1.4-20 (LDN 935) + V1.4-21 (M13): Diagnose additiv —
                # status_reasons (low_corr_roh/few_control_points/
                # unexpected_rotation) + EQMODE-Modi (0=AZ, 1=EQ, None)
                # beider Seiten; nachvollziehbar in merge_report.json.
                "status_reasons": reg_result.status_reasons,
                "eqmode_majority": eqmode_by_group.get(group_hash, {}).get("majority"),
                "ref_eqmode_majority": eqmode_by_group.get(ref_hash, {}).get("majority"),
            })

        # V1.6-4: Compute group-average rotation (median) from cross-group
        # registrations.  The unexpected_rotation quality-gate criterion
        # checks against this median instead of against the reference frame
        # (which may itself have a slight rotation, causing the entire
        # group to be falsely flagged).
        group_rotations = [
            e.get("rotation_deg", 0.0) for e in cross_group_registrations
        ]
        group_avg_rotation = (
            float(np.median(group_rotations)) if group_rotations else 0.0
        )

        # CR-001 W3 (AC-W3-1/2) + W13 (AC-W13-1/2) + W7-Erweiterung (AC-W7-2):
        # min_correlation-Sicherheitsnetz. Nicht-Referenz-Gruppen mit
        # corr_hp < min_correlation (NACH W1-Handling) werden aus dem Merge
        # AUSGESCHLOSSEN; Stacks bleiben unter group_*/04_stacked/ erhalten
        # (kein Cleanup); Grund landet in skipped_groups (Report-Sektion, W7).
        # Referenz wird nie geskippt. Gruppen mit frame_count < 3 werden NIE
        # geskippt (W13) — preview_paths stammen aus stacked.fits VOR dem
        # Skip-Filter (W7-Erweiterung).
        # FSM-B: Filter-Gate zuerst (früh), Korrelations-Gate danach innerhalb Kandidaten (AC-FSM-B6)
        min_correlation = (multi_group_config.merge.min_correlation
                           if multi_group_config.merge else 0.1)
        # skipped_groups startet mit filter_excluded (AC-FSM-B3), W3 additiv danach
        skipped_groups: list[dict] = list(filter_excluded_skipped)
        _w3_skipped: list[dict] = []
        if min_correlation is not None and min_correlation > 0.0 and aligned_stacks:
            aligned_stacks, _w3_skipped = self._apply_cross_group_skip_filter(
                aligned_stacks, cross_group_registrations, ref_hash, min_correlation,
                group_metadata=group_metadata,
                preview_paths=preview_paths,
                working_dir=self.working_dir,
                # V1.4-21 (M13): EQMODE-Majority je Gruppe (0=AZ, 1=EQ,
                # None=unbekannt) — eq_mix_az_eq-Kriterium im Mehrmesswert-
                # Gate (best effort; ohne Header-Info keine Mix-Regel).
                group_eqmode={
                    gh: d.get("majority") for gh, d in eqmode_by_group.items()
                },
                # V1.6-4: Gruppen-Durchschnittsrotation fuer die
                # unexpected_rotation-Qualitaets-Pruefung (statt 0.0/
                # Referenz-Frame-Rotation).
                group_avg_rotation=group_avg_rotation,
            )
            skipped_groups.extend(_w3_skipped)

        # RE-F (V1.3-24): Rejected-Gruppen zusaetzlich in die Report-Sektion
        # aufnehmen (additiv zu den W3-Skips; kein Cleanup, Stacks bleiben
        # unaligniert unter group_*/04_stacked/ erhalten).
        if rejected_groups:
            skipped_groups.extend(rejected_groups)

        # P2-1 (ray-Review, R3-Randfall): Intra-Group-Skips (nur Referenz-
        # Frame registriert, alle Nicht-Referenz-Frames verworfen) additiv
        # in die Report-Sektion aufnehmen — gleiche Semantik wie
        # skipped_groups/rejected_groups (kein Cleanup, kein Crash).
        if skipped_intra_groups:
            skipped_groups.extend(skipped_intra_groups)

        # 7. PCC per group stack (T6)
        pcc_stacks: dict[str, Path] = {}
        pcc_fallback_groups: list[str] = []

        # DEF-014: PCC nur wenn Preset-Step "photometric_color_calibration"
        # vorhanden ist. Analog zum Single-Group-Pfad in processing_agent.py
        # Zeile 292 (_has_step("photometric_color_calibration")).
        # Ohne diesen Check laeuft PCC im Multi-Group-Pfad immer — unabhaengig
        # von pcc.enabled: false im suggested.yaml (CLI-Override-Noop trifft
        # nur die Preset-Step-Liste, nicht den _apply_pcc_per_group-Aufruf).
        pcc_step_active = _has_step("photometric_color_calibration")
        if not pcc_step_active:
            self.logger.info(
                "multi_group.pcc_skipped_no_preset_step",
                msg="photometric_color_calibration not in preset steps — PCC skipped (DEF-014)",
            )

        # Compute pixel scale once (shared across groups).
        # F-META-1.2 (stella Punkt 5): Stack-Skala aus dem verankerten
        # stack_scale_factor der Registrations-Config (KEIN fester
        # 4.0-Faktor; Teleskop (z.B. Dwarf3): nativ 2.9 µm, 2x Superpixel-Debayer).
        reg_cfg = proc_params.get("registration", {}) or {}
        stack_scale_factor = float(reg_cfg.get("stack_scale_factor", 2.0))
        focal = context.equipment.focal_length_mm
        pix_um = context.equipment.pixel_size_um
        if focal and pix_um and focal > 0 and pix_um > 0:
            pixel_scale = compute_pixel_scale(focal, pix_um, binning=stack_scale_factor)
        else:
            pixel_scale = 0.0

        # F-META-1.2: wcs_info aus vorhandener Datenhaltung (Zielkoordinaten +
        # Pixel-Skala) — analog zum Single-Group-Pfad in run().
        wcs_info: dict | None = None
        if (
            context.target.ra is not None
            and context.target.dec is not None
            and pixel_scale > 0
        ):
            wcs_info = {
                "ra": context.target.ra,
                "dec": context.target.dec,
                "pixel_scale_arcsec": pixel_scale,
            }

        # V1.6 (stella/Boris 2026-08-20): PCC-Strategie
        # pcc_per_group=True (Config/Default False): PCC pro Gruppe (altes Verhalten)
        # pcc_per_group=False: PCC auf MERGED Stack (alle Frames, max S/N)
        do_pcc_per_group = getattr(multi_group_config, "pcc_per_group", False)

        # V1.7-5 (Always Multi-Group, AC-A5/A6): Bei genau 1 Gruppe IST der
        # Gruppen-Stack bereits der finale Stack (alle Frames) — ein PCC auf
        # dem "Merge" waere identisch mit PCC auf diesem Stack. pcc_per_group
        # =False (Default) wird deshalb fuer den Single-Group-Fall lokal auf
        # True abgebildet: Daten aequivalent, aber der bestehende Per-Group-
        # Hook pflegt group_metadata.pcc_status, Preview und Fallback-Marker
        # automatisch (gleiche Kette wie bei N Gruppen).
        if len(groups) == 1 and not do_pcc_per_group:
            self.logger.info(
                "multi_group.pcc_single_group_on_group_stack",
                msg="Single group: PCC applied on the group stack (identical data to merged)",
            )
            do_pcc_per_group = True

        # DEF-014: Preset-Step-Gate — wenn kein PCC-Step im Preset, beide
        # PCC-Pfade (per-group + merged) deaktivieren.
        if not pcc_step_active:
            do_pcc_per_group = False

        if do_pcc_per_group:
            # Alt: PCC pro Gruppe — FSM-B: nur Kandidaten (aligned_stacks ist gefiltert)
            for group_hash, stack_path in aligned_stacks.items():
                info = _filtered_groups.get(group_hash) or groups.get(group_hash)
                if info is None:
                    continue
                group_dir = (info.working_dir
                             if info.working_dir
                             else self.working_dir / f"group_{group_hash}")

                # V1.8-1 (DEF-005): Per-Group pixel scale (fallback materialization
                # may change the effective stack_scale_factor).
                group_meta = group_metadata.get(group_hash) or {}
                group_ssf = group_meta.get("effective_stack_scale_factor")
                if group_ssf is None:
                    group_ssf = stack_scale_factor
                if focal and pix_um and focal > 0 and pix_um > 0:
                    group_pixel_scale = compute_pixel_scale(focal, pix_um, binning=float(group_ssf))
                else:
                    group_pixel_scale = 0.0

                pcc_path, pcc_status = self._apply_pcc_per_group(
                    stack_path, context, multi_group_config,
                    group_dir, group_pixel_scale,
                    ra=context.target.ra, dec=context.target.dec,
                    group_metadata=group_meta,
                )
                pcc_stacks[group_hash] = pcc_path

                # CR-001 P2 (AC-P2-1..5): Preview je Gruppe nach PCC (farbkalibriert),
                # Dateiname preview_{group_hash}.jpg in 04_stacked/ (AC-P2-2/3).
                # Hook ist NICHT an pcc_status gebunden → auch bei Gray-World-Fallback
                # (AC-P2-4, PCC_FALLBACK_GRAY_WORLD.txt bleibt Indikator). Fehler → nur
                # Gruppe betroffen, nie Run-Abbruch (AC-P2-5, try/except + Continue).
                try:
                    preview_path = create_preview_jpg(
                        pcc_path,
                        group_dir / "04_stacked" / f"preview_{group_hash}.jpg",
                        preview_config=preview_cfg,
                    )
                    if preview_path is None:
                        self.logger.warning("multi_group.preview_failed", hash=group_hash,
                                            reason="create_preview_jpg_returned_none")
                except Exception as e:
                    self.logger.warning("multi_group.preview_failed", hash=group_hash, error=str(e))

                if group_hash in group_metadata:
                    group_metadata[group_hash]["pcc_status"] = pcc_status

                # DEF-010/011: PCC Grünstich Fallback — wenn PCC rejected (implausible
                # factors), bleibt Stack linear grün. Preview SCNR (preview_export.scnr true)
                # wirkt nur im JPG, nicht im FITS. Fallback: SCNR im linearen Pfad
                # (0.5) auf den Stack anwenden, damit FITS nicht grünstichig bleibt.
                # Status bleibt "rejected_implausible_factors" fuer Agent-Log Persistenz
                # (Tests erwarten exakten String), SCNR wird best-effort appliziert.
                if pcc_status == "rejected_implausible_factors":
                    try:
                        from ..core.pcc import scnr as _scnr_fallback
                        _scnr_fallback(
                            pcc_path,
                            {"scnr_amount": 0.5},
                            load_frame=self.load_frame,
                            save_frame=self.save_frame,
                            logger=self.logger,
                        )
                        self.logger.info("multi_group.pcc_rejected_scnr_applied", group=group_hash, amount=0.5)
                    except Exception as e:
                        self.logger.warning("multi_group.pcc_rejected_scnr_failed", group=group_hash, error=str(e))

                if pcc_status == "fallback_gray_world":
                    pcc_fallback_groups.append(group_hash)
        else:
            # Neu: Kein PCC pro Gruppe -> aligned stacks direkt mergen
            # pcc_stacks wird für Merge verwendet (un-PCC'd)
            pcc_stacks = aligned_stacks
            self.logger.info("multi_group.pcc_per_group_disabled",
                             msg="Skipping per-group PCC, will apply PCC on merged stack")

        # 8. Merge stacks (via MergeAgent — Phase 3, T10)
        effective_target = target_name or context.target.name
        safe_target = effective_target.replace(" ", "_").replace("(", "").replace(")", "")

        # CR-001 W14 (AC-W14-2) + V1.3-5: Referenz-Wahl deterministisch
        # dokumentieren — Sektion `reference_selection` {method, group,
        # signal_scores?, quality_scores?, fallback_reason?} in
        # merge_report.json + mg_metadata.
        # FSM-B: Auf Kandidatenmenge dokumentieren (AC-FSM-B1/B2), bei 0 Kandidaten leer.
        if candidate_hashes is not None and not candidate_hashes:
            reference_selection = {"method": "frame_count", "group": "", "signal_scores": {}}
        else:
            reference_selection = self._build_reference_selection(
                _filtered_groups, multi_group_config.reference_group, ref_hash, _filtered_group_stacks,
                registration_metrics=_ref_registration_metrics,
            )

        # V1.4-21 (M13): Modus der Referenz + Mix-Doku additiv in der
        # reference_selection-Sektion (merge_report.json) — "Referenzwahl
        # bevorzugt Gruppe gleichen Modus (bzw. im Merge-Report vermerken,
        # dass Modus-Mix vorliegt)": die Qualitaetswahl selbst bleibt
        # unveraendert (V1.3-5); der Modus-Mix wird dokumentiert und das
        # Cross-Group-Gate (eq_mix_az_eq) schuetzt den Merge.
        reference_selection["eqmode"] = {
            "ref_group_majority": eqmode_by_group.get(ref_hash, {}).get("majority"),
            "majority_by_group": {
                gh: d.get("majority") for gh, d in eqmode_by_group.items()
            },
            "mix_detected": len({
                d.get("majority") for d in eqmode_by_group.values()
                if d.get("majority") in (0, 1)
            }) >= 2,
        }

        merged_path: Path | None = None
        merge_report: dict = {}

        if len(groups) == 1:
            # V1.7-5 (Always Multi-Group, AC-A4/C5/OQ-AMG-4): Kein MergeAgent-
            # Aufruf bei genau 1 Gruppe — der Guard "< 2 Stacks" wuerde sonst
            # merge.insufficient_stacks erzeugen (M92-Abnahme verbietet das).
            # Stattdessen kanonische Materialisierung: Der (ggf. PCC-korri-
            # gierte) Gruppen-Stack wird nach merged/{safe_target}_merged.fits
            # kopiert — UNABHAENGIG von --merge/--no-merge (AC-C5), denn der
            # Gruppen-Stack ist bereits das Merge-Resultat (N=1).
            # FSM-B: Wenn Filter die einzige Gruppe ausschliesst → Merge-Skip (OQ-FSM-4 A)
            if candidate_hashes is not None and not candidate_hashes:
                self.logger.warning(
                    "multi_group.merge_skipped_filter_excluded",
                    reason="filter_excluded_single_group",
                    filters=effective_filters,
                )
                merged_path = None
                merge_report = {"error": "insufficient_stacks", "reason": "filter_excluded"}
            else:
                single_hash = next(iter(pcc_stacks))
                # F-01: Guard src=None (Test Mock liefert (None, status)) — fallback auf aligned/group.
                src = pcc_stacks.get(single_hash) or aligned_stacks.get(single_hash) or group_stacks.get(single_hash)
                if src is None:
                    self.logger.warning(
                        "multi_group.pcc_none_fallback",
                        hash=single_hash,
                        src=None,
                        action="no_source_available",
                    )
                    self.logger.warning(
                        "multi_group.single_group_merged_export_failed",
                        src=None,
                        error="pcc_stack is None and fallback unavailable",
                    )
                    merged_path = None
                else:
                    if src != pcc_stacks.get(single_hash):
                        self.logger.warning(
                            "multi_group.pcc_none_fallback",
                            hash=single_hash,
                            src=str(src),
                            fallback="aligned_or_group",
                        )
                    merged_dir = self.working_dir / "merged"
                    try:
                        merged_dir.mkdir(parents=True, exist_ok=True)
                        merged_path = merged_dir / f"{safe_target}_merged.fits"
                        shutil.copy2(src, merged_path)
                        self.logger.info(
                            "multi_group.single_group_merged_export",
                            src=str(src),
                            dst=str(merged_path),
                        )
                    except Exception as e:
                        # Konsistent mit Merge-Fail-Handling: Fehler loggen, Lauf
                        # laeuft mit merged_path=None weiter (kein Abbruch).
                        # F-01: logger.error -> warning ( _LogRecorder hat kein error() )
                        self.logger.warning(
                            "multi_group.single_group_merged_export_failed",
                            src=str(src),
                            error=str(e),
                        )
        elif merge_agent is not None:
            # FSM-B: Merge nur Kandidaten (AC-FSM-B1), Metadaten gefiltert für korrekte MG*-Header
            _merge_meta = _filtered_group_metadata if candidate_hashes is not None else group_metadata
            # Merge-Skip bei <2 Kandidaten (OQ-FSM-4 A) — Gruppen-Stacks bleiben erhalten
            if candidate_hashes is not None and len(pcc_stacks) < 2:
                self.logger.warning(
                    "multi_group.merge_skipped_filter",
                    candidates=len(pcc_stacks),
                    filters=effective_filters,
                    excluded=[e["group"] for e in filter_excluded_skipped],
                    msg="Filter leaves <2 candidates — merge skipped (OQ-FSM-4 A)",
                )
            merge_result = merge_agent.run(
                group_stacks=pcc_stacks,
                group_metadata=_merge_meta,
                target_name=effective_target,
                merge_config=multi_group_config.merge,
                pcc_fallback_groups=pcc_fallback_groups,
                cross_group_registrations=cross_group_registrations,
                skipped_groups=skipped_groups,  # CR-001 W3 (AC-W3-1) + FSM-B filter_excluded
                reference_selection=reference_selection,  # CR-001 W14 (AC-W14-2)
                preview_config=preview_cfg,
            )
            merged_path = merge_result.merged_path
            merge_report = merge_result.merge_report

            # V1.6 (stella/Boris 2026-08-20): PCC auf MERGED Stack (pcc_per_group=False)
            # DEF-014: pcc_step_active-Gate — kein PCC wenn Preset keinen Step hat.
            if pcc_step_active and not do_pcc_per_group and merged_path and merged_path.exists():
                self.logger.info("multi_group.pcc_on_merged", path=str(merged_path))
                # Copy to pcc_applied.fits in merged dir
                merged_dir = self.working_dir / "merged"
                merged_dir.mkdir(parents=True, exist_ok=True)
                pcc_merged_path = merged_dir / "pcc_applied.fits"
                try:
                    # shutil ist Modul-Import (kein lokaler Import hier —
                    # der wuerde den Namen fuer die GESAMTE Funktion lokal
                    # machen und die Single-Group-Materialisierung oben
                    # mit UnboundLocalError brechen).
                    shutil.copy2(merged_path, pcc_merged_path)
                    # Call PCC via the injected function (same as per-group)
                    # We need to use the processing agent's PCC method
                    # For now, use the multi_group_config's pcc_fallback strategy
                    proc_params = {}
                    # ray Review Fix 1 (2026-08-21): Return AUSWERTEN — der
                    # Status muss bis ProcessingResult.pcc_status durch-
                    # kommen (agent-log.yaml + run-info.json), sonst bleibt
                    # es fälschlich "pending" (z.B. bei Quality-Gate-
                    # Rejection).
                    merged_pcc_result_path, merged_pcc_status = self._apply_pcc_per_group(
                        pcc_merged_path, context, multi_group_config,
                        merged_dir, pixel_scale,
                        ra=context.target.ra, dec=context.target.dec,
                        group_metadata={"merged": True, "groups": list(aligned_stacks.keys())},
                    )
                    self.last_merged_pcc_status = merged_pcc_status
                    # DEF-010/011 Grünstich: bei Merged-PCC Rejection SCNR im linearen Pfad
                    if merged_pcc_status == "rejected_implausible_factors":
                        try:
                            from ..core.pcc import scnr as _scnr_merged
                            _scnr_merged(
                                Path(merged_pcc_result_path),
                                {"scnr_amount": 0.5},
                                load_frame=self.load_frame,
                                save_frame=self.save_frame,
                                logger=self.logger,
                            )
                            self.logger.info("multi_group.pcc_merged_rejected_scnr_applied", amount=0.5)
                        except Exception as e:
                            self.logger.warning("multi_group.pcc_merged_rejected_scnr_failed", error=str(e))
                    # ray-Major-3 (2026-08-21): Return-Pfad des Hooks ver-
                    # wenden — das PCC-Artefakt liegt unter merged/04_stacked/
                    # pcc_applied.fits (der Hook kopiert stack_path intern
                    # dorthin und arbeitet in-place), NICHT auf der Rohkopie
                    # merged/pcc_applied.fits. Vorher zeigte merged_path auf
                    # die unkorrigierte Kopie -> Export/Preview/Header-
                    # Annotierung enthielten den linearen Stack, die Korrek-
                    # tur ging verloren. Bei Gate-Rejection enthaelt der
                    # Return-Pfad die unveraenderte (lineare) Kopie — nichts
                    # wird ueberschrieben, Verhalten unveraendert.
                    merged_path = Path(merged_pcc_result_path)
                    self.logger.info("multi_group.pcc_on_merged_complete",
                                     path=str(merged_path),
                                     pcc_status=merged_pcc_status)
                except Exception as e:
                    self.logger.warning("multi_group.pcc_on_merged_failed",
                                        error=str(e))
                    # Fallback to un-PCC'd merged_path
        else:
            self.logger.warning("multi_group.merge_skipped",
                                msg="No MergeAgent provided — merge step skipped")

        # 8b. Plugin-Steps (PL-B, SE-D): EINMAL auf dem finalen Merge
        # (OQ-SE-4, Empfehlung A), VOR dem Export (AC-SE-D3) und VOR dem
        # Cleanup. Der Kern materialisiert den gemergten Stack als
        # 04_stacked/stacked.fits (Plugin-Input-Konvention, SE-B2-Vertrag),
        # sofern der Merge existiert. Ein erfolgreicher Plugin-Lauf mit
        # FITS-Artefakt in 04_stacked/ ersetzt den aktuellen Stack
        # (Uebernahme, AC-SE-B2) -> Export/Preview basieren auf Enhanced.
        # Fix-Sammlung v1.3 §3 (P0): Root-`04_stacked` entsteht im Multi-
        # Group-Modus NUR LAZY hier und NUR wenn der Preset tatsaechlich
        # Plugin-Steps enthaelt (sonst waere der materialisierte
        # Root-Stack ein reines Artefakt — C19-Befund). Ohne
        # `has_plugin_steps`-Hook (Direkt-Nutzer/Tests) bleibt die
        # Materialisierung unbedingt (bisheriges Verhalten).
        materialize_plugin_stack = (
            bool(self.has_plugin_steps(pipeline))
            if self.has_plugin_steps is not None
            else True
        )
        if merged_path and merged_path.exists() and materialize_plugin_stack:
            try:
                self.stacked_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(merged_path, self.stacked_dir / "stacked.fits")
                self.logger.info("multi_group.plugin_stack_materialized",
                                 src=str(merged_path),
                                 dst=str(self.stacked_dir / "stacked.fits"))
            except Exception as e:
                self.logger.warning("multi_group.plugin_stack_materialize_failed",
                                    src=str(merged_path), error=str(e))
        plugin_results = self.run_plugin_steps(pipeline, context)
        for pr in plugin_results:
            artifact = pr.artifact
            if (
                artifact is not None
                and artifact.suffix.lower() == ".fits"
                and artifact.parent == self.stacked_dir
            ):
                self.logger.info("multi_group.plugin_adopted_artifact",
                                 step=pr.step, artifact=str(artifact))
                merged_path = artifact

        # 8c. F-META-1.2: Merge-Export-Header best-effort anreichern
        # (Light-Header-Keys + approximatives WCS + effektive Pixelgroesse
        # XPIXSZ/YPIXSZ, analog Single-Group).
        if merged_path and merged_path.exists():
            # F-META-1.2 (stella Punkt 5): effektive Pixelgroesse aus der
            # verankerten Registrations-Config (Precedence CLI > Config >
            # Preset > Default, resolve_registration).
            # V1.8-1 (DEF-005): Single-group fallback materialization may have
            # a different effective stack_scale_factor than the global default.
            export_ssf = float(stack_scale_factor)
            if len(groups) == 1:
                single_group_meta = next(iter(group_metadata.values()))
                single_eff_ssf = single_group_meta.get("effective_stack_scale_factor")
                if single_eff_ssf is not None:
                    export_ssf = float(single_eff_ssf)
            export_wcs_info = wcs_info
            if export_ssf != float(stack_scale_factor):
                if focal and pix_um and focal > 0 and pix_um > 0:
                    export_pixel_scale = compute_pixel_scale(focal, pix_um, binning=export_ssf)
                else:
                    export_pixel_scale = 0.0
                if (
                    context.target.ra is not None
                    and context.target.dec is not None
                    and export_pixel_scale > 0
                ):
                    export_wcs_info = {
                        "ra": context.target.ra,
                        "dec": context.target.dec,
                        "pixel_scale_arcsec": export_pixel_scale,
                    }
            annotate_export_header(
                merged_path, context, wcs=export_wcs_info,
                stack_scale_factor=export_ssf,
            )

        # 9. Export merged result (final FITS lives ONLY in merged/ — v1.11:
        # no top-level copy; single-group top-level *_final.fits unchanged)
        merged_dir = self.working_dir / "merged"
        exports: list[Path] = []

        if merged_path and merged_path.exists():
            exports.append(merged_path)

            # V1.8-3 (AC-FITS-A2): optionaler gestreckter FITS fuer den Merge
            # (additiv, nie Ersatz fuer den linearen merged-FITS).
            stretched_enabled = (
                export_cfg is not None and export_cfg.stretched_fits is True
            )
            if stretched_enabled:
                stretched_out = merged_dir / f"{safe_target}_merged_stretched.fits"
                stretched = export_stretched_fits(
                    merged_path, stretched_out, export_cfg
                )
                if stretched:
                    exports.append(stretched)

            # Create auto-stretched JPG preview
            jpg_out = merged_dir / f"{safe_target}_merged_preview.jpg"
            preview = create_preview_jpg(
                merged_path, jpg_out,
                preview_config=preview_cfg,
            )
            if preview:
                exports.append(preview)

            # Copy PCC fallback marker to merged dir if any group used fallback
            if pcc_fallback_groups:
                marker_src = self.working_dir / f"group_{pcc_fallback_groups[0]}" / "04_stacked" / "PCC_FALLBACK_GRAY_WORLD.txt"
                if marker_src.exists():
                    try:
                        shutil.copy2(marker_src, merged_dir / "PCC_FALLBACK_GRAY_WORLD.txt")
                    except Exception as e:
                        self.logger.warning("archive.copy_failed",
                                            src=str(marker_src),
                                            dst=str(merged_dir / "PCC_FALLBACK_GRAY_WORLD.txt"),
                                            error=str(e))

        # 10. Cleanup group working dirs (T7 — default: delete)
        if not multi_group_config.keep_group_working_dirs:
            self._cleanup_group_dirs(groups, safe_target)

        self.logger.info("multi_group.complete",
                         groups=len(groups), merged=merged_path is not None,
                         pcc_fallback_groups=len(pcc_fallback_groups))

        # Build multi_group_metadata for archive agent-log (M2/ray)
        mg_metadata = {
            "groups": group_metadata,
            "method": multi_group_config.merge.method if multi_group_config.merge else "weighted_average",
            "weight_by": multi_group_config.merge.weight_by if multi_group_config.merge else "frame_count",
            "reference_group": ref_hash,
            "reference_selection": reference_selection,  # CR-001 W14 (AC-W14-2)
            "pcc_fallback_groups": pcc_fallback_groups,
            "skipped_groups": skipped_groups,  # CR-001 W3 (AC-W3-1)
            # V1.3-3 (stella-Befund 4): Cross-Group-Registrations-Metriken
            # (Pass 2 — der M13-Fehlerort). corr_hp/method/rotation_deg/scale/
            # n_control_points/status je Nicht-Referenz-Gruppe. Additiv —
            # Legacy ohne Feld bleibt [].
            # V1.3-5-Hinweis: Bei astroalign-Fehlschlag Translation-only-
            # Fallback (fft-Shift); bei starker Feldrotation (M13, AZ bis
            # 13°) kann das zu einem verdrehten Merge-Bild führen. V1.4-2:
            # rotation_fft (Log-Polar-FFT) als Cross-Group-Methode oder
            # zusätzliche Fallback-Stufe; WCS via CD-Matrix.
            "cross_group_registrations": cross_group_registrations,
        }
        # V1.7-1 FSM-C2/C4: effektive Filter-Liste + Zuordnung Kandidat/excluded je Gruppe (additiv, nur wenn Filter gesetzt — AC-FSM-B5)
        if effective_filters is not None:
            mg_metadata["merge_filters"] = list(effective_filters)
            # Details je Gruppe (Hash -> {filter, status: candidate|filter_excluded}) für Transparenz (AC-C2)
            _filter_status: dict[str, dict] = {}
            for _gh, _meta in group_metadata.items():
                _fv = _meta.get("filter")
                # candidate_hashes enthält nur Kandidaten (bei effective_filters != None)
                _is_candidate = (_gh in candidate_hashes) if candidate_hashes is not None else True
                _filter_status[_gh] = {
                    "filter": _fv,
                    "status": "candidate" if _is_candidate else "filter_excluded",
                }
            mg_metadata["filter_status"] = _filter_status
            # Optional: Tippfehler-Hinweis (bereits geloggt, hier zusätzlich dokumentiert)
            _group_norm = set()
            for _m in group_metadata.values():
                _fv2 = _m.get("filter")
                _group_norm.add("" if _fv2 is None else str(_fv2).strip().lower())
            _unmatched = [f for f in set(effective_filters) if f not in _group_norm]
            if _unmatched:
                mg_metadata["filter_warnings"] = {
                    "unmatched_filters": _unmatched,
                    "available_filters": sorted(_group_norm),
                    "hint": "Verdacht Tippfehler: Filter-Wert passt zu keiner Gruppe",
                }

        return self.processing_result_class(
            stacked=merged_path,
            exports=exports,
            multi_group_metadata=mg_metadata,
            # V1.3-3 (stella-Befund 4): Registrierungs-Metriken aggregiert je
            # Gruppe (Per-Group-dicts aus group_metadata, NUR Gruppen MIT
            # Metriken — legacy-frei). Damit zeigt processing.registration_
            # metrics im agent-log auch bei Multi-Group-Laeufen die corr_hp-
            # Verteilung/method_counts (Single-Pfad fuellt es in run()).
            registration_metrics={
                "mode": "multi_group",
                "groups": {
                    gh: dict(meta.get("registration_metrics") or {})
                    for gh, meta in group_metadata.items()
                    if meta.get("registration_metrics")
                },
            },
            # V1.8-2 (AC-PREV-A5): effektive Preview/Export-Pipeline Settings.
            preview_export=preview_cfg.model_dump() if preview_cfg is not None else None,
            # V1.8-3 (AC-FITS-A4): Gestretchter FITS Status fuer agent-log/inspect.
            stretched_fits={
                "enabled": bool(export_cfg.stretched_fits) if export_cfg is not None else False,
                "created": any(e.name.endswith("_stretched.fits") for e in exports),
                "method": export_cfg.stretch.method if export_cfg is not None else "asinh",
                "a": export_cfg.stretch.a if export_cfg is not None else 0.01,
            },
        )

    def _cleanup_group_dirs(self, groups: dict[str, GroupInfo], target_name: str) -> None:
        """Remove per-group working directories after successful merge.

        Refactor 2026-08-14 (Cluster 6): Delegation auf Modul-Funktion
        ``cleanup_group_dirs`` (moved from ProcessingAgent). Der Logger
        wird durchgereicht (``self.logger``), damit Events wie
        ``multi_group.cleanup_group_dir`` konsistent ueber den Agent-Logger
        laufen.
        """
        cleanup_group_dirs(groups, target_name, logger=self.logger)
