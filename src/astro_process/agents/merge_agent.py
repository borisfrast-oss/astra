"""MergeAgent — Merge multiple group stacks into a single FITS output.

Phase 3 (T9–T10) of the Multi-Group Stacking feature.
Replaces the inline _merge_group_stacks() method in ProcessingAgent.

Usage:
    merge_agent = MergeAgent(working_dir, config)
    result = merge_agent.run(group_stacks, group_metadata, target_name)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from dataclasses import dataclass, field
import structlog
import numpy as np
from astropy.io import fits

from ..config.models import MergeConfig
from ..core.preview import create_preview, create_preview_jpg

if TYPE_CHECKING:
    from ..config.models import PreviewExportConfig


logger = structlog.get_logger(__name__)


@dataclass
class MergeResult:
    """Ergebnis des Merge-Agents.

    Attributes:
        merged_path: Pfad zum gemergten FITS (None bei Fehler).
        group_stacks: {group_hash: Path} — Eingabe-Stacks.
        group_metadata: {group_hash: dict} — Metadaten der Gruppen.
        merge_report: Vollständiger Merge-Report (Schema §5.3).
        preview_path: Pfad zum Preview-JPG (optional).
        agent_log: Pfad zum Agent-Log (optional).
    """
    merged_path: Optional[Path]
    group_stacks: dict[str, Path] = field(default_factory=dict)
    group_metadata: dict[str, dict] = field(default_factory=dict)
    merge_report: dict = field(default_factory=dict)
    preview_path: Optional[Path] = None
    agent_log: Optional[Path] = None


class MergeAgent:
    """Merge-Agent: Weighted Merge mehrerer Gruppen-Stacks.

    Lädt FITS-Dateien selbst von Pfaden — ProcessingAgent übergibt
    nur Pfade, keine ndarrays. Saubere Trennung der Verantwortlichkeiten.

    Ersetzt die inline _merge_group_stacks()-Methode in ProcessingAgent.
    """

    def __init__(self, working_dir: Path, config=None):
        """Initialize MergeAgent.

        Args:
            working_dir: Working directory (parent of merged/).
            config: AppConfig or object with multi_group.merge attributes.
                    If None or missing merge config, MergeConfig defaults are used.
        """
        self.working_dir = working_dir
        self.config = config
        self.merged_dir = working_dir / "merged"
        self.merged_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        group_stacks: dict[str, Path],
        group_metadata: dict[str, dict],
        target_name: str,
        merge_config: Optional[MergeConfig] = None,
        pcc_fallback_groups: Optional[list[str]] = None,
        cross_group_registrations: Optional[list[dict]] = None,
        skipped_groups: Optional[list[dict]] = None,
        reference_selection: Optional[dict] = None,
        preview_config: Optional["PreviewExportConfig"] = None,
        context=None,
    ) -> MergeResult:
        """Run merge on group stacks.

        Args:
            group_stacks: {group_hash: Path to PCC-corrected stack FITS}.
            group_metadata: {group_hash: dict with frame_count, exptime, gain,
                             filter, total_exposure, pcc_status}.
            target_name: Target name for output filenames.
            merge_config: Merge configuration (method, weight_by).
                          If None, reads from self.config or falls back to defaults.
            pcc_fallback_groups: List of group hashes that used PCC gray-world fallback.
            cross_group_registrations: Liste der Cross-Group-Registrations-Metriken
                          (CR-001 P3-B, AC-P3-2/3): pro Eintrag {group, reference,
                          shift_y, shift_x, correlation, status}. Korrelation ist
                          post-shift berechnet. Default None → Report-Sektion [].
                          Der `astra merge`-Sub-Command übergibt keine Daten.
            skipped_groups: Liste der vom Merge AUSGESCHLOSSENEN Gruppen
                          (CR-001 W3, AC-W3-1): pro Eintrag {group, reason,
                          corr_hp, min_correlation}. Default None → Report-
                          Sektion [].
            reference_selection: Dokumentation der deterministischen
                          Referenz-Gruppen-Wahl (CR-001 W14, AC-W14-2):
                          {method, group, signal_scores, fallback_reason?}.
                          Default None → Report-Feld {} (konsistent für
                          `astra merge`).
            preview_config: V1.8-2 Preview/Export-Pipeline Einstellungen.

        Returns:
            MergeResult with merged_path, merge_report, preview_path.

        Raises:
            ValueError: If shape mismatch between group stacks.
        """
        # ── Resolve config ──────────────────────────────────
        if merge_config is None:
            merge_config = self._resolve_merge_config()
        if pcc_fallback_groups is None:
            pcc_fallback_groups = []
        if cross_group_registrations is None:
            cross_group_registrations = []
        if skipped_groups is None:
            skipped_groups = []
        if reference_selection is None:
            reference_selection = {}

        # V1.7-1 FSM-C4: effektive Filter-Liste additiv loggen (nur wenn gesetzt, sonst byte-identisch zu v1.6)
        if merge_config.filters is not None:
            logger.info(
                "merge.start",
                stacks=len(group_stacks),
                method=merge_config.method,
                weight_by=merge_config.weight_by,
                filters=merge_config.filters,
            )
        else:
            logger.info(
                "merge.start",
                stacks=len(group_stacks),
                method=merge_config.method,
                weight_by=merge_config.weight_by,
            )

        if len(group_stacks) == 0:
            logger.warning("merge.insufficient_stacks", count=len(group_stacks))
            return MergeResult(
                merged_path=None,
                group_stacks=group_stacks,
                group_metadata=group_metadata,
                merge_report={"error": "insufficient_stacks"},
            )
        # P-04-Mini (V1.12-FU-3): Single-Stack Fallback laut loggen — 1 Kandidat nach Gate/Filter
        # Bei N>=2 Eingabe + skipped_groups (filter_typo / cross_group_gate) fällt Merge still
        # auf 1 Stack zurück. Statt still: Warning `merge.fell_back_to_single_group` + Report-Feld
        # `merge.fallback`. Die detaillierte Fallback-Erkennung (Integration_lost_pct) passiert
        # nach dem Laden, damit echte Valid-Stacks gezaehlt werden; hier nur der Eingabe-Pfad
        # fuer die Warnung single_stack_fallback komplementaer ergaenzen.
        if len(group_stacks) == 1:
            # V19-FIX-11 P0 Gate Duo-Band: single_stack_fallback — mit Warnung statt hart Skip wenn nur 1 Stack übrig (wie Single-Group)
            sole_hash = next(iter(group_stacks))
            # P-04: Wenn skipped_groups belegen dass N>=2 -> 1 Fallback vorliegt, nutze die
            # explizite P-04-Warnung (statt nur single_stack_fallback). Der eigentliche
            # `fell_back_to_single_group`-Hint mit integration_lost wird nach dem Laden
            # emittiert (dort steht valide Stack-Zahl + Metadaten fest).
            if skipped_groups:
                # total_exposure-basierte Hint-Vorstufe (best effort; finale Warnung nach Laden)
                remaining = [sole_hash]
                excluded = [s.get("group", "") for s in skipped_groups if s.get("group")]
                # reason heuristisch: filter_excluded -> filter_typo, sonst cross_group_gate
                _reasons = {s.get("reason", "") for s in skipped_groups}
                _reason = "filter_typo" if any("filter" in r for r in _reasons) else "cross_group_gate"
                total_all = sum(float(group_metadata.get(h, {}).get("total_exposure", 0) or 0) for h in set(remaining + excluded)) or None
                total_rem = float(group_metadata.get(sole_hash, {}).get("total_exposure", 0) or 0)
                lost_pct = round((1 - total_rem / total_all) * 100, 1) if total_all and total_all > 0 else None
                logger.warning(
                    "merge.fell_back_to_single_group",
                    excluded_group=excluded[0] if len(excluded) == 1 else ",".join(excluded) if excluded else "unknown",
                    remaining_groups=remaining,
                    integration_lost_pct=lost_pct,
                    reason=_reason,
                    from_count=len(remaining) + len(excluded),
                    to_count=1,
                    hint=f"merge fell back to single group, {excluded[0] if excluded else 'unknown'} excluded — check cross_group gate / filter_typo",
                )
            logger.warning("merge.single_stack_fallback", count=1, group=sole_hash, msg="Only one stack remains after quality gate — exporting single stack as merged with warning")
            # Fallthrough to load/merge path with 1 stack (copy instead of weighted average)

        # ── 1. Load stacks from paths ───────────────────────
        stacks: list[np.ndarray] = []
        weights: list[float] = []
        stack_hashes: list[str] = []

        for group_hash in sorted(group_stacks.keys()):
            stack_path = group_stacks[group_hash]
            if not stack_path or not stack_path.exists():
                logger.warning(
                    "merge.stack_not_found",
                    hash=group_hash,
                    path=str(stack_path),
                )
                continue

            try:
                data = self._load_fits(stack_path)
            except Exception as e:
                logger.warning("merge.stack_load_failed", hash=group_hash,
                               path=str(stack_path), error=str(e))
                continue
            stacks.append(data)

            meta = group_metadata.get(group_hash, {})
            w = self._compute_weight(meta, merge_config)
            weights.append(float(w))
            stack_hashes.append(group_hash)

        if len(stacks) == 0:
            logger.warning("merge.insufficient_valid_stacks", count=len(stacks))
            return MergeResult(
                merged_path=None,
                group_stacks=group_stacks,
                group_metadata=group_metadata,
                merge_report={"error": "insufficient_valid_stacks"},
            )
        # P-04-Mini: Fallback-Erkennung nach Laden (valid stacks = 1, aber Eingabe/skip belegt N>=2)
        # Beispiel M27: 2 Gruppen (4290s), eine via cross_group Gate excluded -> 2880s/4290s = 33% Verlust.
        # Emitte WARN `merge.fell_back_to_single_group` + Feld `merge.fallback` im Report.
        _fallback: dict | None = None
        if len(stacks) == 1:
            logger.warning("merge.single_stack_fallback_valid", count=1, stacks=stack_hashes, msg="Only one valid stack after loading — exporting as merged")
            # Echte Fallback-Heuristik: valid 1 + (Eingabe 2+ ODER skipped non-empty) => 2→1
            _input_cnt = len(group_stacks)
            _skipped_cnt = len(skipped_groups) if skipped_groups else 0
            _total_before = _input_cnt + sum(1 for s in (skipped_groups or []) if s.get("group") not in group_stacks)
            # Falls skipped Gruppen bereits in group_stacks fehlten, total_before faengt es
            # Alternativ: wenn valid 1 und skipped non-empty -> immer Fallback (filter/cross_group)
            _is_fallback = (_total_before >= 2) or (_skipped_cnt > 0) or (_input_cnt >= 2 and len(stack_hashes) == 1 and _input_cnt != len(stack_hashes))
            # Spezial: input 2 -> valid 1 via Ladefehler (stack load failure) -> _input_cnt>=2 a reicht
            if _input_cnt >= 2 and len(stack_hashes) == 1:
                _is_fallback = True
            if _is_fallback:
                # Excluded = Gruppen aus skipped_groups + those that failed to load
                _excluded = []
                for s in (skipped_groups or []):
                    g = s.get("group")
                    if g:
                        _excluded.append(g)
                for h in group_stacks:
                    if h not in stack_hashes and h not in _excluded:
                        _excluded.append(h)
                # Deduplicate preserve order
                seen = set()
                _excl_dedup = []
                for e in _excluded:
                    if e not in seen:
                        seen.add(e)
                        _excl_dedup.append(e)
                _excluded = _excl_dedup
                remaining = list(stack_hashes)
                # Reason heuristisch
                _reasons = {str(s.get("reason", "")) for s in (skipped_groups or [])}
                if any("filter" in r.lower() for r in _reasons):
                    _reason = "filter_typo"
                elif any("corr" in r.lower() or "cross" in r.lower() or "below" in r.lower() for r in _reasons):
                    _reason = "cross_group_gate"
                elif _excluded:
                    _reason = "cross_group_gate"
                else:
                    _reason = "unknown"
                # Integration lost pct
                try:
                    total_all = sum(float(group_metadata.get(h, {}).get("total_exposure", 0) or 0) for h in set(remaining + _excluded)) or None
                    # Fallback: if metadata missing (z.B. `astra merge` Standalone), nutze frame_count
                    if not total_all or total_all == 0:
                        total_all = sum(float(group_metadata.get(h, {}).get("frame_count", 0) or 0) for h in set(remaining + _excluded)) or None
                    total_rem = sum(float(group_metadata.get(h, {}).get("total_exposure", 0) or 0) for h in remaining) or sum(float(group_metadata.get(h, {}).get("frame_count", 0) or 0) for h in remaining) or 0
                    if total_all and total_all > 0:
                        lost_pct = round((1 - total_rem / total_all) * 100, 1)
                    else:
                        lost_pct = None
                except Exception:
                    lost_pct = None
                # Wenn noch nicht bereits via Eingabe-Pfad geloggt (skipped input 1), jetzt loggen
                # Vermeide Doppel-Log wenn Eingabe bereits 1+skipped und dort schon geloggt: nur wenn input>=2 oder noch nicht geloggt
                # Wir loggen hier immer als finale Instanz (nach Laden) — duplikatfrei via einmaliger Emission pro Run
                # Pruefe ob Eingabe-Pfad bereits fell_back geloggt hat: wenn group_stacks initial 1, ist dort geloggt; hier nicht erneut wenn _input_cnt==1 und bereits geloggt
                should_log = not (_input_cnt == 1 and _skipped_cnt > 0)  # bereits oben geloggt
                # Bei Lade-Fallback (input 2 -> valid 1) immer loggen
                if _input_cnt >= 2:
                    should_log = True
                if should_log:
                    logger.warning(
                        "merge.fell_back_to_single_group",
                        excluded_group=_excluded[0] if len(_excluded) == 1 else ",".join(_excluded) if _excluded else "unknown",
                        excluded_groups=_excluded,
                        remaining_groups=remaining,
                        integration_lost_pct=lost_pct,
                        reason=_reason,
                        from_count=len(remaining) + len(_excluded),
                        to_count=len(remaining),
                        hint=f"merge fell back to single group, {_excluded[0] if _excluded else 'unknown'} excluded — check cross_group gate / filter_typo",
                    )
                # Report-Feld fuer merge_report.json / agent-log.yaml
                _fallback = {
                    "from": len(remaining) + len(_excluded),
                    "to": len(remaining),
                    "excluded": _excluded[0] if len(_excluded) == 1 else _excluded,
                    "excluded_groups": _excluded,
                    "remaining_groups": remaining,
                    "reason": _reason,
                    "integration_lost_pct": lost_pct,
                }
                # Auch via multi_group Pfad wird merge.fallback im mg_metadata persistiert (archive.py)

        # ── 2. Validate shapes ──────────────────────────────
        shapes = [s.shape for s in stacks]
        if len(set(shapes)) > 1:
            raise ValueError(
                f"Shape mismatch between group stacks: {shapes}"
            )

        # ── 3. Merge ────────────────────────────────────────
        merged = self._merge(stacks, weights, merge_config.method)

        # ── 4. Clip negative pixels post-merge (AQ5/hal) ───
        merged = np.maximum(merged, 0)

        # ── 5. Save merged FITS with propagated headers ─────
        safe_name = target_name.replace(" ", "_").replace("(", "").replace(")", "")
        merged_path = self.merged_dir / f"{safe_name}_merged.fits"
        self._save_fits(merged, merged_path)

        # CR-001 W14: Use signal-selected reference group (not alphabetical first)
        ref_hash = reference_selection.get("group") if reference_selection else (stack_hashes[0] if stack_hashes else "")
        if not ref_hash and stack_hashes:
            ref_hash = stack_hashes[0]  # Fallback if reference_selection missing/empty
        self._propagate_headers(
            merged_path,
            group_stacks,
            group_metadata,
            merge_config,
            ref_hash,
            stack_hashes,
            context=context,
        )

        # ── 6. Create preview (format-aware, V1.12) ────────
        _fmt = "tiff"
        try:
            _fmt = getattr(self.config.preview, "format", "tiff") if self.config and getattr(self.config, "preview", None) else "tiff"
        except Exception:
            _fmt = "tiff"
        preview_path = self._create_preview(merged_path, safe_name, preview_config=preview_config, preview_format=_fmt)

        # ── 7. Build merge report ──────────────────────────
        # _fallback wurde oben (P-04) bei single-stack Fallback befuellt
        _fallback_for_report = locals().get("_fallback")
        merge_report = self._build_merge_report(
            merge_config,
            ref_hash,
            merged_path,
            merged,
            group_stacks,
            group_metadata,
            stack_hashes,
            weights,
            pcc_fallback_groups,
            cross_group_registrations,
            skipped_groups,
            reference_selection,
            fallback=_fallback_for_report,
        )
        # P-04: Sync _fallback in Report falls _build_merge_report ihn nicht gesetzt (z.B. None)
        if _fallback_for_report and "merge.fallback" not in merge_report:
            merge_report["merge.fallback"] = _fallback_for_report
            merge_report["fallback"] = _fallback_for_report

        # ── 8. Write merge_report.json ──────────────────────
        self._write_report(merge_report)

        logger.info(
            "merge.complete",
            output=str(merged_path),
            stacks=len(stacks),
            method=merge_config.method,
        )

        return MergeResult(
            merged_path=merged_path,
            group_stacks=group_stacks,
            group_metadata=group_metadata,
            merge_report=merge_report,
            preview_path=preview_path,
        )

    # ────────────────────────────────────────────────────────────
    # Private Helpers
    # ────────────────────────────────────────────────────────────

    def _resolve_merge_config(self) -> MergeConfig:
        """Resolve merge configuration from self.config or return defaults.

        Handles the case where config or multi_group section is None gracefully.
        """
        if self.config is not None:
            mg = getattr(self.config, "multi_group", None)
            if mg is not None:
                mc = getattr(mg, "merge", None)
                if mc is not None:
                    return mc
        return MergeConfig()

    @staticmethod
    def _load_fits(path: Path) -> np.ndarray:
        """Load FITS as float32 (H, W, C) or (H, W).

        Transposes from FITS convention (C, H, W) to internal (H, W, C).
        """
        with fits.open(path) as hdul:
            data = hdul[0].data.astype(np.float32)
            if data.ndim == 3:
                data = data.transpose(1, 2, 0)  # (C, H, W) → (H, W, C)
            return data

    @staticmethod
    def _save_fits(data: np.ndarray, path: Path) -> None:
        """Save float32 array as FITS.

        Transposes from internal (H, W, C) to FITS convention (C, H, W).
        """
        out = data.astype(np.float32)
        if out.ndim == 3:
            out = out.transpose(2, 0, 1)  # (H, W, C) → (C, H, W)
        hdu = fits.PrimaryHDU(out)
        if data.ndim == 3:
            hdu.header["CTYPE3"] = "RGB"
            hdu.header["CUNIT3"] = "channel"
        hdu.writeto(path, overwrite=True)

    @staticmethod
    def _compute_weight(meta: dict, merge_config: MergeConfig) -> float:
        """Compute weight for a group based on merge config.

        Args:
            meta: Group metadata dict (frame_count, total_exposure, …).
            merge_config: Merge configuration determining weight_by strategy.

        Returns:
            Float weight value.
        """
        if merge_config.weight_by == "total_exposure":
            return float(meta.get("total_exposure", meta.get("frame_count", 1)))
        # default: frame_count
        return float(meta.get("frame_count", 1))

    @staticmethod
    def _merge(
        stacks: list[np.ndarray],
        weights: list[float],
        method: str,
    ) -> np.ndarray:
        """Apply merge method to a list of stacks.

        Args:
            stacks: List of ndarrays (all same shape).
            weights: Weight per stack (for weighted_average).
            method: One of "weighted_average", "average", "median".

        Returns:
            Merged ndarray (float32, same shape as input stacks).
        """
        if method == "weighted_average":
            weights_np = np.array(weights, dtype=np.float64)
            total = weights_np.sum()
            if total <= 0:
                logger.warning("merge.zero_weight_sum",
                               msg="All weights are zero — using equal weights")
                weights_np = np.ones_like(weights_np) / len(weights_np)
            else:
                weights_np = weights_np / total
            merged = np.zeros_like(stacks[0], dtype=np.float64)
            for data, w in zip(stacks, weights_np):
                merged += data.astype(np.float64) * w
            return merged.astype(np.float32)

        if method == "average":
            return np.mean(np.stack(stacks, axis=0), axis=0).astype(np.float32)

        if method == "median":
            return np.median(np.stack(stacks, axis=0), axis=0).astype(np.float32)

        # Unknown method — fallback to weighted_average with warning
        logger.warning(
            "merge.unknown_method",
            method=method,
            fallback="weighted_average",
        )
        weights_np = np.array(weights, dtype=np.float64)
        weights_np = weights_np / weights_np.sum()
        merged = np.zeros_like(stacks[0], dtype=np.float64)
        for data, w in zip(stacks, weights_np):
            merged += data.astype(np.float64) * w
        return merged.astype(np.float32)

    @staticmethod
    def _propagate_headers(
        merged_path: Path,
        group_stacks: dict[str, Path],
        group_metadata: dict[str, dict],
        merge_config: MergeConfig,
        ref_hash: str,
        all_hashes: list[str],
        context=None,
    ) -> None:
        """V1.12-HEADER: Replace propagation with build_effective_header (S1-S5, S3 fallback).

        Uses reference group (signal-selected) + MG* + summierte EXPTIME;
        Fallback S3: wenn context is None (astra merge standalone) -> raw_cards aus ref_header via HEADER_ALIASES.

        Sets WCS keys, OBJECT/TELESCOP/INSTRUME/RA/DEC/XPIXSZ effective etc via SSOT header_utils.

        Args:
            merged_path: Path to the merged FITS to update.
            group_stacks: {group_hash: Path} for reference lookup.
            group_metadata: {group_hash: dict} for total_exposure sum.
            merge_config: Merge configuration for method/weight_by headers.
            ref_hash: Reference group hash.
            all_hashes: All group hashes in sorted order.
            context: ObservationContext for S4 group filtering; None -> use ref_header (S3)
        """
        if ref_hash not in group_stacks or not group_stacks[ref_hash].exists():
            logger.warning("merge.header_propagation_no_ref", hash=ref_hash)
            return

        ref_path = group_stacks[ref_hash]
        try:
            # Determine method/scale for merged inherits effective from ref (S1)
            # Infer from ref header DEBAYER/XBINNING/XPIXSZ after stacked annotation
            ref_hdr = None
            try:
                with fits.open(ref_path) as src:
                    ref_hdr = src[0].header.copy()
            except Exception:
                ref_hdr = None
            method = "superpixel"
            scale_window = 2.0
            drizzle_scale = 2.0
            if ref_hdr is not None:
                debayer = str(ref_hdr.get("DEBAYER", "")).lower()
                if debayer in ("malvar2004", "malvar", "bilinear"):
                    method = "malvar2004" if "malvar" in debayer else "bilinear"
                    scale_window = 1.0
                elif debayer == "drizzle":
                    method = "drizzle"
                    try:
                        drizzle_scale = float(ref_hdr.get("DRZSCALE", 2.0))
                    except Exception:
                        drizzle_scale = 2.0
                else:
                    # Fallback via XBINNING or XPIXSZ
                    try:
                        xbin = int(ref_hdr.get("XBINNING", 2))
                        if xbin == 1:
                            # Could be malvar or drizzle; check XPIXSZ ~1.45 for drizzle
                            xpix = float(ref_hdr.get("XPIXSZ", 5.8))
                            if abs(xpix - 1.45) < 0.2:
                                method = "drizzle"
                            else:
                                method = "malvar2004"
                                scale_window = 1.0
                        else:
                            method = "superpixel"
                    except Exception:
                        method = "superpixel"
            # Summed EXPTIME
            total_exp = sum(float(meta.get("total_exposure", 0) or 0) for meta in group_metadata.values())
            # Determine wcs from context or ref_hdr
            wcs = None
            if ref_hdr is not None:
                # Try to use RA/DEC/PIXELS from ref_hdr
                try:
                    ra = ref_hdr.get("RA")
                    dec = ref_hdr.get("DEC")
                    # Use CDELT to infer pixel_scale if available
                    cdelt = ref_hdr.get("CDELT2", 0)
                    if ra is not None and dec is not None:
                        ps = abs(float(cdelt)) * 3600.0 if cdelt else 0.0
                        if ps > 0:
                            wcs = {"ra": float(ra), "dec": float(dec), "pixel_scale_arcsec": float(ps)}
                        else:
                            # Fallback compute via XPIXSZ/FOCALLEN
                            try:
                                xpix = float(ref_hdr.get("XPIXSZ", 2.9))
                                focal = float(ref_hdr.get("FOCALLEN", 150.0))
                                if focal > 0:
                                    ps2 = 206.265 * xpix / focal
                                    wcs = {"ra": float(ra), "dec": float(dec), "pixel_scale_arcsec": float(ps2)}
                            except Exception:
                                wcs = {"ra": float(ra), "dec": float(dec), "pixel_scale_arcsec": 0.0}
                except Exception:
                    wcs = None
            # Build effective header via SSOT (S1-S5)
            from ..core.header_utils import annotate_fits, build_effective_header
            # Determine merged NAXIS for S5 CRPIX
            naxis = None
            try:
                with fits.open(merged_path) as mhdul:
                    n1 = mhdul[0].header.get("NAXIS1")
                    n2 = mhdul[0].header.get("NAXIS2")
                    if n1 and n2:
                        naxis = (int(n1), int(n2))
                    elif mhdul[0].data is not None:
                        d = mhdul[0].data
                        if d.ndim == 3:
                            naxis = (d.shape[2], d.shape[1]) if d.shape[0] == 3 else (d.shape[-1], d.shape[-2])
                        else:
                            naxis = (d.shape[1], d.shape[0])
            except Exception:
                naxis = None
            # Build header: context if available, else ref_header fallback (S3)
            if context is not None:
                # Try group-filtered context shim for S4
                eff_ctx = context
                if ref_hash:
                    try:
                        from ..models.core import compute_group_hash as _cgh
                        from types import SimpleNamespace
                        from ..models.core import FrameSet as _FS, FrameType as _FT
                        lights = context.get_lights()  # type: ignore
                        if lights and hasattr(lights, "group_by_params"):
                            gmap = lights.group_by_params()
                            for gk, fs in gmap.items():
                                try:
                                    gh = _cgh(float(gk[0]), int(gk[1]), str(gk[2]))
                                except Exception:
                                    continue
                                if gh == ref_hash and fs.frames:
                                    filtered_fs = _FS(frame_type=_FT.LIGHT, frames=list(fs.frames))
                                    eff_ctx = SimpleNamespace(get_lights=lambda fs=filtered_fs: fs, target=getattr(context, "target", None), frames={_FT.LIGHT: filtered_fs})
                                    break
                    except Exception:
                        eff_ctx = context
                hdr = build_effective_header(eff_ctx, method=method, scale_window=scale_window, drizzle_scale=drizzle_scale, wcs=wcs, total_exposure=total_exp, naxis=naxis)
            else:
                # Fallback S3: context is None (astra merge standalone) -> raw_cards from ref_header via HEADER_ALIASES
                hdr = build_effective_header(None, method=method, scale_window=scale_window, drizzle_scale=drizzle_scale, wcs=wcs, total_exposure=total_exp, ref_header=ref_hdr, naxis=naxis)
            # Fallback copy WCS keys from ref_hdr if build didn't produce them (e.g., test with only CRVAL but no RA/FOCALLEN)
            if ref_hdr is not None:
                for _k in ["CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2", "CDELT1", "CDELT2", "CTYPE1", "CTYPE2", "CUNIT1", "CUNIT2", "REG_ROT"]:
                    if _k in ref_hdr and _k not in hdr:
                        try:
                            hdr[_k] = ref_hdr[_k]
                        except Exception:
                            pass
                # Also copy OBJECT etc if missing
                for _k in ["OBJECT", "TELESCOP", "INSTRUME", "RA", "DEC"]:
                    if _k in ref_hdr and _k not in hdr:
                        try:
                            hdr[_k] = ref_hdr[_k]
                        except Exception:
                            pass
            # Add MG* + HISTORY kumuliert (OQ-3)
            hdr["MGCNTGRP"] = len(all_hashes)
            hdr["MGREFGRP"] = ref_hash
            hdr["MGMETHOD"] = merge_config.method
            hdr["MGWTBY"] = merge_config.weight_by
            hdr["MGVER"] = "1.0"
            hdr["MERGED"] = True
            try:
                hdr.add_history(f"Merged {len(all_hashes)} groups via {merge_config.method}")
            except Exception:
                pass
            # Ensure MULTI for heterogeneous GAIN/FILTER (merge spec: MULTI when heterogen, else single)
            # Determine if heterogen
            try:
                gains = set(str(m.get("gain")) for m in group_metadata.values() if m.get("gain") is not None)
                filters = set(str(m.get("filter")) for m in group_metadata.values() if m.get("filter") not in (None, "none", ""))
                if len(gains) > 1 or len(filters) > 1:
                    hdr["GAIN"] = "MULTI"
                    hdr["FILTER"] = "MULTI"
                else:
                    # Keep single value if homogeneous (preserve from ref)
                    if "GAIN" not in hdr or hdr["GAIN"] in (None, ""):
                        # Fallback single
                        single_gain = next(iter(gains)) if gains else None
                        if single_gain:
                            hdr["GAIN"] = single_gain
                    if "FILTER" not in hdr or hdr["FILTER"] in (None, ""):
                        single_f = next(iter(filters)) if filters else None
                        if single_f:
                            hdr["FILTER"] = single_f
            except Exception:
                hdr["GAIN"] = "MULTI"
                hdr["FILTER"] = "MULTI"
            annotate_fits(merged_path, hdr)
        except Exception as e:
            logger.warning("merge.header_propagation_failed", error=str(e))

    @staticmethod
    def _create_preview(
        merged_path: Path, safe_name: str,
        preview_config: Optional["PreviewExportConfig"] = None,
         preview_format: str = "tiff",
    ) -> Optional[Path]:
        """Create auto-stretched preview from merged FITS — format-aware.

        V1.12-PREVIEW-FORMAT: TIFF 16-bit Default / JPG Fallback.

        Args:
            merged_path: Path to the merged FITS.
            safe_name: Sanitised target name for output filename.
            preview_config: V1.8-2 Preview/Export-Pipeline Einstellungen.
            preview_format: "tiff" (Default) or "jpg".

        Returns:
            Path to preview, or None on failure.
        """
        fmt = str(preview_format).strip().lower() if isinstance(preview_format, str) else "tiff"
        if fmt not in ("tiff", "jpg"):
            fmt = "tiff"
        ext = ".tiff" if fmt == "tiff" else ".jpg"
        preview_dir = merged_path.parent
        preview_path = preview_dir / f"{safe_name}_merged_preview{ext}"
        try:
            result = create_preview(
                merged_path, preview_path, format=fmt,
                preview_config=preview_config,
            )
            if result:
                logger.info("merge.preview_created", path=str(preview_path), format=fmt)
            return result
        except Exception as e:
            logger.warning("merge.preview_failed", error=str(e))
            return None

    @staticmethod
    def _build_merge_report(
        merge_config: MergeConfig,
        ref_hash: str,
        merged_path: Path,
        merged: np.ndarray,
        group_stacks: dict[str, Path],
        group_metadata: dict[str, dict],
        stack_hashes: list[str],
        weights: list[float],
        pcc_fallback_groups: list[str],
        cross_group_registrations: Optional[list[dict]] = None,
        skipped_groups: Optional[list[dict]] = None,
        reference_selection: Optional[dict] = None,
        fallback: Optional[dict] = None,
    ) -> dict:
        """Build merge report dict conforming to architecture schema §5.3.

        Args:
            merge_config: Merge configuration.
            ref_hash: Reference group hash.
            merged_path: Output FITS path.
            merged: Merged data array for stats.
            group_stacks: {group_hash: Path} for input paths.
            group_metadata: {group_hash: dict} for input metadata.
            stack_hashes: Ordered list of group hashes used in merge.
            weights: Corresponding weight values.
            pcc_fallback_groups: Groups that used PCC fallback.
            cross_group_registrations: Cross-group registration metrics
                (CR-001 P3-B, AC-P3-2/3): [{group, reference, shift_y,
                shift_x, correlation, corr_roh, corr_hp, status}].
                correlation ist rückwärtskompatibel = corr_roh; corr_hp
                ist die QC-Hauptmetrik (Hochpass sigma=30, W2).
                Default None → Sektion [] (konsistent für `astra merge`).
            skipped_groups: Vom Merge ausgeschlossene Gruppen (CR-001 W3,
                AC-W3-1): [{group, reason: "below_min_correlation",
                corr_hp, min_correlation}]. Default None → Sektion [].
            reference_selection: Deterministische Referenz-Gruppen-Wahl
                (CR-001 W14, AC-W14-2): {method: "signal"|"frame_count"|
                "user", group, signal_scores, fallback_reason?}.
                Default None → Feld {}.

        Returns:
            Merge report dictionary.
        """
        if cross_group_registrations is None:
            cross_group_registrations = []
        if skipped_groups is None:
            skipped_groups = []
        if reference_selection is None:
            reference_selection = {}

        report: dict = {
            "method": merge_config.method,
            "weight_by": merge_config.weight_by,
            "reference_group": ref_hash,
            # CR-001 W14 (AC-W14-2): Referenz-Wahl deterministisch + dokumentiert
            "reference_selection": reference_selection,
            "input_stacks": [],
            "output": {
                "path": str(merged_path),
                "shape": list(merged.shape),
                "stats": {
                    "min": float(merged.min()),
                    "max": float(merged.max()),
                    "mean": float(merged.mean()),
                    "median": float(np.median(merged)),
                },
            },
            "pcc_fallback_groups": pcc_fallback_groups,
            # CR-001 P3-B (AC-P3-2): Cross-Group-Registrations-Metriken
            # (Schema §5.3-Erweiterung — Doku-Update durch paige nach QG-P3)
            "cross_group_registrations": cross_group_registrations,
            # CR-001 W3 (AC-W3-1): vom Merge ausgeschlossene Gruppen
            "skipped_groups": skipped_groups,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        }
        # V1.7-1 FSM-C2/C4: effektive Filter-Liste additiv (nur wenn gesetzt, sonst byte-identisch AC-FSM-B5)
        if merge_config.filters is not None:
            report["filters"] = list(merge_config.filters)

        for i, gh in enumerate(stack_hashes):
            meta = group_metadata.get(gh, {})
            report["input_stacks"].append({
                "group": gh,
                "path": str(group_stacks.get(gh, "")),
                "metadata": {
                    "frame_count": meta.get("frame_count"),
                    "exptime": meta.get("exptime"),
                    "gain": meta.get("gain"),
                    "filter": meta.get("filter"),
                    "total_exposure": meta.get("total_exposure"),
                    # T3: Per-Group-Dark-Quelle
                    # (local|library_exact|library_nearest|none|unknown)
                    "dark_source": meta.get("dark_source", "unknown"),
                },
                "weight": weights[i] if i < len(weights) else 1.0,
                "pcc_status": meta.get("pcc_status", "unknown"),
            })

        # QF-B (AC-QF-B2): `quality`-Block additiv (per-Group-Zusammenfassung,
        # Median-FWHM/Median-SNR/Outlier-Rate). Bestehende Report-Felder
        # bleiben unveraendert. Gruppen ohne Qualitaetsdaten (z.B. `astra
        # merge`-Standalone mit Header-only-Metadaten) erzeugen schlicht
        # keine Eintraege.
        # QF-01 (Sprint-2-Close): Per-Frame-Qualitaet (frame + snr +
        # fwhm_median + star_count + correlation + outlier, QF-A-Schema)
        # wird additiv in den quality-Block je Gruppe aufgenommen —
        # Legacy-Gruppen ohne frame_quality bleiben unveraendert.
        quality_block: dict = {}
        for gh in stack_hashes:
            meta = group_metadata.get(gh, {})
            entry: dict = {}
            q = meta.get("quality")
            if isinstance(q, dict) and q:
                entry.update(q)
            fq = meta.get("frame_quality")
            if isinstance(fq, list) and fq:
                entry["frame_quality"] = fq
            if entry:
                quality_block[gh] = entry
        report["quality"] = quality_block

        # GR-E (AC-GR-E1, AC-GR-D2): `gradient_removal`-Block additiv
        # (per-Group: applied + Modell-Parameter — degree, grid, n_samples,
        # n_rejected, n_iterations, residual_mad, residual_max,
        # channel_scales, coefficients). Nur Gruppen mit GR-Report (GR-Attempt
        # bei enabled) erzeugen Eintraege — Legacy-Reports unveraendert.
        gr_block: dict = {}
        for gh in stack_hashes:
            meta = group_metadata.get(gh, {})
            gr = meta.get("gradient_removal")
            if isinstance(gr, dict) and gr:
                gr_block[gh] = gr
        report["gradient_removal"] = gr_block

        # P-04-Mini (V1.12-FU-3): Merge Fallback — Single-Stack nach Gate/Filter
        # Persistiert als `merge.fallback` + `fallback` (grep `merge\.fallback`).
        # Beispiel M27: 2 Gruppen (4290s) -> 1 (2880s) = 33% Verlust durch cross_group_gate.
        if fallback:
            report["merge.fallback"] = dict(fallback)
            report["fallback"] = dict(fallback)

        return report

    @staticmethod
    def _write_report(report: dict) -> None:
        """Write merge_report.json to the merged directory.

        Args:
            report: Merge report dictionary.
        """
        if not report:
            return

        # Infer merged dir from output path in report
        output_path_str = report.get("output", {}).get("path", "")
        if output_path_str:
            report_path = Path(output_path_str).parent / "merge_report.json"
        else:
            logger.warning("merge.report_no_output_path")
            return

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info("merge.report_written", path=str(report_path))
        except Exception as e:
            logger.warning("merge.report_failed", error=str(e))
