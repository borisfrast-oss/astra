"""Frame Selection + Outlier Rejection Pipeline (V1.7-2 FSEL-B/C/D).

Extracted from multi_group_agent.py (Split V1.7-7 Schritt 1).
Pure selection/rejection logic — no dependency on Merge/Registration/PCC.

Input: FrameQuality lists + Configs → Output: Filter paths + Log details.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional

import structlog

from .quality import FrameQuality, compute_frame_score
from ..config.models import FrameSelectionConfig

logger = structlog.get_logger(__name__)


def _resolve_frame_selection_config(
    proc_params: dict,
    app_config=None,
) -> FrameSelectionConfig:
    """FSEL-B/D: Effektive FrameSelectionConfig aufloesen (Precedence CLI > Config > Preset).

    CLI-Override wird in cli.py via resolve_frame_selection (CLI > Config > Preset)
    bereits in pipeline.processing_params.frame_selection und cfg.frame_selection
    verankert (siehe cli.process.frame_selection). Dieser Helper bleibt
    kompatibel fuer Direktaufrufe (Tests) ohne CLI: Config > Preset > Default.
    Fuer CLI-Laeufe liefert die cfg-Mutation den CLI-Gewinner — die hier
    erneute Config-Pruefung gibt ihn zurueck (korrekte Precedence).

    Args:
        proc_params: ``pipeline.processing_params.model_dump()``-dict.
        app_config: ``AppConfig``-Instanz (optional, z.B. ``self.config``).

    Returns:
        FrameSelectionConfig mit effektiven Werten.
    """
    # Preset-Ebene
    preset_fs = proc_params.get("frame_selection") if isinstance(proc_params, dict) else None
    preset_cfg: FrameSelectionConfig | None = None
    if isinstance(preset_fs, dict):
        try:
            preset_cfg = FrameSelectionConfig(**preset_fs)
        except Exception:
            preset_cfg = None
    elif isinstance(preset_fs, FrameSelectionConfig):
        preset_cfg = preset_fs

    # Config-Ebene (AppConfig.frame_selection) gewinnt — darin steckt bei
    # CLI-Laeufen bereits der CLI-Gewinner (cfg.frame_selection = effective_fs).
    if app_config is not None:
        cfg_fs = getattr(app_config, "frame_selection", None)
        if isinstance(cfg_fs, FrameSelectionConfig):
            return cfg_fs
        if isinstance(cfg_fs, dict):
            try:
                return FrameSelectionConfig(**cfg_fs)
            except Exception:
                pass

    if preset_cfg is not None:
        return preset_cfg
    return FrameSelectionConfig()


def _resolve_rejection_config(
    proc_params: dict,
    app_config=None,
) -> tuple[bool, dict, bool]:
    """FSEL-C: Effektive Outlier-Rejection-Config aufloesen (Precedence Config > Preset).

    Rejection liegt als flache Felder in ProcessingParams (rejection_enabled,
    rejection_thresholds, rejection_elongation) und als optionale Top-Level-
    Overrides in AppConfig (rejection_enabled etc.). Keine CLI-Flags fuer
    Rejection in v1.7 — nur Config/Preset. Default disabled (byte-identical).

    Returns:
        Tuple (enabled, thresholds_dict, elongation_enabled)
    """
    preset_enabled = False
    preset_thresholds: dict = {}
    preset_elongation = True
    if isinstance(proc_params, dict):
        # bool | None handling — None bedeutet "nicht gesetzt"
        v = proc_params.get("rejection_enabled")
        if v is not None:
            preset_enabled = bool(v)
        vt = proc_params.get("rejection_thresholds")
        if isinstance(vt, dict):
            preset_thresholds = dict(vt)
        ve = proc_params.get("rejection_elongation")
        if ve is not None:
            preset_elongation = bool(ve)

    if app_config is not None:
        cfg_e = getattr(app_config, "rejection_enabled", None)
        if cfg_e is not None:
            preset_enabled = bool(cfg_e)
        cfg_t = getattr(app_config, "rejection_thresholds", None)
        if isinstance(cfg_t, dict):
            preset_thresholds = dict(cfg_t)
        elif cfg_t is not None:
            # None -> no override, {} -> explicit empty
            pass
        cfg_el = getattr(app_config, "rejection_elongation", None)
        if cfg_el is not None:
            preset_elongation = bool(cfg_el)

    if preset_thresholds is None:
        preset_thresholds = {}
    return bool(preset_enabled), dict(preset_thresholds), bool(preset_elongation)


# V1.8-8 (DEF-006): Mandatory corr_hp Gate
DEFAULT_MIN_CORR_HP = 0.05


def _resolve_min_corr_hp_config(
    proc_params: dict,
    app_config=None,
) -> float | None:
    """V1.8-8 (DEF-006): Effektiven rejection_min_corr_hp aufloesen.

    Precedence: Config (AppConfig.rejection_min_corr_hp) > Preset
    (proc_params rejection_min_corr_hp) > Default 0.05.
    Explizites None/null deaktiviert das Gate. Analog V1.4-20
    min_correlation (0.1), aber intra-group vor Stacking, mandatory für
    average (stella a+c).

    Returns:
        float Schwelle oder None wenn deaktiviert.
    """
    preset_val: float | None = 0.05
    if isinstance(proc_params, dict) and "rejection_min_corr_hp" in proc_params:
        # None bedeutet explizit deaktiviert (preset kann null setzen)
        preset_val = proc_params.get("rejection_min_corr_hp")
    # Config override — unterscheide nicht gesetzt vs explizit null
    if app_config is not None:
        fields_set = getattr(app_config, "model_fields_set", set())
        if "rejection_min_corr_hp" in fields_set:
            return getattr(app_config, "rejection_min_corr_hp")
        cfg_v = getattr(app_config, "rejection_min_corr_hp", None)
        if cfg_v is not None:
            return cfg_v
        # Falls via Dict-Konstruktion ohne fields_set aber Wert vorhanden
        # (Tests) — nimm cfg_v wenn fields_set leer aber Wert nicht None?
        # Bereits oben: falls nicht in fields_set aber cfg_v nicht None, return.
    return preset_val


def _apply_mandatory_average_filter(
    registered: List[Path],
    qualities: List[FrameQuality],
    min_corr_hp: float | None,
    group_hash: str,
    logger=None,
) -> tuple[List[Path], int, list[str]]:
    """V1.8-8 (DEF-006 stella a+c): Mandatory Filter für Average-Pfad.

    Verwirft wenn outlier_excluded==True ODER corr_hp < min_corr_hp
    (Default 0.05, Analog V1.4-20 Cross-Group-Gate). Wirkt auch bei
    rejection_enabled==False (mandatory Gate, nicht an Flag hängend).
    Bestehende Qualities.outlier_excluded werden respektiert (a), zusätzlich
    corr_hp-Gate (c) — kombiniert.

    Mapping: Path -> FrameQuality via frame string (as_posix + name, Windows-robust)
    analog _apply_selection_and_rejection. Referenz-Frames (correlation None)
    werden nie via Gate verworfen.

    Args:
        registered: Registrierte Pfade (nach Perzentil/Threshold).
        qualities: FrameQuality-Liste dieser Gruppe (aus register_frames).
        min_corr_hp: Schwelle (None=deaktiviert).
        group_hash: Für Logging.
        logger: Optional structlog logger.

    Returns:
        Tuple (filtered_registered, n_rejected, rejected_frame_strs)
    """
    log = logger or structlog.get_logger(__name__)
    if not registered:
        return registered, 0, []
    if min_corr_hp is None:
        return registered, 0, []
    # Build lookup: frame string variants -> FrameQuality
    q_by_posix: dict[str, FrameQuality] = {}
    q_by_name: dict[str, FrameQuality] = {}
    q_by_raw: dict[str, FrameQuality] = {}
    for q in qualities:
        if q.frame is not None:
            posix = Path(q.frame).as_posix()
            name = Path(q.frame).name
            q_by_posix[posix] = q
            q_by_name[name] = q
            q_by_raw[q.frame] = q
            q_by_raw[str(q.frame)] = q

    def _find_q(p: Path) -> FrameQuality | None:
        # Windows-robust: posix, raw, name
        q = q_by_posix.get(p.as_posix())
        if q is not None:
            return q
        q = q_by_raw.get(str(p))
        if q is not None:
            return q
        q = q_by_name.get(p.name)
        if q is not None:
            return q
        q = q_by_raw.get(p.name)
        return q

    filtered: List[Path] = []
    rejected_strs: list[str] = []
    for idx, p in enumerate(registered):
        q = _find_q(p)
        if q is None:
            # Fallback: positional mapping fuer Intra-Group (DEF-011 M27 60s40)
            # deb_*.fits (qualities) vs reg_*.fits (registered) haben unterschiedliche
            # Namen (deb_0047 vs reg_0000). Name-Lookup schlaegt fehl -> Ghosting
            # bleibt (threshold_rejected 0 trotz corr 0.04). Positional gilt:
            # registered[i] <-> qualities[i] wenn Längen gleich (kein RE-F Reject).
            # Bei Längendifferenz (RE-F Rejects) konservativ behalten.
            if len(registered) == len(qualities) and 0 <= idx < len(qualities):
                q = qualities[idx]
                # Nur nutzen wenn correlation plausibel (M27 Beleg: corr 0.04)
                # Referenz hat correlation None -> nicht filtern, daher ok.
            else:
                # Kein Mapping: konservativ behalten (nicht verwerfen ohne Metrik)
                filtered.append(p)
                continue
            if q is None:
                filtered.append(p)
                continue
        # Condition (a): outlier_excluded True -> verwerfen
        if getattr(q, "outlier_excluded", False):
            rejected_strs.append(p.as_posix())
            continue
        # Condition (c): corr_hp < Schwelle -> verwerfen (nur wenn correlation vorhanden)
        corr = getattr(q, "correlation", None)
        if corr is not None:
            try:
                fv = float(corr)
            except Exception:
                fv = None  # type: ignore
            if fv is not None and fv < float(min_corr_hp):
                rejected_strs.append(p.as_posix())
                continue
        filtered.append(p)

    n_rejected = len(rejected_strs)
    if n_rejected > 0:
        log.info(
            "selection.mandatory_rejected",
            group=group_hash,
            total=len(registered),
            rejected=n_rejected,
            stacked=len(filtered),
            min_corr_hp=min_corr_hp,
            rejected_frames=rejected_strs,
        )
    return filtered, n_rejected, rejected_strs


def _apply_frame_selection(
    registered: List[Path],
    qualities: List[FrameQuality],
    config: FrameSelectionConfig,
    group_hash: str,
    logger=None,
) -> List[Path]:
    """FSEL-B: Perzentilbasierte Auswahl je Gruppe (AC-FSEL-B1..B6).

    Nach Registration (Scores liegen vor), vor Stacking — nur Lights,
    je Gruppe unabhängig (AC-FSEL-B5/B6, V1.5-5).

    Logik:
      - Scores via ``compute_frame_score(qualities, weights)`` (FSEL-A).
      - Lights sortieren nach Score (hoch = gut), unterste
        (100-keep_percentile)% verwerfen (AC-FSEL-B2).
      - Rundungsregel floor der Verwurf-Anzahl dokumentiert (AC-FSEL-B3):
        discard = floor(N * (100-keep_percentile)/100).
      - Bei 0 Verwürfen Pipeline unverändert.
      - Bei <min_frames verbleibend komplett skippen mit Warning
        ``selection.skipped_min_frames`` und ALLE Frames stacken (AC-FSEL-B4).

    Args:
        registered: Registrierte Frame-Pfade dieser Gruppe (Stack-Eingabe).
        qualities: FrameQuality-Liste dieser Gruppe (gleiche Gruppe,
            beliebige Reihenfolge, aus register_frames).
        config: Effektive FrameSelectionConfig.
        group_hash: Gruppen-ID für Logging.
        logger: Optional structlog-Logger.

    Returns:
        Gefilterte ``registered``-Liste (oder unverändert bei disabled/0/skip).
    """
    log = logger or structlog.get_logger(__name__)
    if not config.enabled:
        return registered
    if not registered:
        return registered
    if not qualities:
        return registered

    n = len(registered)
    # Rundungsregel floor (AC-FSEL-B3) — deterministisch dokumentiert.
    discard = math.floor(n * (100 - config.keep_percentile) / 100.0)
    keep = n - discard
    if discard <= 0:
        log.info(
            "selection.no_discard",
            group=group_hash,
            total=n,
            keep_percentile=config.keep_percentile,
            discard=0,
            keep=n,
            reason="floor_rounding_zero",
        )
        return registered
    if keep < config.min_frames:
        log.warning(
            "selection.skipped_min_frames",
            group=group_hash,
            total=n,
            keep_percentile=config.keep_percentile,
            discard=discard,
            keep=keep,
            min_frames=config.min_frames,
            action="all_frames_stacked",
        )
        return registered

    # Scores berechnen (FSEL-A) — session-relativ Median/MAD.
    try:
        scores = compute_frame_score(qualities, weights=config.weights)
    except Exception as e:
        log.warning("selection.score_failed", group=group_hash, error=str(e), action="all_frames_stacked")
        return registered

    if len(scores) != len(qualities):
        log.warning(
            "selection.score_length_mismatch",
            group=group_hash,
            scores=len(scores),
            qualities=len(qualities),
            action="all_frames_stacked",
        )
        return registered

    # Mapping FrameQuality.frame -> score, dann registered nach Score sortieren.
    # Fallback: falls FrameQuality.frame nicht zu Path passt (z.B. None), via
    # Index-Zuordnung der sortierten Scores auf registered (best effort).
    # Primär: Pfad-basierte Zuordnung (robust bei Reihenfolge-Differenzen).

    # Build lookup path-string -> score (beste score je Pfad falls Duplikate)
    # Windows-Robust: speichere sowohl as_posix als auch Name (AC-FSEL-A5, Pfad-Match robust)
    from pathlib import Path

    score_by_frame: dict[str, float] = {}
    score_by_name: dict[str, float] = {}
    for q, s in zip(qualities, scores):
        if q.frame is not None:
            # Posix-normalisierter Key (robust gegen Windows Backslash)
            key_posix = Path(q.frame).as_posix()
            name_key = Path(q.frame).name
            # Bei Duplikaten höheren Score behalten
            prev = score_by_frame.get(key_posix)
            if prev is None or s > prev:
                score_by_frame[key_posix] = s
            prev_n = score_by_name.get(name_key)
            if prev_n is None or s > prev_n:
                score_by_name[name_key] = s
            # Legacy: original string als Key ebenfalls (falls bereits posix)
            prev_orig = score_by_frame.get(q.frame)
            if prev_orig is None or s > prev_orig:
                score_by_frame[q.frame] = s

    # Falls lookup leer (alle frame=None), fallback auf Index-Reihenfolge:
    # qualities und registered sind dann index-korreliert (register_frames
    # behält Reihenfolge: qualities[0] = Referenz = registered[0]).
    if not score_by_frame:
        # Index-basiert: qualities und registered parallel (längere qualities)
        # → nimm die besten keep Indizes aus qualities, filtere registered
        # via Position? Aber registered ist subset (keine Rejects) → komplex.
        # Fallback: wenn kein Pfad-Match möglich, keine Selektion.
        log.warning(
            "selection.no_frame_mapping",
            group=group_hash,
            action="all_frames_stacked",
        )
        return registered

    # Scores für registered ermitteln (fehlende → worst 0.0, AC-FSEL-A5)
    scored_registered: list[tuple[Path, float]] = []
    for p in registered:
        # Windows-robust: probiere as_posix, original str, und Name
        s = score_by_frame.get(p.as_posix())
        if s is None:
            s = score_by_frame.get(str(p))
        if s is None:
            s = score_by_name.get(p.name)
        if s is None:
            s = score_by_frame.get(p.name)
        if s is None:
            s = 0.0
        scored_registered.append((p, s))

    # Sortieren nach Score absteigend (hoch = gut), unterste discard verwerfen
    scored_registered.sort(key=lambda x: x[1], reverse=True)
    kept = scored_registered[:keep]
    discarded = scored_registered[keep:]

    kept_paths = [p for p, _ in kept]

    log.info(
        "selection.applied",
        group=group_hash,
        total=n,
        keep=keep,
        discard=discard,
        keep_percentile=config.keep_percentile,
        min_frames=config.min_frames,
        discarded_frames=[str(p) for p, _ in discarded],
        kept_frames=[str(p) for p, _ in kept],
    )
    return kept_paths


def _percentile_selection_details(
    registered: List[Path],
    qualities: List[FrameQuality],
    config: FrameSelectionConfig,
    group_hash: str,
    logger=None,
) -> dict:
    """FSEL-C/D: Perzentil-Details ohne Filterung (fuer Trichter-Zaehlung).

    Berechnet Scores, Discard/Keep-Anzahlen und Cutoff deterministisch,
    ohne registered zu mutieren. Wird vom kombinierten
    _apply_selection_and_rejection fuer die Trichter-Kette und die
    per-frame Entscheidung verwendet.

    Returns:
        dict mit total, keep, discard, scores (List[float] in qualities-Reihenfolge),
        score_by_frame, scored_registered (sorted), cutoff_score, skipped_min_frames,
        kept_frames (set), discarded_frames (set).
    """
    from pathlib import Path

    log = logger or structlog.get_logger(__name__)
    n = len(registered)
    discard = math.floor(n * (100 - config.keep_percentile) / 100.0) if config.enabled and n > 0 else 0
    keep = n - discard
    skipped_min = False
    if config.enabled and discard > 0 and keep < config.min_frames:
        skipped_min = True
        discard = 0
        keep = n

    # Scores (FSEL-A) — session-relativ Median/MAD, auch bei skipped/disabled fuer Transparenz.
    try:
        scores = compute_frame_score(qualities, weights=config.weights) if qualities else []
    except Exception as e:
        log.warning("selection.score_failed", group=group_hash, error=str(e))
        scores = [0.0 for _ in qualities]

    if len(scores) != len(qualities):
        scores = [0.0 for _ in qualities]

    # Mapping frame -> score (Windows-robust: posix + name)
    score_by_frame: dict[str, float] = {}
    score_by_name: dict[str, float] = {}
    for q, s in zip(qualities, scores):
        if q.frame is not None:
            key_posix = Path(q.frame).as_posix()
            name_key = Path(q.frame).name
            prev = score_by_frame.get(key_posix)
            if prev is None or s > prev:
                score_by_frame[key_posix] = s
            prev_n = score_by_name.get(name_key)
            if prev_n is None or s > prev_n:
                score_by_name[name_key] = s
            prev_orig = score_by_frame.get(q.frame)
            if prev_orig is None or s > prev_orig:
                score_by_frame[q.frame] = s

    # Scores fuer registered ermitteln + sortiert (robust)
    scored_registered: list[tuple[Path, float]] = []
    for p in registered:
        s = score_by_frame.get(p.as_posix())
        if s is None:
            s = score_by_frame.get(str(p))
        if s is None:
            s = score_by_name.get(p.name)
        if s is None:
            s = score_by_frame.get(p.name)
        if s is None:
            s = 0.0
        scored_registered.append((p, s))
    if scored_registered:
        scored_registered.sort(key=lambda x: x[1], reverse=True)

    cutoff: float | None = None
    if config.enabled and not skipped_min and discard > 0 and scored_registered:
        # Cutoff = niedrigster kept Score (min der kept) — Grund fuer percentile_rejected
        kept_part = scored_registered[:keep] if keep > 0 else []
        if kept_part:
            cutoff = min(s for _, s in kept_part)

    kept_set = set(p.as_posix() for p, _ in scored_registered[:keep]) if not skipped_min else set(p.as_posix() for p in registered)
    discarded_set = set(p.as_posix() for p, _ in scored_registered[keep:]) if (config.enabled and not skipped_min and discard > 0) else set()
    # Auch Name-Sets fuer Windows-Vergleich (robust)
    kept_set_names = set(p.name for p, _ in scored_registered[:keep]) if not skipped_min else set(p.name for p in registered)
    discarded_set_names = set(p.name for p, _ in scored_registered[keep:]) if (config.enabled and not skipped_min and discard > 0) else set()

    return {
        "total": n,
        "keep": keep,
        "discard": discard,
        "skipped_min_frames": skipped_min,
        "scores": scores,
        "score_by_frame": score_by_frame,
        "score_by_name": score_by_name,
        "scored_registered": scored_registered,
        "cutoff_score": cutoff,
        "kept_set": kept_set,
        "discarded_set": discarded_set,
        "kept_set_names": kept_set_names,
        "discarded_set_names": discarded_set_names,
    }


def _apply_selection_and_rejection(
    registered: List[Path],
    qualities: List[FrameQuality],
    fs_config: FrameSelectionConfig,
    rejection_enabled: bool,
    rejection_thresholds: dict,
    rejection_elongation: bool,
    group_hash: str,
    logger=None,
    mandatory_min_corr_hp: float | None = DEFAULT_MIN_CORR_HP,
) -> tuple[List[Path], dict]:
    """FSEL-C1..C3 + FSEL-D1: Kombinierte Perzentil → Threshold Pipeline je Gruppe.

    Reihenfolge (AC-FSEL-C1): zuerst Perzentil-Selektion (relativ), danach
    Threshold-Rejection (absolut) auf dem Rest — keine Doppelt-Verwerfung in
    einer Stufe (ein Frame nur einmal gezaehlt).

    Zaehlt die Trichter-Kette (AC-FSEL-C2): total → percentile_rejected →
    threshold_rejected → stacked, je Gruppe. Unabhängige Schalter (AC-FSEL-C3):
    Deaktivieren eines Mechanismus aendert den anderen nicht.

    Generiert per-frame Entscheidungen fuer agent-log (AC-FSEL-D1):
    score, Entscheidung (kept | percentile_rejected | threshold_rejected),
    Grund/Schwellenkontext (cutoff/Rang bzw. outlier_reject_reason).

    Args:
        registered: Registrierte Pfade dieser Gruppe (Stack-Eingabe, Lights-only).
        qualities: FrameQuality-Liste dieser Gruppe (aus register_frames).
        fs_config: Effektive FrameSelectionConfig.
        rejection_enabled: Ob Threshold-Rejection aktiv ist (config/preset).
        rejection_thresholds: Thresholds-Dict fuer reject_outlier_frames.
        rejection_elongation: elongation_unusable_enabled fuer reject_outlier_frames.
        group_hash: Gruppen-ID fuer Logging.
        logger: Optional structlog-Logger.

    Returns:
        Tuple (final_registered, report) wobei report die Trichter-Zahlen,
        Score-Spanne und per-frame Liste enthaelt (fuer agent-log/ inspect).
    """
    from .quality import reject_outlier_frames

    log = logger or structlog.get_logger(__name__)
    total = len(registered)
    if total == 0:
        return registered, {
            "total": 0,
            "percentile_rejected": 0,
            "threshold_rejected": 0,
            "stacked": 0,
            "keep_percentile": fs_config.keep_percentile if fs_config else 92,
            "enabled": bool(fs_config.enabled) if fs_config else False,
            "weights": dict(fs_config.weights) if fs_config and fs_config.weights else None,
            "min_frames": fs_config.min_frames if fs_config else 3,
            "skipped_min_frames": False,
            "score_min": None,
            "score_max": None,
            "score_median": None,
            "cutoff_score": None,
            "frames": [],
        }

    # — Perzentil-Stufe (FSEL-B) ———————————————
    pct_details = _percentile_selection_details(registered, qualities, fs_config, group_hash, logger=log)
    # Gefilterte Liste nach Perzentil (oder unveraendert bei disabled/skipped)
    after_percentile: List[Path]
    if not fs_config.enabled or pct_details["discard"] == 0 or pct_details["skipped_min_frames"]:
        after_percentile = list(registered)
        percentile_rejected = 0
        # Logging bereits im _apply_frame_selection-Stil fuer Konsistenz
        if fs_config.enabled and pct_details["skipped_min_frames"]:
            log.warning(
                "selection.skipped_min_frames",
                group=group_hash,
                total=total,
                keep_percentile=fs_config.keep_percentile,
                discard=pct_details["discard"],
                keep=pct_details["keep"],
                min_frames=fs_config.min_frames,
                action="all_frames_stacked",
            )
        elif fs_config.enabled and pct_details["discard"] == 0:
            log.info(
                "selection.no_discard",
                group=group_hash,
                total=total,
                keep_percentile=fs_config.keep_percentile,
                discard=0,
                keep=total,
                reason="floor_rounding_zero",
            )
        elif fs_config.enabled:
            # Fallback: percentile angewendet — im detaillierten Pfad nicht nochmal
            pass
    else:
        # Use _apply_frame_selection for konsistentes Logging (selection.applied)
        after_percentile = _apply_frame_selection(registered, qualities, fs_config, group_hash, logger=log)
        percentile_rejected = total - len(after_percentile)

    # — Threshold-Rejection-Stufe (V1.5-8) —————
    threshold_rejected = 0
    final_registered = list(after_percentile)
    # Fuer Threshold-Entscheidung brauchen wir Qualities der nach-Perzentil verbliebenen Frames
    # Mappe Path -> FrameQuality fuer den Rest
    # Qualities sind moeglichst 1:1 zu registered (vor Selektion); nach Perzentil filtern wir
    # qualities auf die verbliebenen Pfade (via frame-Namen). Falls frame=None, fallback auf Reihenfolge.
    if rejection_enabled and after_percentile:
        # Build remaining qualities subset — Windows-robust: normalisiere auf as_posix + name
        kept_set = set(p.as_posix() for p in after_percentile)
        kept_set_str = set(str(p) for p in after_percentile)
        kept_name_set = set(p.name for p in after_percentile)
        # Filtere qualities: behalte nur solche, deren frame in after_percentile liegt.
        # Falls qualities laenger als registered (RE-F-Faelle), trotzdem korrekt.
        subset_qualities: List[FrameQuality] = []
        subset_index_map: dict[str, int] = {}  # frame string -> index in subset
        for q in qualities:
            if q.frame is not None:
                q_posix = Path(q.frame).as_posix()
                q_name = Path(q.frame).name
                if q_posix in kept_set or q_name in kept_name_set or q.frame in kept_set_str or q.frame in kept_name_set:
                    # Vermeide Duplikate (frame kann mehrfach vorkommen — nimm erste)
                    if q_posix not in subset_index_map and q_name not in subset_index_map and q.frame not in subset_index_map:
                        subset_qualities.append(q)
                        subset_index_map[q_posix] = len(subset_qualities) - 1
                        subset_index_map[q_name] = len(subset_qualities) - 1
                        subset_index_map[q.frame] = len(subset_qualities) - 1
            else:
                # frame=None — nicht zuordnen, spaeter per Position? Fuer Threshold betrachten wir nur Pfad-basierte.
                pass

        # Falls subset leer (alle frame=None), fallback: nimm qualities in Reihenfolge der after_percentile
        # (best effort — dann sind beide Listen gleich lang, Annahme index-korreliert)
        if not subset_qualities and len(qualities) >= len(after_percentile):
            # Heuristik: qualities und registered waren index-korreliert; nach Perzentil koennen wir nicht mehr
            # sicher zuordnen → verzichte auf Threshold-Filterung dieser Gruppe (sicher: keine Verwerfung)
            log.warning(
                "selection.rejection_no_quality_mapping",
                group=group_hash,
                action="no_threshold_rejection",
            )
        elif subset_qualities:
            try:
                rejected_qualities = reject_outlier_frames(
                    subset_qualities,
                    thresholds=rejection_thresholds or {},
                    elongation_unusable_enabled=rejection_elongation,
                )
            except Exception as e:
                log.warning("selection.rejection_failed", group=group_hash, error=str(e), action="no_threshold_rejection")
                rejected_qualities = [FrameQuality(frame=q.frame, snr=q.snr, fwhm_median=q.fwhm_median, star_count=q.star_count, outlier_excluded=False) for q in subset_qualities]

            # Bestimme welche Frames threshold-rejected sind
            rejected_frames_set = set()
            threshold_reasons: dict[str, str] = {}  # frame -> reason
            for rq in rejected_qualities:
                if rq.outlier_excluded:
                    key = rq.frame or ""
                    rejected_frames_set.add(key)
                    # Auch Name-Match fuer robustheit
                    if rq.frame:
                        # try both full path and name
                        pass
                    threshold_reasons[key] = rq.outlier_reject_reason or "threshold"

            # Filtere after_percentile nach rejected set — Windows-robust (as_posix + name)
            new_final: List[Path] = []
            for p in after_percentile:
                # Pruefe ob Path im rejected set (via posix, str, name)
                is_rejected = False
                p_posix = p.as_posix()
                p_str = str(p)
                p_name = p.name
                for rq in rejected_qualities:
                    if rq.outlier_excluded and rq.frame is not None:
                        rq_posix = Path(rq.frame).as_posix()
                        rq_name = Path(rq.frame).name
                        if rq_posix == p_posix or rq_posix == p_str or rq.frame == p_str or rq.frame == p_posix or rq_name == p_name or rq.frame == p_name:
                            is_rejected = True
                            break
                # Fallback: wenn rejected set via index (frame=None) nicht geht, ueberspringe
                if is_rejected:
                    continue
                new_final.append(p)

            threshold_rejected = len(after_percentile) - len(new_final)
            final_registered = new_final
            if threshold_rejected > 0:
                log.info(
                    "selection.threshold_rejected",
                    group=group_hash,
                    total_after_percentile=len(after_percentile),
                    threshold_rejected=threshold_rejected,
                    stacked=len(final_registered),
                    thresholds=rejection_thresholds,
                )
        else:
            # Kein subset, aber Threshold sollte nicht filtern
            pass

    # — Mandatory Gate (V1.8-8 DEF-006, stella a+c) ———————————————————
    # Verwirft auch bei rejection_enabled==False: outlier_excluded==True
    # (threshold-basiert, auch wenn Flag aus war) ODER corr_hp < Schwelle
    # (Default 0.05, analog V1.4-20 min_correlation 0.1). Mandatory für average,
    # aber hier generisch nach Threshold-Stufe angewandt — bei Default
    # 0.05 fallen nur katastrophale Frames (0.004-0.01) wie M92 Lauf 2.
    mandatory_rejected = 0
    mandatory_rejected_set: set[str] = set()
    mandatory_reason_by_frame: dict[str, str] = {}
    if mandatory_min_corr_hp is not None and final_registered:
        # Build subset für mandatory check (verbleibende nach Perzentil+Threshold)
        mand_kept_posix = set(p.as_posix() for p in final_registered)
        mand_kept_str = set(str(p) for p in final_registered)
        mand_kept_names = set(p.name for p in final_registered)
        mand_subset: List[FrameQuality] = []
        mand_index_map: dict[str, int] = {}
        for q in qualities:
            if q.frame is not None:
                q_posix = Path(q.frame).as_posix()
                q_name = Path(q.frame).name
                if q_posix in mand_kept_posix or q_name in mand_kept_names or q.frame in mand_kept_str or q.frame in mand_kept_names:
                    key = q_posix
                    if key not in mand_index_map and q_name not in mand_index_map and q.frame not in mand_index_map:
                        mand_subset.append(q)
                        mand_index_map[q_posix] = len(mand_subset) - 1
                        mand_index_map[q_name] = len(mand_subset) - 1
                        mand_index_map[q.frame] = len(mand_subset) - 1
        # DEF-011 fallback: deb vs reg Name-Mismatch -> positional mapping
        if not mand_subset and len(final_registered) == len(qualities):
            mand_subset = list(qualities)
            for q in qualities:
                if q.frame is not None:
                    mand_index_map[Path(q.frame).as_posix()] = 0
        elif not mand_subset and len(final_registered) <= len(qualities):
            # Allgemeiner Fall: nutze Positions-Mapping (M27 60s40: 48 reg vs 48 qual)
            # Filtere qualities positionell: index entspricht final_registered index
            # wenn keine Name-Treffer, aber Längen ähnlich -> nimm alle mit corr
            # und filtere später positionell
            mand_subset = list(qualities)
            for q in qualities:
                if q.frame is not None:
                    mand_index_map[Path(q.frame).as_posix()] = 0
        if mand_subset:
            try:
                mand_rejected_quals = reject_outlier_frames(
                    mand_subset,
                    thresholds=rejection_thresholds or {},
                    elongation_unusable_enabled=rejection_elongation,
                )
            except Exception as e:
                log.warning("selection.mandatory_rejection_failed", group=group_hash, error=str(e))
                mand_rejected_quals = mand_subset
            # Filtere final_registered nach outlier_excluded ODER corr_hp < Schwelle
            new_mand_final: List[Path] = []
            # Positional-Fallback Index fuer deb vs reg Mismatch (DEF-011)
            use_positional = len(final_registered) == len(mand_rejected_quals) and not any(
                Path(rq.frame).name == p.name for p in final_registered for rq in mand_rejected_quals if rq.frame
            ) if mand_rejected_quals else False
            for idx, p in enumerate(final_registered):
                p_posix = p.as_posix()
                p_str = str(p)
                p_name = p.name
                rq_match: FrameQuality | None = None
                for rq in mand_rejected_quals:
                    if rq.frame is None:
                        continue
                    rq_posix = Path(rq.frame).as_posix()
                    rq_name = Path(rq.frame).name
                    if rq_posix == p_posix or rq.frame == p_str or rq.frame == p_posix or rq_name == p_name or rq.frame == p_name:
                        rq_match = rq
                        break
                if rq_match is None and use_positional and 0 <= idx < len(mand_rejected_quals):
                    rq_match = mand_rejected_quals[idx]
                if rq_match is None:
                    # Kein Mapping — konservativ behalten
                    new_mand_final.append(p)
                    continue
                is_outlier = bool(getattr(rq_match, "outlier_excluded", False))
                corr = getattr(rq_match, "correlation", None)
                is_low_corr = False
                if corr is not None:
                    try:
                        is_low_corr = float(corr) < float(mandatory_min_corr_hp)
                    except Exception:
                        is_low_corr = False
                if is_outlier or is_low_corr:
                    mandatory_rejected += 1
                    if is_outlier and is_low_corr:
                        reason = f"{rq_match.outlier_reject_reason or 'outlier'},correlation<{mandatory_min_corr_hp}"
                    elif is_outlier:
                        reason = rq_match.outlier_reject_reason or "outlier_excluded"
                    else:
                        reason = f"correlation {corr} < {mandatory_min_corr_hp}"
                    mandatory_rejected_set.add(p_posix)
                    mandatory_rejected_set.add(p_str)
                    mandatory_rejected_set.add(p_name)
                    mandatory_reason_by_frame[p_posix] = reason
                    mandatory_reason_by_frame[p_str] = reason
                    mandatory_reason_by_frame[p_name] = reason
                    continue
                new_mand_final.append(p)
            if mandatory_rejected > 0:
                # Guard: nicht auf 0 filtern (sonst All Groups Failed wie im no_calib Test mit 3 synthetischen Random-Frames)
                # Min-Frames Guard ist für Mandatory nicht pauschal (Test test_reference_corr_none erwartet 2->1 trotz min 3)
                if len(new_mand_final) == 0:
                    log.warning(
                        "selection.mandatory_skipped_empty",
                        group=group_hash,
                        total_after_threshold=len(final_registered),
                        mandatory_rejected=mandatory_rejected,
                        would_stack=0,
                        action="all_frames_kept",
                    )
                else:
                    log.info(
                        "selection.mandatory_rejected",
                        group=group_hash,
                        total_after_threshold=len(final_registered),
                        mandatory_rejected=mandatory_rejected,
                        stacked=len(new_mand_final),
                        min_corr_hp=mandatory_min_corr_hp,
                    )
                    final_registered = new_mand_final

    stacked = len(final_registered)

    # — Report fuer agent-log / inspect / Trichter ————————————————
    # Score-Spanne aus pct_details (urspruengliche Scores, alle Frames)
    scores = pct_details.get("scores") or []
    score_min = float(min(scores)) if scores else None
    score_max = float(max(scores)) if scores else None
    import numpy as np
    score_median = float(np.median(scores)) if scores else None
    # Per-frame Entscheidungen: fuer jeden urspruenglichen registered Frame
    # Nutze pct_details.scored_registered fuer Score je Path (sortierte Reihenfolge)
    # und rejected info fuer Threshold
    # Build score lookup (bereits in pct_details)
    score_by_frame = pct_details.get("score_by_frame") or {}
    # Fuer Threshold: rejected_frames_set bereits bestimmt (erneut aufbauen fuer Report)
    # Rekonstruiere rejected set fuer Report (robust)
    threshold_rejected_set: set[str] = set()
    threshold_reason_by_frame: dict[str, str] = {}
    if rejection_enabled and after_percentile and 'rejected_qualities' in locals():
        for rq in rejected_qualities:
            if rq.outlier_excluded and rq.frame is not None:
                # Speichere posix, original und name — robust gegen Windows/Posix-Mix
                rq_posix = Path(rq.frame).as_posix()
                rq_name = Path(rq.frame).name
                threshold_rejected_set.add(rq_posix)
                threshold_rejected_set.add(rq.frame)
                threshold_rejected_set.add(rq_name)
                threshold_reason_by_frame[rq_posix] = rq.outlier_reject_reason or "threshold"
                threshold_reason_by_frame[rq.frame] = rq.outlier_reject_reason or "threshold"
                threshold_reason_by_frame[rq_name] = rq.outlier_reject_reason or "threshold"
    # V1.8-8: Mandatory Gate trägt ebenfalls zu threshold_rejected bei (stella a+c)
    # Für Report: mandatory_rejected_set bereits oben gefüllt; hier nur sicherstellen
    # dass threshold sets auch mandatory enthalten wenn nötig (für unified decision)
    # mandatory_reason_by_frame bereits befüllt

    # Bestimme percentile discarded set (aus pct_details) — bereits posix-normalisiert
    # Score lookup robust: auch score_by_name
    score_by_name = pct_details.get("score_by_name") or {}
    percentile_discarded_set_posix = pct_details.get("discarded_set") or set()
    percentile_discarded_names = pct_details.get("discarded_set_names") or set()
    # Fix: auch posix-Variante fuer discarded_set (falls alte Keys)
    # score_by_frame enthaelt beides

    frames_report: list[dict] = []
    # Fuer jeden original registered Pfad — Windows-robust (as_posix + name)
    for p in registered:
        key = p.as_posix()
        key_str = str(p)
        name = p.name
        # Score ermitteln — probiere posix, str, name, score_by_name
        s = score_by_frame.get(key)
        if s is None:
            s = score_by_frame.get(key_str)
        if s is None:
            s = score_by_name.get(name)
        if s is None:
            s = score_by_frame.get(name, 0.0)
        if s is None:
            s = 0.0
        # Entscheidung bestimmen (AC-FSEL-C1: keine Doppelt-Zaehlung)
        # Reihenfolge: percentile -> threshold -> mandatory (letztere als threshold_rejected für Trichter, aber reason differenziert)
        if key in percentile_discarded_set_posix or key_str in percentile_discarded_set_posix or name in percentile_discarded_names or key in percentile_discarded_names or key_str in percentile_discarded_names:
            decision = "percentile_rejected"
            reason = f"score {float(s):.4f} < cutoff {float(pct_details.get('cutoff_score') or 0):.4f} (rank, percentile {fs_config.keep_percentile})" if pct_details.get("cutoff_score") is not None else f"below percentile {fs_config.keep_percentile}"
        elif key in threshold_rejected_set or key_str in threshold_rejected_set or name in threshold_rejected_set:
            decision = "threshold_rejected"
            reason = threshold_reason_by_frame.get(key) or threshold_reason_by_frame.get(key_str) or threshold_reason_by_frame.get(name) or "threshold"
        elif key in mandatory_rejected_set or key_str in mandatory_rejected_set or name in mandatory_rejected_set:
            # V1.8-8 mandatory: als threshold_rejected zählen (Trichter), reason mit corr_hp/outlier
            decision = "threshold_rejected"
            reason = mandatory_reason_by_frame.get(key) or mandatory_reason_by_frame.get(key_str) or mandatory_reason_by_frame.get(name) or f"correlation<{mandatory_min_corr_hp}"
        else:
            # Nur kept wenn nicht in einer der Rejected-Mengen.
            decision = "kept"
            reason = None
        frames_report.append({
            "frame": key,
            "score": round(float(s), 4),
            "decision": decision,
            "reason": reason,
        })

    # V1.8-8: mandatory_rejected in threshold_rejected einrechnen (stella a+c kombiniert)
    total_threshold = threshold_rejected + mandatory_rejected
    report = {
        "total": total,
        "percentile_rejected": percentile_rejected,
        "threshold_rejected": total_threshold,
        "stacked": stacked,
        "keep_percentile": fs_config.keep_percentile if fs_config else 92,
        "enabled": bool(fs_config.enabled) if fs_config else False,
        "weights": dict(fs_config.weights) if fs_config and fs_config.weights else None,
        "min_frames": fs_config.min_frames if fs_config else 3,
        "skipped_min_frames": bool(pct_details.get("skipped_min_frames")),
        "score_min": round(score_min, 4) if score_min is not None else None,
        "score_max": round(score_max, 4) if score_max is not None else None,
        "score_median": round(score_median, 4) if score_median is not None else None,
        "cutoff_score": round(float(pct_details["cutoff_score"]), 4) if pct_details.get("cutoff_score") is not None else None,
        "frames": frames_report,
        # Fuer inspect: zusaetzliche Aggregation
        "rejection_enabled": bool(rejection_enabled),
        "rejection_thresholds": dict(rejection_thresholds) if rejection_thresholds else {},
        # V1.8-8: Mandatory Gate (DEF-006) transparent
        "mandatory_rejected": mandatory_rejected,
        "min_corr_hp": mandatory_min_corr_hp,
    }

    # Trichter-Logging (AC-FSEL-C2) — strukturiert je Gruppe (erweitert V1.8-8)
    log.info(
        "selection.funnel",
        group=group_hash,
        total=total,
        percentile_rejected=percentile_rejected,
        threshold_rejected=total_threshold,
        stacked=stacked,
        keep_percentile=report["keep_percentile"],
        enabled=report["enabled"],
        mandatory_rejected=mandatory_rejected,
        min_corr_hp=mandatory_min_corr_hp,
    )

    return final_registered, report


__all__ = [
    "_resolve_frame_selection_config",
    "_resolve_rejection_config",
    "_resolve_min_corr_hp_config",
    "_apply_frame_selection",
    "_percentile_selection_details",
    "_apply_selection_and_rejection",
    "_apply_mandatory_average_filter",
    "DEFAULT_MIN_CORR_HP",
]