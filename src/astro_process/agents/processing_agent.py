"""Processing Agent - Registration, stacking, PCC, SCNR, export (Python, 3D RGB, Multi-Group)."""

from pathlib import Path
from typing import Optional, List, TYPE_CHECKING
from dataclasses import dataclass, field
import structlog
import numpy as np
from astropy.io import fits

from ..models.core import ObservationContext, GroupInfo
from ..config.models import PipelinePreset, MultiGroupConfig, PipelineStep

if TYPE_CHECKING:
    from .merge_agent import MergeAgent
from ..core.pcc import get_pcc_fallback, photometric_color_calibration, scnr
from ..core.plugins import Plugin, PluginContext, PluginResult, resolve_step
from ..core.gradient_removal import background_extraction
from ..core.quality import FrameQuality
from ..core.registration import RegistrationResult
from .multi_group_agent import (
    MultiGroupProcessor,
    apply_cross_group_skip_filter,
    apply_pcc_per_group,
    build_reference_selection,
    cleanup_group_dirs,
    copy_wcs_headers,
    register_to_reference_stack,
    select_reference_group,
)

logger = structlog.get_logger(__name__)

_RUN_HANDLED_STEPS = frozenset({
    "register_frames",
    "stack_frames",
    "background_extraction",
    "gradient_removal",
    "photometric_color_calibration",
    "natural_color_processing",
    "scnr",
    "green_removal",
    "stretch",
    "gentle_stretch",
    "star_preserving_stretch",
    "export",
})

_EXTERNALLY_HANDLED_STEPS = frozenset({
    "create_master_dark",
    "calibrate_lights",
})


@dataclass
class ProcessingResult:
    registered_frames: List[Path] = field(default_factory=list)
    stacked: Optional[Path] = None
    exports: List[Path] = field(default_factory=list)
    multi_group_metadata: Optional[dict] = None
    frame_qualities: List[dict] = field(default_factory=list)
    stack_quality: Optional[dict] = None
    gradient_removal: Optional[dict] = None
    registration_metrics: Optional[dict] = None
    pcc_status: Optional[str] = None
    preview_export: Optional[dict] = None
    stretched_fits: Optional[dict] = None


class ProcessingAgent:
    """Python processing pipeline for 3D RGB data: registration, stacking, export."""

    def __init__(self, working_dir: Path, config=None):
        self.working_dir = working_dir
        self.config = config
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.registered_dir = working_dir / "03_registered"
        self.stacked_dir = working_dir / "04_stacked"
        self._last_frame_qualities: List[FrameQuality] = []
        self._last_frame_rejected: int = 0
        self._last_registration_metrics: dict = {}
        self.pixel_scale_override: float | None = None

    def _ensure_phase_dirs(self) -> None:
        self.registered_dir.mkdir(parents=True, exist_ok=True)
        self.stacked_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _pipeline_has_plugin_steps(pipeline: PipelinePreset) -> bool:
        for step in pipeline.steps:
            if step.name in _RUN_HANDLED_STEPS:
                continue
            if step.name in _EXTERNALLY_HANDLED_STEPS:
                continue
            return True
        return False

    def _run_plugin_steps(
        self, pipeline: PipelinePreset, context: ObservationContext
    ) -> list[PluginResult]:
        results: list[PluginResult] = []
        for step in pipeline.steps:
            if step.name in _RUN_HANDLED_STEPS:
                continue
            if step.name in _EXTERNALLY_HANDLED_STEPS:
                continue
            plugin = resolve_step(step.name)
            if plugin is None:
                logger.warning(
                    "pipeline.step_unhandled",
                    step=step.name,
                    msg="No handler for this preset step — verify the pipeline preset",
                )
                continue
            result = self._run_plugin(plugin, step, pipeline, context)
            if result is not None:
                results.append(result)
        return results

    def _run_plugin(
        self,
        plugin: Plugin,
        step: PipelineStep,
        pipeline: PipelinePreset,
        context: ObservationContext,
    ) -> PluginResult | None:
        plugin_context = PluginContext(
            working_dir=self.working_dir,
            output_dir=self.working_dir,
            processing_params=pipeline.processing_params,
            target_name=context.target.name if context.target else "",
            step_params=step.params,
        )
        try:
            result = plugin.run(plugin_context)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "pipeline.plugin_failed",
                plugin=plugin.name,
                step=step.name,
                error=str(e),
                msg="Plugin raised — step skipped (E1)",
            )
            return None
        if not result.ok:
            logger.warning(
                "pipeline.plugin_failed",
                plugin=plugin.name,
                step=step.name,
                ok=False,
                log_fields=result.log_fields,
                msg="Plugin reported failure — step skipped (E1)",
            )
            return None
        logger.info(
            "pipeline.plugin_complete",
            plugin=plugin.name,
            step=step.name,
            artifact=str(result.artifact) if result.artifact else None,
            log_fields=result.log_fields,
        )
        return result

    def _load_frame(self, path: Path) -> np.ndarray:
        with fits.open(path) as hdul:
            data = hdul[0].data.astype(np.float32)
            if data.ndim == 3:
                data = data.transpose(1, 2, 0)
            return data

    def _save_frame(self, data: np.ndarray, path: Path) -> None:
        out = data.astype(np.float32)
        if out.ndim == 3:
            out = out.transpose(2, 0, 1)
        hdu = fits.PrimaryHDU(out)
        if data.ndim == 3:
            hdu.header["CTYPE3"] = "RGB"
            hdu.header["CUNIT3"] = "channel"
        path.parent.mkdir(parents=True, exist_ok=True)
        hdu.writeto(path, overwrite=True)

    def _background_extraction(self, stacked: Optional[Path], params: dict) -> Optional[dict]:
        return background_extraction(
            stacked, params, load_frame=self._load_frame, save_frame=self._save_frame, logger=logger,
        )

    def _get_pcc_fallback(self) -> str:
        return get_pcc_fallback(self.config)

    def _photometric_color_calibration(self, stacked: Optional[Path], params: dict,
                                         ra: Optional[float] = None, dec: Optional[float] = None,
                                         pixel_scale_arcsec: float = 0.0) -> Optional[str]:
        return photometric_color_calibration(
            stacked, params, load_frame=self._load_frame, save_frame=self._save_frame,
            config=self.config, logger=logger, ra=ra, dec=dec, pixel_scale_arcsec=pixel_scale_arcsec,
        )

    def _scnr(self, stacked: Optional[Path], params: dict):
        scnr(stacked, params, load_frame=self._load_frame, save_frame=self._save_frame, logger=logger)

    def process_multi_group(
        self, context: ObservationContext,
        calibration_result, debayer_result,
        pipeline: PipelinePreset,
        multi_group_config: MultiGroupConfig,
        merge_agent: Optional['MergeAgent'] = None,
        target_name: str = "",
    ) -> ProcessingResult:
        processor = MultiGroupProcessor(
            self.working_dir, self.config,
            load_frame=self._load_frame,
            save_frame=self._save_frame,
            run_plugin_steps=self._run_plugin_steps,
            processing_result_class=ProcessingResult,
            select_reference_group=self._select_reference_group,
            register_to_reference_stack=self._register_to_reference_stack,
            apply_pcc_per_group=self._apply_pcc_per_group,
            has_plugin_steps=ProcessingAgent._pipeline_has_plugin_steps,
            logger=logger,
        )
        result = processor.process_multi_group(
            context, calibration_result, debayer_result,
            pipeline, multi_group_config,
            merge_agent=merge_agent, target_name=target_name,
        )
        self._last_frame_qualities = processor.last_frame_qualities
        self._last_frame_rejected = processor.last_frame_rejected
        self._last_registration_metrics = processor.last_registration_metrics
        if result.multi_group_metadata and result.multi_group_metadata.get("groups"):
            statuses = [m.get("pcc_status", "unknown") for m in result.multi_group_metadata["groups"].values()]
            unique = list(dict.fromkeys(statuses))
            if unique == [None] and getattr(processor, "last_merged_pcc_status", None) is not None:
                result.pcc_status = processor.last_merged_pcc_status
            else:
                result.pcc_status = unique[0] if len(unique) == 1 else "mixed"
        elif getattr(processor, "last_merged_pcc_status", None) is not None:
            result.pcc_status = processor.last_merged_pcc_status
        return result

    @staticmethod
    def _select_reference_group(
        groups: dict[str, GroupInfo],
        strategy: str = "largest",
        group_stacks: Optional[dict[str, Path]] = None,
        registration_metrics: Optional[dict[str, dict]] = None,
    ) -> str:
        return select_reference_group(groups, strategy, group_stacks, registration_metrics, logger=logger)

    def _build_reference_selection(
        self, groups: dict[str, GroupInfo], strategy: str, ref_hash: str,
        group_stacks: dict[str, Path], registration_metrics: Optional[dict[str, dict]] = None,
    ) -> dict:
        return build_reference_selection(groups, strategy, ref_hash, group_stacks, registration_metrics=registration_metrics, logger=logger)

    @staticmethod
    def _apply_cross_group_skip_filter(
        aligned_stacks: dict[str, Path], cross_group_registrations: list[dict], ref_hash: str,
        min_correlation: float, group_metadata: Optional[dict] = None, preview_paths: Optional[dict] = None,
        working_dir: Optional[Path] = None, group_avg_rotation: float = 0.0,
    ) -> tuple[dict[str, Path], list[dict]]:
        return apply_cross_group_skip_filter(
            aligned_stacks, cross_group_registrations, ref_hash, min_correlation,
            group_metadata=group_metadata, preview_paths=preview_paths, working_dir=working_dir,
            group_avg_rotation=group_avg_rotation, logger=logger,
        )

    def _register_to_reference_stack(
        self, stack_path: Path, ref_stack_path: Path, filter_name: str, output_dir: Path,
        params: Optional[dict] = None, eq: Optional[bool] = None,
    ) -> RegistrationResult:
        return register_to_reference_stack(
            stack_path, ref_stack_path, filter_name, output_dir,
            load_frame=self._load_frame, save_frame=self._save_frame, logger=logger, params=params, eq=eq,
        )

    @staticmethod
    def _copy_wcs_headers(source_path: Path, target_path: Path, rotation_deg: float = 0.0) -> None:
        copy_wcs_headers(source_path, target_path, rotation_deg=rotation_deg, logger=logger)

    def _apply_pcc_per_group(
        self, stack_path: Path, context: ObservationContext, multi_group_config: MultiGroupConfig,
        group_dir: Path, pixel_scale_arcsec: float = 0.0, ra: Optional[float] = None,
        dec: Optional[float] = None, group_metadata: Optional[dict] = None,
    ) -> tuple[Path, str]:
        return apply_pcc_per_group(
            stack_path, context, multi_group_config, group_dir,
            photometric_color_calibration_fn=self._photometric_color_calibration,
            logger=logger, pixel_scale_arcsec=pixel_scale_arcsec, ra=ra, dec=dec, group_metadata=group_metadata,
        )

    def _cleanup_group_dirs(self, groups: dict[str, GroupInfo], target_name: str) -> None:
        cleanup_group_dirs(groups, target_name, logger=logger)


def create_processing_agent(working_dir: Path, config=None) -> ProcessingAgent:
    return ProcessingAgent(working_dir, config)
