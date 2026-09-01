"""Gradient Removal (GR-A) — polynomial background modelling, Clean-Room.

Folgt dem *Funktionsprinzip* von Siril ``AutoGradientRemoval.py``
(Sampling + Sigma-Clipping + 2D-Polynom-Fit + Subtraktion) als eigene
numpy/scipy-Implementierung — keine Code-Uebernahme (Lizenz-/Copyright-
sauber, Clean-Room-Annahme 1).

Design-Entscheidungen (v12-gradient-removal.md, OQ-GR-1..6, alle von
stella/owen bestaetigt):

- **Post-Stack-Anwendung** (OQ-GR-6) — das Modul arbeitet auf einem
  bereits gestackten Frame (oder einem beliebigen 2D-Bild).
- **Mono-Fit, kanalweise Subtraktion** (OQ-GR-2): Das Hintergrundmodell
  wird auf der Luminance (Kanal-Mittel) gefittet und pro Kanal ueber den
  Kanal-Median skaliert subtrahiert — erhaelt die Farbverhaeltnisse und
  vermeidet drei unabhaengige Fits (Duo-Band: R=Ha vs G+B=OIII).
- **Grad 2, Grid 16x16, 3.0·MAD** (OQ-GR-3; Default-Flip (16, 16) nach
  M13-Real-Run-Validierung AC-GR-C4, s2-b4-m13-grid-validierung) als
  konservative Defaults.
- **Subtraktion, keine Division** (OQ-GR-4); Ergebnis wird auf 0
  geclippt (Konvention wie ``_apply_calibration``: ``np.maximum(x, 0)``).
- **Deterministisch** (kein RNG; Annahme 2) — gleiche Eingabe ergibt
  gleiches Modell und gleiches Ergebnis.

Algorithmus (iterative Rejection — AC-GR-A2/A5/A6):

1. **Sampling:** Das Bild wird in ein ``grid`` aus Zellen zerlegt; pro
   Zelle liefert der Median einen robusten Hintergrundwert (Sterne sind
   lokal wenige Pixel und heben den Zellen-Median kaum).
2. **Initiale Rejection:** Zellen deutlich heller als das globale
   Zellen-Median + ``k*sigma`` (``sigma = 1.4826*MAD``) — Sterne, helle
   Objektkerne — fliegen vor dem ersten Fit heraus.
3. **Fit:** 2D-Polynom (``degree``) per Least-Squares auf den
   verbleibenden Zellen -> glattes Hintergrundmodell.
4. **Iterative Rejection:** Residuen (Zellenwert - Modell). Zellen mit
   |Residuum| > ``k*sigma_resid`` werden **beidseitig** gegen das Modell
   verworfen, dann wird neu gefittet (max. ``max_iter`` Runden). Eine
   grosse weiche Quelle (M31-artiger Galaxien-Halo, AC-GR-A5;
   Emissionsnebel, AC-GR-A6) erzeugt nach dem ersten Fit ein grosses
   positives Residuum ueber viele Zellen und wird damit aus dem Fit
   ausgeschlossen, statt das Grad-2-Modell zu verzerren. Der echte
   Gradient (glatt, global) bleibt erhalten, weil seine Zellen dem
   Modell folgen.
5. **Subtraktion:** Modell vom Bild abziehen, negative Werte auf 0
   clippen.

Fehlerbehandlung (AC-GR-A4, E1): Unterschreitet die Anzahl der nach der
Rejection verbleibenden Sample-Punkte ``min_samples`` (Default: Anzahl der
Polynom-Terme), wirft das Modul :class:`GradientRemovalError` — der
Aufrufer (Pipeline) ueberspringt den Schritt mit Warning statt mit einem
korrupten Modell weiterzulaufen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import structlog
from numpy.typing import NDArray

logger = structlog.get_logger(__name__)


class GradientRemovalError(ValueError):
    """Raised when gradient removal cannot produce a trustworthy model.

    Kept separate from ``ValueError`` so the pipeline can catch it and
    skip the step with a warning (AC-GR-A4, AC-GR-E2) instead of a
    generic error path.
    """


def _neighborhood_reject(
    values: NDArray[np.float64],
    keep: NDArray[np.bool_],
    rows: int,
    cols: int,
    sigma_clip: float,
) -> tuple[int, NDArray[np.bool_]]:
    """Drop cells that stand out against their immediate neighbourhood.

    Rebuilds the cell grid (values were sampled in row-major order) and
    rejects any kept cell whose value deviates more than
    ``sigma_clip * sigma`` from the median of its kept 3x3 neighbours
    (``sigma = 1.4826 * MAD`` of those neighbours). This is the
    AC-GR-A5/A6 guard: a large soft source (galaxy halo, emission
    region) leaves rim cells that are *locally* elevated against the
    background around them — a plain global/iterative residual rejection
    can miss them because the polynomial already absorbs them with small
    residuals. Returns ``(n_rejected, new_keep_flat)``.
    """
    value_grid = np.full((rows, cols), np.nan)
    keep_grid = np.zeros((rows, cols), dtype=bool)
    flat_idx = np.arange(values.size)
    grid_rs, grid_cs = np.divmod(flat_idx, cols)
    value_grid[grid_rs, grid_cs] = values
    keep_grid[grid_rs, grid_cs] = keep

    n_new = 0
    for r in range(rows):
        r0, r1 = max(0, r - 1), min(rows, r + 2)
        for c in range(cols):
            if not keep_grid[r, c]:
                continue
            c0, c1 = max(0, c - 1), min(cols, c + 2)
            local_keep = keep_grid[r0:r1, c0:c1].copy()
            lr, lc = r - r0, c - c0
            local_keep[lr, lc] = False
            neighbours = value_grid[r0:r1, c0:c1][local_keep]
            if neighbours.size < 2:
                continue
            local_median = float(np.median(neighbours))
            local_sigma = 1.4826 * float(np.median(np.abs(neighbours - local_median)))
            if local_sigma <= 1e-12:
                continue
            if abs(value_grid[r, c] - local_median) > sigma_clip * local_sigma:
                keep_grid[r, c] = False
                n_new += 1
    return n_new, keep_grid.ravel()


def _poly_terms(degree: int) -> list[tuple[int, int]]:
    """Enumerate 2D polynomial term exponents up to ``degree``.

    Term index ``k`` maps to ``u**i * v**j`` where ``(i, j)`` enumerates
    homogeneous-degree pairs: ``(0,0), (1,0), (0,1), (2,0), (1,1),
    (0,2), ...`` — the same enumeration as the QF-C generator
    (``tests/synthetic._poly2d``), so an injected gradient with
    coefficients ``c`` is *exactly* representable by the model.
    """
    terms: list[tuple[int, int]] = []
    for deg in range(degree + 1):
        for i in range(deg, -1, -1):
            terms.append((i, deg - i))
    return terms


@dataclass
class GradientModel:
    """Fitted polynomial background model (GR-E reporting basis).

    Attributes:
        degree: Polynomial degree.
        grid: Sampled cell grid ``(rows, cols)``.
        coefficients: Fitted polynomial coefficients (same term order as
            :func:`_poly_terms`; ``model(u, v) = sum c_k * u**i * v**j``).
        n_cells: Total number of sampled cells (grid product).
        n_samples: Cells used for the final fit after rejection.
        n_rejected: Cells rejected overall (initial + iterative).
        n_iterations: Number of iterative rejection rounds performed.
        residual_mad: Robust residual scatter of the accepted samples
            around the final model (``1.4826 * median(|resid|)``).
        residual_max: Max absolute residual of the accepted samples.
    """

    degree: int
    grid: tuple[int, int]
    coefficients: NDArray[np.floating[Any]]
    n_cells: int
    n_samples: int
    n_rejected: int
    n_iterations: int
    residual_mad: float
    residual_max: float

    def evaluate(self, shape: tuple[int, ...]) -> NDArray[np.float64]:
        """Evaluate the model on the full image grid (u, v normalized).

        Returns a 2D array of the same spatial shape as the input frame.
        """
        height, width = shape[0], shape[1]
        v, u = np.mgrid[0:height, 0:width]
        u = (u - (width - 1) / 2) / (width / 2)
        v = (v - (height - 1) / 2) / (height / 2)
        result = np.zeros((height, width), dtype=np.float64)
        for coeff, (i, j) in zip(self.coefficients, _poly_terms(self.degree), strict=True):
            result += coeff * (u**i) * (v**j)
        return result

    def _evaluate_at(self, us: NDArray[np.float64], vs: NDArray[np.float64]) -> NDArray[np.float64]:
        """Evaluate the model at normalized sample coordinates."""
        result = np.zeros(us.shape, dtype=np.float64)
        for coeff, (i, j) in zip(self.coefficients, _poly_terms(self.degree), strict=True):
            result += coeff * (us**i) * (vs**j)
        return result


@dataclass
class GradientRemovalResult:
    """Result of :func:`remove_gradient`.

    Attributes:
        image: Gradient-corrected image (same shape/dtype as input).
        model: The fitted background model (for reporting, GR-E).
        channel_scales: Per-channel scale factors used for the
            subtraction (mono fit, channel-wise scaling, OQ-GR-2).
    """

    image: NDArray[Any]
    model: GradientModel
    channel_scales: list[float]


def _to_mono(image: NDArray[Any]) -> tuple[NDArray[np.float64], bool]:
    """Reduce a 2D/3D image to a mono luminance frame.

    ``image`` is either ``(H, W)`` (returned unchanged) or ``(H, W, C)``
    (returned as the channel mean). Returns ``(mono, is_rgb)``.
    """
    if image.ndim == 2:
        return np.asarray(image, dtype=np.float64), False
    if image.ndim == 3:
        return np.mean(image, axis=-1, dtype=np.float64), True
    raise ValueError(f"image must be 2D or 3D (H, W, C), got shape {image.shape}")


def fit_background(
    image: NDArray[Any],
    *,
    degree: int = 2,
    grid: tuple[int, int] = (16, 16),
    sigma_clip: float = 3.0,
    min_samples: int | None = None,
    max_iter: int = 5,
) -> GradientModel:
    """Fit a polynomial background model with iterative rejection.

    Args:
        image: 2D ``(H, W)`` frame (luminance/mono).
        degree: Polynomial degree (OQ-GR-3 default 2).
        grid: ``(rows, cols)`` sampling grid (OQ-GR-3 default 16x16;
            M13-validiert AC-GR-C4).
        sigma_clip: ``k`` for ``k*sigma`` clipping (``sigma =
            1.4826*MAD``); OQ-GR-3 default 3.0.
        min_samples: Minimum accepted cells for the final fit; below this
            a :class:`GradientRemovalError` is raised. Defaults to the
            number of polynomial terms.
        max_iter: Maximum iterative rejection rounds after the initial
            rejection (default 5).

    Returns:
        The fitted :class:`GradientModel`.

    Raises:
        GradientRemovalError: If fewer than ``min_samples`` cells survive
            the rejection (E1: never return a corrupt model).
    """
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ValueError(f"fit_background expects a 2D image, got shape {image.shape}")
    if degree < 0:
        raise ValueError(f"degree must be >= 0, got {degree!r}")
    rows, cols = grid
    if rows < 2 or cols < 2:
        raise ValueError(f"grid must be at least (2, 2), got {grid!r}")
    if sigma_clip <= 0:
        raise ValueError(f"sigma_clip must be > 0, got {sigma_clip!r}")
    if max_iter < 0:
        raise ValueError(f"max_iter must be >= 0, got {max_iter!r}")

    terms = _poly_terms(degree)
    n_terms = len(terms)
    if min_samples is None:
        min_samples = n_terms
    if min_samples < n_terms:
        raise ValueError(
            f"min_samples {min_samples} < polynomial terms {n_terms} for degree {degree}"
        )

    height, width = image.shape
    cell_h = -(-height // rows)  # ceil division
    cell_w = -(-width // cols)

    # 1. Sampling: per-cell median value and cell center in normalized coords.
    cell_values: list[float] = []
    cell_us: list[float] = []
    cell_vs: list[float] = []
    for r in range(rows):
        y0 = r * cell_h
        y1 = min(y0 + cell_h, height)
        cy = (y0 + y1 - 1) / 2
        for c in range(cols):
            x0 = c * cell_w
            x1 = min(x0 + cell_w, width)
            cx = (x0 + x1 - 1) / 2
            cell = image[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            cell_values.append(float(np.median(cell)))
            cell_us.append((cx - (width - 1) / 2) / (width / 2))
            cell_vs.append((cy - (height - 1) / 2) / (height / 2))

    values = np.asarray(cell_values, dtype=np.float64)
    us = np.asarray(cell_us, dtype=np.float64)
    vs = np.asarray(cell_vs, dtype=np.float64)
    n_cells = values.size
    if n_cells < min_samples:
        raise GradientRemovalError(
            f"sampled {n_cells} cells < min_samples {min_samples} "
            f"(grid {grid} on {shape_str((height, width))})"
        )

    def _sigma(arr: NDArray[np.float64]) -> float:
        median = float(np.median(arr))
        return float(1.4826 * np.median(np.abs(arr - median)))

    # 2. Initial rejection: drop cells far above the global cell median
    #    (stars, bright object cores). A flat sigma (no variation) keeps
    #    all cells.
    global_sigma = _sigma(values)
    if global_sigma > 1e-12:
        keep = values <= float(np.median(values)) + sigma_clip * global_sigma
    else:
        keep = np.ones(values.shape, dtype=bool)

    # 3. + 4. Fit with iterative rejection against the model residuals
    #    plus neighbourhood rejection. The neighbourhood guard is the
    #    AC-GR-A5/A6 protection: a large soft source (galaxy halo,
    #    emission region) leaves rim cells that a pure residual
    #    rejection can miss — the polynomial absorbs them with small
    #    residuals, so the source would be modelled as a "gradient" and
    #    removed. Cells that stand out against their 3x3 neighbourhood
    #    are rejected instead, so the fit only follows the smooth,
    #    global gradient.
    n_iterations = 0
    for _ in range(max_iter):
        kept_values = values[keep]
        kept_us = us[keep]
        kept_vs = vs[keep]

        design = np.column_stack([kept_us**i * kept_vs**j for i, j in terms])
        coefficients, *_rest = np.linalg.lstsq(design, kept_values, rcond=None)

        resid = kept_values - design @ coefficients
        resid_sigma = float(1.4826 * np.median(np.abs(resid - np.median(resid))))
        n_new_resid = 0
        if resid_sigma > 1e-12:
            keep_new = np.abs(resid) <= sigma_clip * resid_sigma
            n_new_resid = int(np.sum(~keep_new))
            keep = keep.copy()
            keep[keep] = keep_new

        n_new_neighbour = 0
        if values.size == rows * cols:
            n_new_neighbour, keep = _neighborhood_reject(values, keep, rows, cols, sigma_clip)

        n_iterations += 1
        if n_new_resid == 0 and n_new_neighbour == 0:
            break

    kept_values = values[keep]
    kept_us = us[keep]
    kept_vs = vs[keep]
    n_samples = int(keep.sum())
    if n_samples < min_samples:
        raise GradientRemovalError(
            f"{n_samples} cells survived rejection < min_samples {min_samples} "
            f"(degree={degree}, grid={grid}, k={sigma_clip})"
        )

    design = np.column_stack([kept_us**i * kept_vs**j for i, j in terms])
    coefficients, *_rest = np.linalg.lstsq(design, kept_values, rcond=None)
    coefficients = np.asarray(coefficients, dtype=np.float64)
    resid = kept_values - design @ coefficients
    resid_mad = float(np.median(np.abs(resid)))

    model = GradientModel(
        degree=degree,
        grid=grid,
        coefficients=coefficients,
        n_cells=n_cells,
        n_samples=n_samples,
        n_rejected=int(n_cells - n_samples),
        n_iterations=n_iterations,
        residual_mad=float(1.4826 * resid_mad),
        residual_max=float(np.max(np.abs(resid))) if resid.size else 0.0,
    )
    logger.info(
        "gradient_removal.model",
        degree=degree,
        grid=f"{rows}x{cols}",
        n_cells=n_cells,
        n_samples=n_samples,
        n_rejected=n_cells - n_samples,
        n_iterations=n_iterations,
        residual_mad=round(model.residual_mad, 4),
    )
    return model


def remove_gradient(
    image: NDArray[Any],
    *,
    degree: int = 2,
    grid: tuple[int, int] = (16, 16),
    sigma_clip: float = 3.0,
    min_samples: int | None = None,
    max_iter: int = 5,
) -> GradientRemovalResult:
    """Remove a smooth background gradient from a 2D or RGB frame.

    Mono fit on the luminance (channel mean), channel-wise subtraction
    scaled by the channel-median ratio (OQ-GR-2). Negative result pixels
    are clipped to 0 (convention like ``_apply_calibration``).

    Args:
        image: ``(H, W)`` mono or ``(H, W, C)`` RGB frame.
        degree, grid, sigma_clip, min_samples, max_iter: forwarded to
            :func:`fit_background`.

    Returns:
        :class:`GradientRemovalResult` with the corrected image and the
        fitted model (reporting basis).

    Raises:
        GradientRemovalError: If the fit is not trustworthy (too few
            samples, E1 — caller skips with warning).
    """
    image = np.asarray(image)
    mono, is_rgb = _to_mono(image)
    model = fit_background(
        mono,
        degree=degree,
        grid=grid,
        sigma_clip=sigma_clip,
        min_samples=min_samples,
        max_iter=max_iter,
    )
    background = model.evaluate(mono.shape)

    if not is_rgb:
        corrected = np.maximum(mono - background, 0.0)
        return GradientRemovalResult(
            image=corrected.astype(image.dtype, copy=False),
            model=model,
            channel_scales=[1.0],
        )

    # OQ-GR-2: scale the mono model per channel by the channel-median
    # ratio so colour ratios are preserved.
    mono_median = float(np.median(mono))
    channel_scales: list[float] = []
    corrected_channels: list[NDArray[Any]] = []
    for c in range(image.shape[-1]):
        channel = image[..., c].astype(np.float64)
        channel_median = float(np.median(channel))
        if mono_median > 1e-6 and np.isfinite(channel_median):
            scale = channel_median / mono_median
        else:
            scale = 1.0
        channel_scales.append(float(scale))
        corrected_channels.append(
            np.maximum(channel - background * scale, 0.0).astype(image.dtype, copy=False)
        )
    corrected = np.stack(corrected_channels, axis=-1)
    return GradientRemovalResult(
        image=corrected,
        model=model,
        channel_scales=channel_scales,
    )


def shape_str(shape: tuple[int, ...]) -> str:
    """Compact shape string for error messages."""
    return "x".join(str(dim) for dim in shape)


# ═══════════════════════════════════════════════════════════════════
# Agent-Wrapper (Refactor 2026-08-14, Cluster 7)
# Verschoben aus ``astro_process/agents/processing_agent.py``
# (ProcessingAgent._background_extraction). Rein verschoben, KEINE
# Verhaltensaenderung: Event-Namen und Report-Schema identisch.
# Frame-I/O erfolgt ueber die Callables ``load_frame``/``save_frame``;
# der Agent bindet seine Methoden und reicht seinen Modul-Logger als
# ``logger=`` durch.
# ═══════════════════════════════════════════════════════════════════


def background_extraction(
    stacked: Optional[Path],
    params: dict,
    *,
    load_frame: Callable[[Path], np.ndarray],
    save_frame: Callable[[np.ndarray, Path], None],
    logger: Optional[logging.Logger] = None,
) -> Optional[dict]:
    """GR-C (AC-GR-C1..C3): Gradient-Removal auf dem gestackten Frame.

    Wird fuer die Preset-Steps `background_extraction` (galaxy_standard)
    und `gradient_removal` (nebula_standard, nebula_narrowband) gerufen
    (AC-GR-B2: kein stiller Ignorier-Fall mehr). Die effektive Config
    (CLI > Config > Preset > Default) ist in ``params["gradient_removal"]``
    verankert (cli.py, resolve_gradient_removal).

    - ``enabled: false`` -> Schritt uebersprungen mit Info-Log
      (v1.1-identisches Bild, AC-GR-C3) — nicht mehr "not implemented".
    - ``GradientRemovalError`` (min_samples unterschritten, Fit
      unzuverlaessig) -> Skip + Warning, Pipeline laeuft weiter
      (AC-GR-B3, AC-GR-E1).
    - Erfolg: Ergebnis ersetzt den Stack In-Place (wie PCC/SCNR,
      AC-GR-C1).

    Refactor: moved from ``ProcessingAgent._background_extraction`` in
    ``astro_process/agents/processing_agent.py`` (Cluster 7, 2026-08-14;
    unveraendert). Frame-I/O erfolgt ueber die Callables ``load_frame``/
    ``save_frame``.

    Args:
        stacked: Path to the stacked FITS file (overwritten on success).
        params: Processing params (liest ``gradient_removal``-Config).
        load_frame: Callable Path -> RGB array (H×W×3).
        save_frame: Callable (array, Path) -> None (ueberschreibt Datei).
        logger: Optional structlog-Logger (Agent reicht seinen durch).

    Returns:
        GR-E-Report (AC-GR-E1): ``{"applied": True, degree, grid,
        sigma_clip, n_samples, n_rejected, n_iterations, residual_mad,
        residual_max, channel_scales, coefficients}`` bei Erfolg;
        ``{"applied": False, skipped_reason, error?}`` bei Skip;
        ``None`` wenn disabled (kein GR-Attempt) oder kein Stack.
    """
    log = logger or logging.getLogger(__name__)
    if not stacked or not stacked.exists():
        return None

    gr_cfg = (params.get("gradient_removal") or {}).copy()
    if not gr_cfg.get("enabled", False):
        log.info("pipeline.gradient_removal_disabled",
                 reason="enabled_false",
                 msg="Gradient removal disabled — frame left unchanged")
        return None

    degree = int(gr_cfg.get("degree", 2))
    grid = tuple(gr_cfg.get("grid", (16, 16)))
    sigma_clip = float(gr_cfg.get("sigma_clip", 3.0))
    min_samples = gr_cfg.get("min_samples")
    log.info("pipeline.gradient_removal_start",
             degree=degree, grid=list(grid), sigma_clip=sigma_clip,
             min_samples=min_samples)

    data = load_frame(stacked)
    if data.ndim != 3 or data.shape[-1] != 3:
        log.warning("pipeline.gradient_removal_skipped",
                    reason=f"expected 3D RGB, got shape {data.shape}")
        return {
            "applied": False,
            "skipped_reason": f"expected_3d_rgb_got_{data.shape}",
        }

    try:
        result = remove_gradient(
            data,
            degree=degree,
            grid=grid,
            sigma_clip=sigma_clip,
            min_samples=min_samples,
        )
    except GradientRemovalError as e:
        # AC-GR-B3/E1: Fit unzuverlaessig -> Schritt uebersprungen +
        # Warning, nie stilles falsches Ergebnis, nie Abbruch.
        log.warning("pipeline.gradient_removal_skipped",
                    reason="gradient_removal_error", error=str(e))
        log.info("pipeline.status", status="success_with_warnings",
                 warning="gradient_removal_skipped")
        return {
            "applied": False,
            "skipped_reason": "gradient_removal_error",
            "error": str(e),
        }

    # AC-GR-C1: In-Place — das Ergebnis ersetzt den Stack.
    save_frame(result.image, stacked)
    # GR-E (AC-GR-E1): Modell-Parameter + Rest-Residuen dokumentieren
    # (merge_report/agent-log — additiv, kein Quality-Gate).
    report = {
        "applied": True,
        "degree": degree,
        "grid": list(grid),
        "sigma_clip": sigma_clip,
        "n_samples": result.model.n_samples,
        "n_rejected": result.model.n_rejected,
        "n_iterations": result.model.n_iterations,
        "residual_mad": round(float(result.model.residual_mad), 4),
        "residual_max": round(float(result.model.residual_max), 4),
        "channel_scales": [round(float(s), 4) for s in result.channel_scales],
        "coefficients": [round(float(c), 4) for c in result.model.coefficients],
    }
    log.info("pipeline.gradient_removal_complete",
             n_samples=report["n_samples"],
             n_rejected=report["n_rejected"],
             n_iterations=report["n_iterations"],
             residual_mad=report["residual_mad"],
             channel_scales=report["channel_scales"])
    return report
