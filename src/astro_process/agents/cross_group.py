"""Cross-Group Functions (V1.7-7 Batch 1+2).

Batch 1 (Reference Selection):
  compute_group_signal_scores, signal_winner_if_any, quality_winner_if_any,
  select_reference_group, build_reference_selection

Batch 2 (Registration + Skip + PCC + Cleanup):
  apply_cross_group_skip_filter, consolidate_eqmode_values, copy_wcs_headers,
  register_to_reference_stack, apply_pcc_per_group, cleanup_group_dirs

Original: ``ProcessingAgent``-Methoden (Cluster 6, 2026-08-14) ->
``multi_group_agent.py`` (Modul-Funktionen) -> ``cross_group.py`` (V1.7-7).

Keine Logik-Änderungen, nur Modul-Verschiebung + Import-Anpassung.
"""

from __future__ import annotations

import math
import shutil
import structlog
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import numpy as np
from astropy.io import fits
from scipy.ndimage import gaussian_filter
from scipy.ndimage import shift as scipy_shift

from ..config.models import FrameSelectionConfig, MultiGroupConfig, PipelinePreset
from ..config.loader import is_merge_filter_match, normalize_merge_filters
from ..core.export import annotate_export_header
from ..core.gradient_removal import background_extraction
from ..core.pcc import compute_pixel_scale, photometric_color_calibration
from ..core.preview import create_preview_jpg
from ..core.quality import (
    FrameQuality,
    compute_frame_score,
    qual_to_dict,
    reject_outlier_frames,
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
from ..core.stacking import stack_frames
from ..models.core import GroupInfo, ObservationContext, compute_group_hash

if TYPE_CHECKING:
    from ..agents.merge_agent import MergeAgent

if TYPE_CHECKING:
    from ..agents.merge_agent import MergeAgent

logger = structlog.get_logger(__name__)

# ray Review Fix 2 (2026-08-21): PCC-Statuswerte OHNE erfolgreiche
# Katalog-Kalibrierung. MG-Header (MGCNTGRP/MGMETHOD=pcc) duerfen nur bei
# Erfolgsstatus geschrieben werden — sonst meldet der Idempotenz-Check
# (apply_pcc_per_group) und der standalone merge (cli.py) beim Re-Run
# fälschlich "gaia_success".
PCC_NON_SUCCESS_STATUSES: frozenset = frozenset({
    "rejected_implausible_factors",
    "fallback_gray_world",
    "skipped",
    "pcc_skipped",
})


# ═══════════════════════════════════════════════════════════════════
# Reference Group Selection (Refactor: moved from multi_group_agent.py,
# V1.7-7 Batch 1 — Reference Selection Functions)
# ═══════════════════════════════════════════════════════════════════


def compute_group_signal_scores(
    group_stacks: dict[str, Path], *, logger=None,
) -> dict[str, float]:
    """CR-001 W14: Deterministisches Signalmaß je Gruppe (AC-W14-2).

    Signalmaß = quantile95 − median auf dem G-Kanal (bzw. Mono für 2D)
    aus `04_stacked/stacked.fits`. Begründung (stella G.2/H.1): 15s60 ist
    verwaschen (corr_hp 0.020, 15 s ohne Flats) → kleines Maß; 60s40 hat
    bei korrekter Verschiebung deutliches Sternsignal (0.835) → größeres
    Maß. Datei-Lesefehler → Gruppe wird mit Score 0.0 ausgeschlossen
    (Fallback-Regel greift in process_multi_group).

    Refactor: moved from ``ProcessingAgent._compute_group_signal_scores``
    (Cluster 6, unveraendert — Modul-Funktion statt @staticmethod).

    Args:
        group_stacks: {group_hash: stacked.fits path}.

    Returns:
        {group_hash: float} — deterministisch, gleiche Eingabe → gleiche
        Werte (kein RNG).
    """
    log = logger or structlog.get_logger(__name__)
    scores: dict[str, float] = {}
    for gh, stack_path in group_stacks.items():
        try:
            with fits.open(stack_path) as hdul:
                data = hdul[0].data.astype(np.float32)
            if data.ndim == 3:
                data = data.transpose(1, 2, 0)  # (C, H, W) → (H, W, C)
                g = data[:, :, 1]
            else:
                g = data
            score = float(np.quantile(g, 0.95) - np.median(g))
            scores[gh] = score if score == score else 0.0  # nan → 0.0
        except Exception as e:
            log.warning("multi_group.reference_signal_score_failed",
                        group=gh, error=str(e))
            scores[gh] = 0.0
    return scores


def signal_winner_if_any(
    groups: dict[str, GroupInfo],
    group_stacks: dict[str, Path],
    signal_scores: dict[str, float],
) -> Optional[str]:
    """Reine Signal-Auswahl (ohne Fallback) — für die Report-Doku.

    Gibt den Kandidaten mit der strikt größten Score zurück, sofern die
    Wahl deterministisch ist (kein Gleichstand, mind. ein Kandidat
    ≥ 3 Frames); sonst None. Gleiche Logik wie in
    select_reference_group (strategy="signal"), ohne frame_count-Tiebreak.

    Refactor: moved from ``ProcessingAgent._signal_winner_if_any``
    (Cluster 6, unveraendert — Modul-Funktion statt @staticmethod).
    """
    if not group_stacks:
        return None
    candidates = [
        gh for gh, sc in signal_scores.items()
        if sc > 0.0
        and groups.get(gh) is not None
        and groups[gh].frame_count >= 3
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda gh: signal_scores[gh])
    best_score = signal_scores[best]
    if any(gh != best and abs(signal_scores[gh] - best_score) < 1e-12
           for gh in candidates):
        return None
    return best


def quality_winner_if_any(
    groups: dict[str, GroupInfo],
    group_stacks: Optional[dict[str, Path]],
    registration_metrics: dict[str, dict],
) -> Optional[str]:
    """Reine Qualitäts-Auswahl (ohne Fallback) — für die Report-Doku.

    V1.3-5: Gibt den Kandidaten mit der strikt besten Registrierungs-
    Qualität zurück, sofern mindestens ein Kandidat mit
    frames_registered >= 3 existiert; sonst None. Gleiche Logik wie in
    select_reference_group (strategy="quality").

    Gewichtung (1 → 4):
      1. kleinster Zero-Shift-Anteil
         zero_shift_ratio = zero_shift_count / max(frames_registered, 1)
      2. höchster n_control_points-Median (astroalign-Kontrollpunkte)
      3. höchster corr_hp-Median
      4. meiste Frames (frame_count), dann lexikografisch größter Hash
         (deterministisch — max-Tupel: (-ratio, n_cp, corr, frames, hash))

    Defensive Zugriffe: Fehlende Felder (Legacy) → 0 für Zähler; None-
    Mediane → -inf (Gruppen ohne astroalign/ohne corr_hp verlieren das
    jeweilige Kriterium, ohne zu crashen).

    Refactor: moved from ``ProcessingAgent._quality_winner_if_any``
    (Cluster 6, unveraendert — Modul-Funktion statt @staticmethod).
    """
    if not registration_metrics:
        return None
    candidates: list[tuple[str, float, float, float, int]] = []
    for gh, metrics in registration_metrics.items():
        if groups.get(gh) is None:
            continue
        if group_stacks is not None and gh not in group_stacks:
            continue
        frames_registered = int(metrics.get("frames_registered") or 0)
        if frames_registered < 3:
            # W14-konsistent: Kleinst-Gruppen ≤ 2 Frames sind statistisch
            # nicht belastbar als Referenz.
            continue
        zero_shift_count = int(metrics.get("zero_shift_count") or 0)
        zero_shift_ratio = zero_shift_count / max(frames_registered, 1)
        cp = metrics.get("n_control_points") or {}
        cp_median = cp.get("median")
        n_cp_median = (
            float(cp_median) if cp_median is not None else float("-inf")
        )
        hp = metrics.get("corr_hp") or {}
        hp_median = hp.get("median")
        corr_hp_median = (
            float(hp_median) if hp_median is not None else float("-inf")
        )
        candidates.append((
            gh, zero_shift_ratio, n_cp_median, corr_hp_median,
            groups[gh].frame_count,
        ))
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda c: (-c[1], c[2], c[3], c[4], c[0]),
    )
    return best[0]


def select_reference_group(
    groups: dict[str, GroupInfo],
    strategy: str = "largest",
    group_stacks: Optional[dict[str, Path]] = None,
    registration_metrics: Optional[dict[str, dict]] = None,
    *,
    logger=None,
) -> str:
    """Select the reference group hash based on the configured strategy.

    CR-001 W14 (AC-W14-1/2) + V1.3-5 (Boris-Entscheidung 2026-08-11):
    Default-Strategie ist "quality" — Referenz nach REGISTRIERUNGS-
    QUALITÄT statt Signalmaß. M13-Befund (Leo, Ergänzung 3): "signal"
    wählte die SCHWÄCHSTE Gruppe (15s60, verwaschen) als Referenz →
    Cross-Group-Registration scheiterte → 60s40 (55 Frames, 3300s,
    sauberste corr 0.70–0.76) wurde verworfen (Domino-Effekt). Die
    Qualitäts-Metriken existieren seit V1.3-3 (`registration_metrics`
    je Gruppe in `group_metadata`).

    Qualitäts-Kriterium (Gewichtung 1 → 4):
      1. Primär:  kleinster Zero-Shift-Anteil
                   zero_shift_ratio = zero_shift_count / max(frames_registered, 1)
                   — je kleiner desto besser (Gruppe, deren Frames echte
                     Verschiebungen fanden).
      2. Sekundär: höchster n_control_points-Median (astroalign-
                    Kontrollpunkte — je mehr desto stabiler).
      3. Tertiär:  höchster corr_hp-Median.
      4. Tiebreak: meiste Frames (frame_count), dann lexikografisch
                   Hash (deterministisch).
    Kandidaten-Filter: nur Gruppen mit frames_registered >= 3 (konsistent
    mit W14 frame_count >= 3; Kleinst-Gruppen ≤ 2 Frames sind statistisch
    nicht belastbar). Keine Kandidaten → Fallback largest
    (reason="no_candidates"). Fehlende Metriken (None/leer — Legacy,
    Mocks, Dry-Run, alte Lauf-Objekte) → Fallback largest
    (reason="no_metrics").

    Manuelle Übersteuerung per Config bleibt (Hash-Strategie). Die
    "signal"-Strategie bleibt VOLLSTÄNDIG erhalten (Config-Override).

    Refactor: moved from ``ProcessingAgent._select_reference_group``
    (Cluster 6, unveraendert — Modul-Funktion statt @staticmethod).

    Args:
        groups: Dict mapping group hash → GroupInfo
        strategy: "largest" (most frames), "signal" (Signalmaß, W14),
                  "quality" (Registrierungs-Qualität, Default via
                  MultiGroupConfig) oder ein konkreter Group-Hash
        group_stacks: {group_hash: stacked.fits path} — für
                  strategy == "signal" nötig (fehlt → Fallback largest,
                  z.B. CLI-Dry-Run vor dem Stacking); bei "quality" wird
                  die Kandidatenmenge auf Gruppen mit Stack beschränkt
        registration_metrics: {group_hash: Metriken-Dict} (V1.3-3) —
                  nur für strategy == "quality" nötig (None/leer →
                  Fallback largest, reason="no_metrics")
        logger: Optional structlog-Logger (Agent reicht seinen durch).

    Returns:
        Group hash of the selected reference group
    """
    log = logger or structlog.get_logger(__name__)
    if strategy == "signal":
        if not group_stacks:
            log.warning("multi_group.reference_signal_fallback",
                        reason="no_stacks")
            return max(groups.keys(), key=lambda h: groups[h].frame_count)
        try:
            scores = compute_group_signal_scores(group_stacks, logger=log)
        except Exception as e:
            log.warning("multi_group.reference_signal_fallback",
                        reason="score_error", error=str(e))
            return max(groups.keys(), key=lambda h: groups[h].frame_count)

        # W14-Kandidaten: frame_count >= 3 (Kleinst-Gruppen ≤ 2 Frames
        # sind statistisch nicht belastbar als Referenz — konsistent mit
        # W13) und positives Signalmaß.
        candidates = [
            gh for gh, sc in scores.items()
            if sc > 0.0
            and groups.get(gh) is not None
            and groups[gh].frame_count >= 3
        ]
        if not candidates:
            log.warning("multi_group.reference_signal_fallback",
                        reason="degenerate_scores", scores=scores)
            return max(groups.keys(), key=lambda h: groups[h].frame_count)

        # Deterministisch: strikt größte Score gewinnt; exakter
        # Gleichstand (unentschieden) → Fallback meiste-Frames.
        best = max(candidates, key=lambda gh: (scores[gh], groups[gh].frame_count, gh))
        best_score = scores[best]
        if any(gh != best and abs(scores[gh] - best_score) < 1e-12
               for gh in candidates):
            log.warning("multi_group.reference_signal_tie",
                        fallback="largest")
            return max(groups.keys(), key=lambda h: groups[h].frame_count)
        return best

    if strategy == "quality":
        metrics_by_group = registration_metrics or {}
        # V1.3-5: Fehlende Metriken (Legacy-Ergebnisse, Mocks, Dry-Run,
        # alte Lauf-Objekte) — kein Qualitätsurteil möglich → Fallback
        # auf die meiste-Frames-Regel (largest) + Log.
        if not any(metrics_by_group.values()):
            log.warning("multi_group.reference_quality_fallback",
                        reason="no_metrics")
            return max(groups.keys(), key=lambda h: groups[h].frame_count)
        winner = quality_winner_if_any(
            groups, group_stacks, metrics_by_group,
        )
        if winner is None:
            log.warning("multi_group.reference_quality_fallback",
                        reason="no_candidates")
            return max(groups.keys(), key=lambda h: groups[h].frame_count)
        return winner

    if strategy == "largest":
        return max(groups.keys(), key=lambda h: groups[h].frame_count)

    # User-specified hash — validate it exists
    if strategy in groups:
        return strategy

    # Fallback to largest if user-specified hash not found
    log.warning("multi_group.reference_group_not_found",
                requested=strategy, fallback="largest")
    return max(groups.keys(), key=lambda h: groups[h].frame_count)


# ═══════════════════════════════════════════════════════════════════
# Skip-Filter + EQMODE (V1.7-7 Batch 2 — moved from multi_group_agent.py)
# ═══════════════════════════════════════════════════════════════════


def apply_cross_group_skip_filter(
    aligned_stacks: dict[str, Path],
    cross_group_registrations: list[dict],
    ref_hash: str,
    min_correlation: float,
    group_metadata: Optional[dict] = None,
    preview_paths: Optional[dict] = None,
    working_dir: Optional[Path] = None,
    *,
    group_eqmode: Optional[dict] = None,
    group_avg_rotation: float = 0.0,
    logger=None,
) -> tuple[dict[str, Path], list[dict]]:
    """CR-001 W3 (AC-W3-1/2): `merge.min_correlation`-Sicherheitsnetz.

    Nicht-Referenz-Gruppen mit `corr_hp < min_correlation` (NACH
    W1-Handling — corr_hp ist der post-W1-Wert aus den
    cross_group_registrations) werden aus dem Merge AUSGESCHLOSSEN. Die
    Stacks bleiben unter `group_*/04_stacked/` erhalten (kein Cleanup);
    der Grund landet in `skipped_groups` (Report-Sektion, → W7).

    CR-001 W13 (AC-W13-1/2): Gruppen mit `frame_count < 3` werden NIE
    geskippt (nur warning, Merge inklusive). Bei ≤ 2 Frames ist corr_hp
    statistisch nicht belastbar (Stack ≈ Einzelframe, rauschdominiert);
    das Sicherheitsnetz soll Müll-Stacks abfangen (anderes Feld), nicht
    Kleinst-Gruppen. `min_correlation` gilt nur für Gruppen mit
    `frame_count >= 3`. Ohne `group_metadata` (Direct-Calls/Tests) bleibt
    das W3-Verhalten 1:1.

    CR-001 W7-Erweiterung (AC-W7-2): `skipped_groups[].preview_path`
    (relativ zum `generated/{ts}`-Ordner) — Preview wird VOR dem
    Skip-Filter aus `stacked.fits` erzeugt (unabhängig vom PCC).

    Die Referenz-Gruppe wird NIE geskippt (AC-W3-2): Sie ist der Fixpunkt
    der Cross-Group-Registration und wird selbst nie registriert (die
    Pass-2-Schleife skippt ref_hash). Läge sie hypothetisch unter der
    Schwelle, würde der gesamte Skip-Filter deaktiviert (Merge ohne
    Skip-Filter + warning) — im Normalpfad nie erreichbar, da ref_hash
    keinen Registrations-Eintrag hat; der Guard `group == ref_hash` bleibt
    als Schutz bestehen.

    Refactor: moved from ``ProcessingAgent._apply_cross_group_skip_filter``
    (Cluster 6, unveraendert — Modul-Funktion statt @staticmethod).

    Args:
        aligned_stacks: {group_hash: aligned.fits path} (Pass-2-Ergebnis).
        cross_group_registrations: Registrations-Metriken (AC-P3-2).
        ref_hash: Effektive Referenz-Gruppe (nie geskippt).
        min_correlation: Schwelle aus merge.min_correlation.
        group_metadata: {group_hash: {frame_count, ...}} (Pass-1-Metadaten)
                        für W13 (optional; None → W3-Verhalten 1:1).
        preview_paths: {group_hash: preview_{hash}.jpg path} (W7-Erw.,
                       optional; VOR dem Skip-Filter erzeugt).
        working_dir: generated/{ts}-Ordner — Basis für relative
                     preview_path (optional).
        group_eqmode: {group_hash: EQMODE-Majority (0=AZ, 1=EQ, None=
                      unbekannt)} (V1.4-20/21, optional; None → Mehrmess-
                      wert-Gate ohne EQMODE-Kriterium — best effort,
                      bestehendes Verhalten bleibt 1:1).
        group_avg_rotation: Median-Rotation (Grad) ueber alle Cross-Group-
                      Registrations (V1.6-4). Wird statt 0.0 als Bezugspunkt
                      fuer unexpected_rotation verwendet — verhindert dass
                      eine leichte Referenz-Rotation die gesamte Gruppe
                      fälschlich als "unexpected" markiert.
        logger: Optional structlog-Logger (Agent reicht seinen durch).

    Returns:
        (gefilterte aligned_stacks, skipped_groups) — skipped_groups:
        [{group, reason: "below_min_correlation", corr_hp, min_correlation,
          preview_path?}] bzw. [{group, reason: "cross_group_quality_gate",
          reasons: [low_corr_roh, few_control_points, unexpected_rotation,
          eq_mix_az_eq], corr_hp, corr_roh, n_control_points, rotation_deg,
          eqmode_majority, ref_eqmode_majority, min_correlation,
          preview_path?}] (V1.4-20/21, additiv).
    """
    log = logger or structlog.get_logger(__name__)
    skipped_groups: list[dict] = []
    kept: dict[str, Path] = {}
    for group_hash, path in aligned_stacks.items():
        if group_hash == ref_hash:
            # AC-W3-2: Referenz wird NIE geskippt (Fixpunkt der Registration).
            kept[group_hash] = path
            continue
        entry = next(
            (e for e in cross_group_registrations if e.get("group") == group_hash),
            None,
        )
        corr_hp = float(entry.get("corr_hp", 1.0)) if entry else 1.0

        # W13 (AC-W13-1/2): frame_count < 3 → NIE skippen (warning).
        # Ohne group_metadata (None) bleibt das W3-Verhalten 1:1.
        frame_count: Optional[int] = None
        if group_metadata is not None:
            frame_count = int(
                (group_metadata.get(group_hash) or {}).get("frame_count", 0)
            )
        if frame_count is not None and frame_count < 3:
            log.warning("multi_group.skip_deactivated_small_group",
                        group=group_hash, frame_count=frame_count,
                        corr_hp=corr_hp,
                        reason="corr_hp_not_reliable_below_3_frames")
            kept[group_hash] = path
            continue

        if corr_hp < min_correlation:
            entry_skip = {
                "group": group_hash,
                "reason": "below_min_correlation",
                "corr_hp": corr_hp,
                "min_correlation": min_correlation,
            }
            # W7-Erweiterung (AC-W7-2): preview_path relativ zum
            # generated/{ts}-Ordner (VOR dem Skip-Filter aus stacked.fits).
            if preview_paths is not None and working_dir is not None:
                pp = preview_paths.get(group_hash)
                if pp is not None:
                    try:
                        entry_skip["preview_path"] = str(
                            Path(pp).relative_to(working_dir)
                        )
                    except ValueError:
                        entry_skip["preview_path"] = str(pp)
            skipped_groups.append(entry_skip)
            log.warning("multi_group.skip_below_min_correlation",
                        group=group_hash, corr_hp=corr_hp,
                        min_correlation=min_correlation)
        else:
            # V1.4-20 (LDN 935) + V1.4-21 (M13): Mehrmesswert-Gate.
            # corr_hp allein kann eine falsche Transformation durchlassen
            # (LDN 935: corr_hp 0.538 > 0.1, aber corr_roh 0.005,
            # n_CP 23, Rotation 2.26° bei EQ → Merge verdreht).
            # Zusaetzliche Kriterien (best effort — unbekannte Werte
            # bzw. fehlende EQMODE-Infos blocken das Gate nicht):
            #   low_corr_roh          corr_roh < 0.05
            #   few_control_points    n_control_points < 30 (astroalign)
            #   unexpected_rotation   EQ-Gruppe + |rotation_deg| > 1°
            #   eq_mix_az_eq          Gruppenmodus ≠ Referenzmodus
            # Bei Gruenden: Gruppe NICHT in den Merge (eigener Stack bleibt
            # unter group_*/04_stacked/ erhalten, kein Cleanup — gleiche
            # Semantik wie below_min_correlation). W13 (frame_count < 3)
            # ist bereits oberhalb geprueft (NIE skippen).
            quality_reasons: list[str] = []
            gate_metrics: dict = {}
            if entry is not None:
                corr_roh = float(
                    entry.get("corr_roh", entry.get("correlation", 1.0)) or 1.0
                )
                n_cp_raw = entry.get("n_control_points")
                n_cp = int(n_cp_raw) if n_cp_raw is not None else None
                rotation_deg = float(entry.get("rotation_deg", 0.0) or 0.0)
                gate_metrics = {
                    "corr_roh": round(corr_roh, 6),
                    "n_control_points": n_cp,
                    "rotation_deg": round(rotation_deg, 6),
                }
                if corr_roh < 0.05:
                    quality_reasons.append("low_corr_roh")
                if n_cp is not None and n_cp < 30:
                    quality_reasons.append("few_control_points")
                eq_here = (group_eqmode or {}).get(group_hash)
                eq_ref = (group_eqmode or {}).get(ref_hash)
                gate_metrics["eqmode_majority"] = eq_here
                gate_metrics["ref_eqmode_majority"] = eq_ref
                if (
                    eq_here is not None
                    and eq_ref is not None
                    and eq_here != eq_ref
                ):
                    quality_reasons.append("eq_mix_az_eq")
                # unexpected_rotation nur bei EQ — AZ hat Feldrotation
                # (bis ~13°, astroalign kompensiert pro Frame).
                # V1.6-4: Rotation gegen Gruppen-Durchschnitt pruefen
                # (nicht gegen 0.0/Referenz-Frame), damit eine leichte
                # Referenz-Rotation nicht die gesamte Gruppe faelschlich
                # als "unexpected" markiert.
                if eq_here == 1 and abs(rotation_deg - group_avg_rotation) > 1.0:
                    quality_reasons.append("unexpected_rotation")
            if quality_reasons:
                entry_skip: dict = {
                    "group": group_hash,
                    "reason": "cross_group_quality_gate",
                    "reasons": quality_reasons,
                    "corr_hp": corr_hp,
                    "min_correlation": min_correlation,
                }
                entry_skip.update(gate_metrics)
                # W7-Erweiterung (AC-W7-2): preview_path analog zum
                # corr_hp-Skip (additiv, relativ zum generated/{ts}-Ordner).
                if preview_paths is not None and working_dir is not None:
                    pp = preview_paths.get(group_hash)
                    if pp is not None:
                        try:
                            entry_skip["preview_path"] = str(
                                Path(pp).relative_to(working_dir)
                            )
                        except ValueError:
                            entry_skip["preview_path"] = str(pp)
                skipped_groups.append(entry_skip)
                log.warning(
                    "multi_group.skip_cross_group_quality_gate",
                    group=group_hash, reasons=quality_reasons,
                    corr_hp=corr_hp, min_correlation=min_correlation,
                    corr_roh=gate_metrics.get("corr_roh"),
                    n_control_points=gate_metrics.get("n_control_points"),
                    rotation_deg=gate_metrics.get("rotation_deg"),
                    group_avg_rotation=round(group_avg_rotation, 4),
                    msg=(
                        "Group excluded from merge by multidimensional "
                        "cross-group quality gate (own stack preserved)."
                    ),
                )
            else:
                kept[group_hash] = path
    return kept, skipped_groups


def consolidate_eqmode_values(eq_modes: list[Optional[int]]) -> dict:
    """V1.4-21 (M13): EQMODE-Werte einer Gruppe konsolidieren.

    Der EQMODE-Header steckt in jedem Light-Frame (0=AZ, 1=EQ,
    None=unbekannt; fits_parser liest ihn best effort — vgl. Fix #2).
    Pro Gruppe wird die Mehrheit bestimmt (``majority``), ob die Gruppe
    intern konsistent ist (``consistent`` — alle BEKANNTEN Werte
    identisch) und die Verteilung (``counts``) dokumentiert.

    Konservatives Verhalten bei unbekanntem/uneindeutigem Modus:
    - Alle Werte unbekannt (None) -> majority None, consistent True
      (keine bekannten Widersprueche — keine Mix-Erkennung moeglich).
    - Gleichstand 0 vs. 1 -> majority None, consistent False (Modus
      unklar — Gruppe wird von der AZ/EQ-Mix-Erkennung NICHT als
      Zugehoeriger eines Modus behandelt; keine falsche Mix-Aussage).

    Args:
        eq_modes: EQMODE-Werte der Frames einer Gruppe (0/1/None).

    Returns:
        {"majority": Optional[int], "consistent": bool,
         "counts": {"0": int, "1": int, "None": int}}
    """
    known_values = [em for em in eq_modes if em in (0, 1)]
    counts_0 = known_values.count(0)
    counts_1 = known_values.count(1)
    if not known_values:
        majority: Optional[int] = None
        consistent = True
    else:
        consistent = all(v == known_values[0] for v in known_values)
        if counts_0 == counts_1:
            majority = None  # Gleichstand -> Modus unklar
        else:
            majority = 1 if counts_1 > counts_0 else 0
    return {
        "majority": majority,
        "consistent": consistent,
        "counts": {
            "0": counts_0,
            "1": counts_1,
            "None": len(eq_modes) - len(known_values),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# Per-Group PCC (T6) + Cleanup (Refactor: moved from multi_group_agent.py,
# V1.7-7 Split Step 2b — moved from ProcessingAgent._apply_pcc_per_group/
# _cleanup_group_dirs via multi_group_agent.py)
# ═══════════════════════════════════════════════════════════════════


# ray Review Fix 2 (2026-08-21): PCC-Statuswerte OHNE erfolgreiche
# Katalog-Kalibrierung. MG-Header (MGCNTGRP/MGMETHOD=pcc) duerfen nur bei
# Erfolgsstatus geschrieben werden — sonst meldet der Idempotenz-Check
# (apply_pcc_per_group) und der standalone merge (cli.py) beim Re-Run
# fälschlich "gaia_success".
PCC_NON_SUCCESS_STATUSES: frozenset = frozenset({
    "rejected_implausible_factors",
    "fallback_gray_world",
    "skipped",
    "pcc_skipped",
})


def apply_pcc_per_group(
    stack_path: Path, context: ObservationContext,
    multi_group_config: MultiGroupConfig, group_dir: Path,
    *,
    photometric_color_calibration_fn,
    logger=None,
    pixel_scale_arcsec: float = 0.0,
    ra: Optional[float] = None, dec: Optional[float] = None,
    group_metadata: Optional[dict] = None,
) -> tuple[Path, str]:
    """Apply PCC to one group stack. Idempotent — skips if already applied.

    Refactor: moved from ``ProcessingAgent._apply_pcc_per_group``
    (Cluster 6, unveraendert — Modul-Funktion statt Methode). Der PCC-
    Schritt selbst wird als Callable ``photometric_color_calibration_fn``
    injiziert (Agent reicht ``_photometric_color_calibration`` durch —
    Tests patchen diese auf dem Agent).

    Args:
        stack_path: Path to the (pre-PCC) stacked or aligned FITS
        context: Observation context (for ra/dec fallback)
        multi_group_config: Multi-group config (for pcc_fallback strategy)
        group_dir: Group's working directory
        photometric_color_calibration_fn: Callable (stacked, params, *,
            ra=, dec=, pixel_scale_arcsec=) -> None.
        logger: Optional structlog-Logger (Agent reicht seinen durch).
        pixel_scale_arcsec: Pixel scale in arcsec/pixel
        ra, dec: Target coordinates in degrees
        group_metadata: Group metadata dict (for MGFRAME/TOTALEXP headers)

    Returns:
        Tuple of (pcc_path: Path, status: str)
        Status is one of: "gaia_success", "fallback_gray_world",
                          "skipped", "failed"
    """
    log = logger or structlog.get_logger(__name__)
    stacked_dir = group_dir / "04_stacked"
    stacked_dir.mkdir(parents=True, exist_ok=True)

    # Destination: pcc_applied.fits
    pcc_path = stacked_dir / "pcc_applied.fits"
    marker_path = stacked_dir / "PCC_FALLBACK_GRAY_WORLD.txt"

    # Idempotency check: if pcc_applied.fits already exists and has been
    # PCC-corrected (marker file or MG*-headers), skip re-processing.
    if pcc_path.exists():
        # ray Review Fix 2: Rejection-Marker ZUERST — er ist autoritativ
        # (auch gegen Legacy-Artefakte mit fälschlichen MG-Headern).
        rejected_marker = stacked_dir / "PCC_REJECTED_FACTORS.txt"
        if rejected_marker.exists():
            log.info("pcc.already_applied_rejected", path=str(pcc_path))
            return pcc_path, "rejected_implausible_factors"
        # Check for MG headers indicating prior PCC
        try:
            with fits.open(pcc_path) as hdul:
                if "MGCNTGRP" in hdul[0].header:
                    log.info("pcc.already_applied", path=str(pcc_path))
                    return pcc_path, "gaia_success"
        except Exception as e:
            log.warning("pcc.idempotency_check_failed", path=str(pcc_path),
                        error=str(e))
        # Check for fallback marker
        if marker_path.exists():
            log.info("pcc.already_applied_fallback", path=str(pcc_path))
            return pcc_path, "fallback_gray_world"

    # Copy input stack to pcc_applied.fits (PCC modifies in place)
    try:
        shutil.copy2(stack_path, pcc_path)
    except Exception as e:
        log.error("pcc.copy_failed", error=str(e))
        return stack_path, "skipped"

    # Call existing PCC method (handles GAIA + gray-world fallback internally)
    # The _photometric_color_calibration method works in-place on pcc_path
    proc_params = {}  # params dict is not used by PCC logic itself
    try:
        photometric_color_calibration_fn(
            pcc_path, proc_params,
            ra=ra, dec=dec,
            pixel_scale_arcsec=pixel_scale_arcsec,
        )
    except Exception as e:
        fallback = multi_group_config.pcc_fallback
        log.warning("pcc.per_group_failed", hash=group_dir.name, error=str(e), fallback=fallback)
        if fallback == "fail":
            raise
        # For "skip" fallback, keep the uncorrected copy
        return pcc_path, "skipped"

    # Determine status from PCC_STATUS.txt (written by photometric_color_calibration
    # using PCCResult.status — precise status instead of marker-file heuristics).
    status_path = stacked_dir / "PCC_STATUS.txt"
    if status_path.exists():
        try:
            status_text = status_path.read_text().strip()
            # Format: "pcc_status=<value>"
            if status_text.startswith("pcc_status="):
                status = status_text.split("=", 1)[1]
                log.info("pcc.per_group_status", hash=group_dir.name, status=status)
                # Add MG marker headers for standalone merge sub-command
                # (M1/ray fix) — NUR bei Erfolgsstatus (ray Review Fix 2):
                # bei rejected/skipped/gray_world wuerde der Idempotenz-
                # Check beim Re-Run fälschlich gaia_success melden.
                if status not in PCC_NON_SUCCESS_STATUSES:
                    try:
                        with fits.open(pcc_path, mode='update') as hdul:
                            hdul[0].header["MGCNTGRP"] = 1
                            hdul[0].header["MGMETHOD"] = "pcc"
                            hdul[0].header["MGVER"] = "1.0"
                            hdul[0].header["MGFRAME"] = (group_metadata or {}).get("frame_count", 0)
                            hdul[0].header["TOTALEXP"] = (group_metadata or {}).get("total_exposure", 0.0)
                    except Exception as e:
                        log.warning("pcc.mg_header_write_failed", path=str(pcc_path),
                                    error=str(e))
                else:
                    log.info("pcc.mg_headers_skipped_non_success",
                             hash=group_dir.name, status=status)
                return pcc_path, status
        except Exception as e:
            log.warning("pcc.status_read_failed", path=str(status_path), error=str(e))

    # Fallback: legacy marker-file detection (backwards compatibility
    # for runs without PCC_STATUS.txt — e.g., external callers).
    if marker_path.exists():
        log.info("pcc.per_group_status", hash=group_dir.name, status="fallback_gray_world")
        return pcc_path, "fallback_gray_world"

    skip_marker_path = stacked_dir / "PCC_SKIPPED.txt"
    if skip_marker_path.exists():
        log.info("pcc.per_group_status", hash=group_dir.name, status="skipped")
        return pcc_path, "skipped"

    # Check MG headers for GAIA success
    try:
        with fits.open(pcc_path) as hdul:
            has_mg = "MGCNTGRP" in hdul[0].header
    except Exception as e:
        log.warning("pcc.mg_header_read_failed", path=str(pcc_path),
                    error=str(e))
        has_mg = False

    # If no marker and no failure exception, GAIA PCC succeeded
    log.info("pcc.per_group_status", hash=group_dir.name, status="gaia_success")
    # Add MG marker headers for standalone merge sub-command (M1/ray fix)
    try:
        with fits.open(pcc_path, mode='update') as hdul:
            hdul[0].header["MGCNTGRP"] = 1
            hdul[0].header["MGMETHOD"] = "pcc"
            hdul[0].header["MGVER"] = "1.0"
            # Write frame_count and total_exposure for standalone merge sub-command
            # (used by `astra merge` to compute weights from FITS headers)
            hdul[0].header["MGFRAME"] = (group_metadata or {}).get("frame_count", 0)
            hdul[0].header["TOTALEXP"] = (group_metadata or {}).get("total_exposure", 0.0)
    except Exception as e:
        log.warning("pcc.mg_header_write_failed", path=str(pcc_path),
                    error=str(e))

    return pcc_path, "gaia_success"


def cleanup_group_dirs(
    groups: dict[str, GroupInfo], target_name: str, *,
    logger=None,
) -> None:
    """Remove per-group working directories after successful merge.

    Refactor: moved from ``ProcessingAgent._cleanup_group_dirs``
    (Cluster 6, unveraendert — Modul-Funktion statt Methode; optionaler
    ``logger``-Parameter, damit der Agent seinen Modul-Logger durchreicht
    und ``processing_agent_mod.logger``-Patches in Tests greifen).

    Args:
        groups: Dict mapping group hash → GroupInfo
        target_name: Target name for logging
        logger: Optional structlog-Logger (Agent reicht seinen durch).
    """
    log = logger or structlog.get_logger(__name__)
    for group_hash, info in groups.items():
        if info.working_dir and info.working_dir.exists():
            try:
                shutil.rmtree(info.working_dir)
                log.info("multi_group.cleanup_group_dir",
                         hash=group_hash, path=str(info.working_dir))
            except Exception as e:
                log.warning("multi_group.cleanup_failed",
                            hash=group_hash, error=str(e))

    log.info("multi_group.group_dirs_cleaned",
             target=target_name,
             hint="Keep with --keep-groups or keep_group_working_dirs=true (default) for debugging")