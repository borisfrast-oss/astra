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
from ..core.preview import create_preview_jpg

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

        if len(group_stacks) < 2:
            logger.warning("merge.insufficient_stacks", count=len(group_stacks))
            return MergeResult(
                merged_path=None,
                group_stacks=group_stacks,
                group_metadata=group_metadata,
                merge_report={"error": "insufficient_stacks"},
            )

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

        if len(stacks) < 2:
            logger.warning("merge.insufficient_valid_stacks", count=len(stacks))
            return MergeResult(
                merged_path=None,
                group_stacks=group_stacks,
                group_metadata=group_metadata,
                merge_report={"error": "insufficient_valid_stacks"},
            )

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
        )

        # ── 6. Create preview JPG ───────────────────────────
        preview_path = self._create_preview(merged_path, safe_name, preview_config=preview_config)

        # ── 7. Build merge report ──────────────────────────
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
        )

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
    ) -> None:
        """Propagate FITS headers from reference group to merged output.

        Sets WCS keys, OBJECT/TELESCOP/INSTRUME/RA/DEC from reference,
        and MG*-keys documenting the merge.

        Args:
            merged_path: Path to the merged FITS to update.
            group_stacks: {group_hash: Path} for reference lookup.
            group_metadata: {group_hash: dict} for total_exposure sum.
            merge_config: Merge configuration for method/weight_by headers.
            ref_hash: Reference group hash.
            all_hashes: All group hashes in sorted order.
        """
        if ref_hash not in group_stacks or not group_stacks[ref_hash].exists():
            logger.warning("merge.header_propagation_no_ref", hash=ref_hash)
            return

        ref_path = group_stacks[ref_hash]
        try:
            with fits.open(ref_path) as src:
                with fits.open(merged_path, mode="update") as tgt:
                    # WCS keys from reference (incl. REG_ROT from V1.5-4)
                    wcs_keys = [
                        "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2",
                        "CDELT1", "CDELT2", "CTYPE1", "CTYPE2",
                        "CUNIT1", "CUNIT2",
                        "REG_ROT",
                    ]
                    for key in wcs_keys:
                        if key in src[0].header:
                            tgt[0].header[key] = src[0].header[key]

                    # OBJECT, TELESCOP, INSTRUME, RA, DEC from reference
                    for key in ["OBJECT", "TELESCOP", "INSTRUME", "RA", "DEC"]:
                        if key in src[0].header:
                            tgt[0].header[key] = src[0].header[key]

                    # Multi-group headers
                    total_exp = sum(
                        meta.get("total_exposure", 0)
                        for meta in group_metadata.values()
                    )
                    tgt[0].header["EXPTIME"] = float(total_exp)
                    tgt[0].header["GAIN"] = "MULTI"
                    tgt[0].header["FILTER"] = "MULTI"
                    tgt[0].header["MGCNTGRP"] = len(all_hashes)
                    tgt[0].header["MGREFGRP"] = ref_hash
                    tgt[0].header["MGMETHOD"] = merge_config.method
                    tgt[0].header["MGWTBY"] = merge_config.weight_by
                    tgt[0].header["MGVER"] = "1.0"
        except Exception as e:
            logger.warning("merge.header_propagation_failed", error=str(e))

    @staticmethod
    def _create_preview(
        merged_path: Path, safe_name: str,
        preview_config: Optional["PreviewExportConfig"] = None,
    ) -> Optional[Path]:
        """Create auto-stretched JPG preview from merged FITS.

        Args:
            merged_path: Path to the merged FITS.
            safe_name: Sanitised target name for output filename.
            preview_config: V1.8-2 Preview/Export-Pipeline Einstellungen.

        Returns:
            Path to preview JPG, or None on failure.
        """
        jpg_dir = merged_path.parent
        jpg_path = jpg_dir / f"{safe_name}_merged_preview.jpg"
        try:
            result = create_preview_jpg(
                merged_path, jpg_path,
                preview_config=preview_config,
            )
            if result:
                logger.info("merge.preview_created", path=str(jpg_path))
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
