"""Structure Enhancement plugin (v1.2, F-SE-1.2, SE-A/SE-B/SE-C).

Erstes Produktiv-Plugin der Astra-Pipeline: Unsharp Masking (Gaussian
High-Pass) mit Intensitaets-Gate auf dem gestackten Bild
(v12-structure-enhancement.md).

Algorithmus pro Kanal ``c`` (SE-A, Schritte 1-10):
1. Robuste Statistik: ``m_c = median(I_c)``, ``mad_c = median(|I_c - m_c|)``.
2. Rausch-Boden: ``floor_c = m_c + k_floor * mad_c`` (``k_floor = 2.0``, fest).
3. Stern-Decke: ``ceil_c = quantile(I_c, 0.995)`` (fest).
4. Schutzfall: ``ceil_c <= floor_c`` -> Kanal unveraendert (Info-Log, nie
   Abbruch — AC-SE-A6).
5. ``mid_c = (floor_c + ceil_c) / 2``.
6. ``B_c = gaussian_filter(I_c, sigma=radius)``.
7. ``HP_c = I_c - B_c``.
8. Gate (Tent): ``g_c(x) = 0`` fuer ``x <= floor_c`` und ``x >= ceil_c``;
   linear ``0 -> 1`` fuer ``floor_c < x <= mid_c``; linear ``1 -> 0`` fuer
   ``mid_c < x < ceil_c``.
9. ``E_c = I_c + amount * g_c(I_c) * HP_c``.
10. Clipping: ``E_c = max(E_c, 0)``.

Determinismus: kein RNG; reine numpy/scipy (gleiche Eingabe -> identisches
Ergebnis, AC-SE-E1). Gate-Konstanten sind fix (OQ-SE-3, Option A); nur
``radius``/``amount`` sind konfigurierbar (SE-C, am Preset-Step via
``PipelineStep.params``).

Vertrag (SE-B): Input ``working_dir/04_stacked/stacked.fits`` (aktueller
Stack), Output ``output_dir/04_stacked/enhanced.fits`` (float32, FITS-Achsen
(C,H,W), ``CTYPE3=RGB``). Fehler -> ``PluginResult(ok=False)``, nie Abbruch
(E1, OQ-PL-4). Fehlender Input -> ``ok=False`` (reason ``stack_not_found``).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy.ndimage import gaussian_filter

from astro_process.core.plugins import Plugin, PluginContext, PluginResult

# Feste Gate-Konstanten (OQ-SE-3, Option A): nicht konfigurierbar in v1.2.
K_FLOOR = 2.0
CEIL_QUANTILE = 0.995

# Konservative Defaults (SE-C): Step ohne ``params`` -> diese Werte.
DEFAULT_RADIUS = 3.0
DEFAULT_AMOUNT = 0.2

# Gueltigkeitsgrenzen (SE-C2): ausserhalb -> Warning + Clamp, nie Abbruch.
RADIUS_MIN, RADIUS_MAX = 0.5, 50.0
AMOUNT_MIN, AMOUNT_MAX = 0.0, 1.0

STEP_NAME = "structure_enhancement"
STACK_FILENAME = "stacked.fits"
ENHANCED_FILENAME = "enhanced.fits"

__all__ = [
    "K_FLOOR",
    "CEIL_QUANTILE",
    "DEFAULT_RADIUS",
    "DEFAULT_AMOUNT",
    "RADIUS_MIN",
    "RADIUS_MAX",
    "AMOUNT_MIN",
    "AMOUNT_MAX",
    "STEP_NAME",
    "apply_structure_enhancement",
    "apply_structure_enhancement_with_report",
    "StructureEnhancementPlugin",
]


def _enhance_channel(
    channel: np.ndarray, radius: float, amount: float
) -> tuple[np.ndarray, bool]:
    """USM + Intensitaets-Gate fuer EINEN Kanal (SE-A, Schritte 1-10).

    Returns:
        (enhanced, degenerate): ``degenerate=True`` wenn das Gate
        degeneriert ist (``ceil_c <= floor_c``, AC-SE-A6) — Kanal
        unveraendert, kein Fehler.
    """
    m = float(np.median(channel))
    mad = float(np.median(np.abs(channel - m)))
    floor_v = m + K_FLOOR * mad
    ceil_v = float(np.quantile(channel, CEIL_QUANTILE))
    if ceil_v <= floor_v:
        # Schutzfall (AC-SE-A6): degeneriertes Bild -> Kanal unveraendert.
        return channel.copy(), True
    mid = (floor_v + ceil_v) / 2.0
    half = mid - floor_v
    blurred = gaussian_filter(channel, sigma=radius)
    hp = channel - blurred
    # Gate (Tent-Funktion, SE-A Schritt 8). Ausserhalb der Masken bleibt
    # gate exakt 0.0 -> Pixel unterhalb floor / oberhalb ceil exakt identisch.
    gate = np.zeros_like(channel, dtype=np.float32)
    left = (channel > floor_v) & (channel <= mid)
    right = (channel > mid) & (channel < ceil_v)
    gate[left] = (channel[left] - floor_v) / half
    gate[right] = (ceil_v - channel[right]) / half
    enhanced = channel + amount * gate * hp
    # Clipping (SE-A Schritt 10): Konvention wie _apply_calibration.
    np.clip(enhanced, 0.0, None, out=enhanced)
    return enhanced, False


def apply_structure_enhancement_with_report(
    image: np.ndarray,
    radius: float = DEFAULT_RADIUS,
    amount: float = DEFAULT_AMOUNT,
) -> tuple[np.ndarray, list[int]]:
    """Per-Kanal USM + Gate (SE-A).

    ``image`` ist (H, W) mono oder (H, W, C) RGB (internes Layout). Gibt
    das Enhanced-Bild (gleiche Form, float32) und die Liste der
    degenerierten Kanaele (AC-SE-A6, fuer den Info-Log) zurueck.
    """
    image = np.asarray(image, dtype=np.float32)
    if image.ndim == 2:
        out, degenerate = _enhance_channel(image, radius, amount)
        return out, [0] if degenerate else []
    if image.ndim == 3:
        channels = []
        degenerate: list[int] = []
        for c in range(image.shape[-1]):
            out, deg = _enhance_channel(image[..., c], radius, amount)
            channels.append(out)
            if deg:
                degenerate.append(c)
        return np.stack(channels, axis=-1), degenerate
    raise ValueError(f"unsupported image shape {image.shape!r}")


def apply_structure_enhancement(
    image: np.ndarray,
    radius: float = DEFAULT_RADIUS,
    amount: float = DEFAULT_AMOUNT,
) -> np.ndarray:
    """Reine Funktion (AC-SE-A1): USM + Intensitaets-Gate, deterministisch.

    Ohne I/O direkt testbar; gleiche Eingabe -> identisches Ergebnis
    (kein RNG, AC-SE-E1).
    """
    enhanced, _ = apply_structure_enhancement_with_report(image, radius, amount)
    return enhanced


def _clamp_value(
    value: object,
    lo: float,
    hi: float,
    default: float,
    name: str,
    clamped: list[tuple[str, object, float, str]],
) -> float:
    """SE-C2: Wert validieren und auf die Grenzen clampsen (mit Notiz)."""
    if value is None:
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        clamped.append((name, value, default, f"non-numeric -> default {default}"))
        return default
    if not math.isfinite(v):
        clamped.append((name, value, default, f"non-finite -> default {default}"))
        return default
    if v < lo:
        clamped.append((name, value, lo, f"clamped to [{lo}, {hi}]"))
        return lo
    if v > hi:
        clamped.append((name, value, hi, f"clamped to [{lo}, {hi}]"))
        return hi
    return v


def _resolve_params(
    params: dict | None, logger: object
) -> tuple[float, float]:
    """SE-C: Step-Params (radius/amount) mit Clamp + Warning.

    Ohne Konfiguration gelten die Defaults (3.0 / 0.2). Ungueltige Werte
    -> Warning (``structure_enhancement.params_clamped``) + Clamp auf die
    Grenzen — nie Abbruch, nie stiller Erfolg (E1).
    """
    params = dict(params or {})
    clamped: list[tuple[str, object, float, str]] = []
    radius = _clamp_value(
        params.get("radius"), RADIUS_MIN, RADIUS_MAX, DEFAULT_RADIUS, "radius", clamped
    )
    amount = _clamp_value(
        params.get("amount"), AMOUNT_MIN, AMOUNT_MAX, DEFAULT_AMOUNT, "amount", clamped
    )
    for name, value, clamped_to, note in clamped:
        logger.warning(  # type: ignore[attr-defined]
            "structure_enhancement.params_clamped",
            param=name,
            value=value,
            clamped_to=clamped_to,
            note=note,
        )
    return radius, amount


def _load_stack(path: Path) -> np.ndarray:
    """Laedt den Stack (FITS (C,H,W) -> intern (H,W,C); 2D bleibt 2D)."""
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float32)
    if data.ndim == 3:
        data = data.transpose(1, 2, 0)  # (C, H, W) -> (H, W, C)
    return data


def _save_stack(data: np.ndarray, path: Path) -> None:
    """Speichert den Enhanced-Stack (intern (H,W,C) -> FITS (C,H,W))."""
    out = np.asarray(data, dtype=np.float32)
    if out.ndim == 3:
        out = out.transpose(2, 0, 1)  # (H, W, C) -> (C, H, W)
    hdu = fits.PrimaryHDU(out)
    if out.ndim == 3:
        hdu.header["CTYPE3"] = "RGB"
        hdu.header["CUNIT3"] = "channel"
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)


class StructureEnhancementPlugin(Plugin):
    """Erstes Produktiv-Plugin (SE-B): ``structure_enhancement``.

    Handelt genau den deklarierten Preset-Step ``structure_enhancement``
    (SE-B-Vertrag). Wirft nicht: Fehler -> ``PluginResult(ok=False)``
    (E1, OQ-PL-4). Fehlender Input -> ``ok=False``
    (reason ``stack_not_found``).
    """

    @property
    def name(self) -> str:
        return "structure_enhancement"

    @property
    def version(self) -> str:
        return "1.0.0"

    def handles(self, step_name: str) -> bool:
        return step_name == STEP_NAME

    def run(self, context: PluginContext) -> PluginResult:
        stacked = Path(context.working_dir) / "04_stacked" / STACK_FILENAME
        if not stacked.exists():
            return PluginResult(
                ok=False,
                step=STEP_NAME,
                log_fields={"reason": "stack_not_found", "path": str(stacked)},
            )

        radius, amount = _resolve_params(context.step_params, context.logger)

        try:
            data = _load_stack(stacked)
            enhanced, degenerate = apply_structure_enhancement_with_report(
                data, radius, amount
            )
        except Exception as e:  # noqa: BLE001 - Plugin-Fehler -> ok=False (E1)
            return PluginResult(
                ok=False,
                step=STEP_NAME,
                log_fields={"reason": "processing_error", "error": str(e)},
            )

        for c in degenerate:
            context.logger.info(  # type: ignore[attr-defined]
                "structure_enhancement.channel_unchanged",
                channel=c,
                reason="degenerate_gate",
            )

        out_path = Path(context.output_dir) / "04_stacked" / ENHANCED_FILENAME
        try:
            _save_stack(enhanced, out_path)
        except Exception as e:  # noqa: BLE001 - Plugin-Fehler -> ok=False (E1)
            return PluginResult(
                ok=False,
                step=STEP_NAME,
                log_fields={"reason": "write_error", "error": str(e)},
            )

        context.logger.info(  # type: ignore[attr-defined]
            "structure_enhancement.complete",
            radius=radius,
            amount=amount,
            path=str(out_path),
        )
        return PluginResult(
            ok=True,
            step=STEP_NAME,
            artifact=out_path,
            log_fields={"radius": radius, "amount": amount},
        )
