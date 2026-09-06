"""Export — FITS-Kopie, Header-Anreicherung, Preview, final.seq (Clean-Room).

Dieses Modul enthaelt die Export-Logik, die am 2026-08-14 im Refactor
(Cluster 2, processing_agent.py entflechten) aus
``astro_process/agents/processing_agent.py`` in ``core/`` verschoben wurde.
KEINE Verhaltensaenderung — Logik, Logger-Events und Fehler sind 1:1
uebernommen (F-META-1.2 Header-Anreicherung inkl. Keys, XPIXSZ/YPIXSZ,
TAN-WCS, export.header_annotated/pipeline.export_complete, shutil.copy2,
final.seq). Geaendert hat sich nur die Aufruf-Konvention: statt
Instanz-Methoden (``self._export``, ``self._annotate_export_header``,
``self._effective_pixel_size_um``) gibt es Modul-Funktionen mit expliziten
Parametern — ``working_dir`` ersetzt ``self.working_dir``; optionale
Callables (``annotate_export_header_fn``, ``effective_pixel_size_um_fn``)
ermoeglichen Test-Injection und halten das Modul agent-frei (core/ darf
nicht agents/ importieren). Der Modul-Logger ist NICHT
``processing_agent.logger`` (Test-Patches: ``core.export.logger``).

Herkunft/Historie (aus processing_agent.py uebernommen):
- F-META-1.2 (stella Punkt 4 / Befund 7 + Punkt 5): Light-Header-Keys
  (OBJECT..EQMODE) aus dem ersten Light-Frame werden in den Final-FITS-
  Header uebernommen; XPIXSZ/YPIXSZ werden auf die EFFEKTIVE Pixelgroesse
  des gestackten Outputs gesetzt (PCC-Skala -> pixel_scale x FOCALLEN /
  206.265; sonst nativer Wert x stack_scale_factor, Default 2.0), damit
  Siril die korrekte Pixel-Scale ableitet; approximatives TAN-WCS
  (CRVAL/CRPIX/CDELT/CTYPE/CUNIT) aus Zielkoordinaten + Pixel-Skala —
  Naeherung, kein Astrometrie-Fit. Best effort: fehlende Daten/Fehler ->
  Header unveraendert, keine Ausnahme, Daten werden nie veraendert.
"""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

import numpy as np
import structlog
from astropy.io import fits

from ..core.fits_parser import EQMODE_KEY
from ..core.preview import create_preview_jpg
from ..core.seq_file import write_seq
from ..models.core import ObservationContext

if TYPE_CHECKING:
    from ..config.models import ExportConfig, PreviewExportConfig

logger = structlog.get_logger(__name__)


# Refactor: moved from processing_agent.py
# F-META-1.2: Header-Keys, die aus dem ersten Light-Frame in den
# Final-Export-FITS uebernommen werden (Siril/Plate-Solving, Befund 7).
# Nur falls im Light-Header vorhanden (raw_cards) — best effort.
EXPORT_LIGHT_HEADER_KEYS = (
    "OBJECT", "RA", "DEC", "TELESCOP", "INSTRUME", "CAMERA", "FOCALLEN",
    "XPIXSZ", "YPIXSZ", "EXPTIME", "GAIN", "FILTER", "DATE-OBS",
    "DET-TEMP", EQMODE_KEY,
)


# Refactor: moved from processing_agent.py
def effective_pixel_size_um(
    light_cards: dict,
    wcs: dict | None,
    stack_scale_factor: float = 2.0,
) -> float | None:
    """F-META-1.2 (stella Punkt 5): effektive Pixelgroesse des gestackten
    Frames in µm — so, dass Siril daraus die korrekte Pixel-Scale ableitet
    (Siril ignoriert CDELT als Startvorgabe und rechnet 206.265 x XPIXSZ /
    FOCALLEN).

    - PCC-Skala vorhanden + FOCALLEN: ``pixel_scale x FOCALLEN / 206.265``
      (Pixelgroesse aus der gemessenen Skala zurueckgerechnet).
    - sonst Fallback: nativer XPIXSZ/YPIXSZ x ``stack_scale_factor``
      (Default 2.0, Teleskop (z.B. Dwarf3): nativ 2.9 µm, 2x Superpixel-Debayer).

    Beide Wege ergeben dieselbe effektive Pixelgroesse, wenn
    ``stack_scale_factor`` dem tatsaechlichen Binning-Faktor entspricht
    (2.9 x 2.0 = 5.8 µm -> 206.265 x 5.8 / 150 = 7.98 arcsec/px).

    Returns:
        Effektive Pixelgroesse in µm oder ``None`` (best effort: nicht
        bestimmbar — keine Aenderung, keine Fehler).
    """
    scale = (wcs or {}).get("pixel_scale_arcsec", 0.0) or 0.0
    focal = light_cards.get("FOCALLEN")
    if scale > 0 and focal:
        try:
            focal_f = float(focal)
        except (TypeError, ValueError):
            focal_f = 0.0
        if focal_f > 0:
            return float(scale) * focal_f / 206.265
    # Fallback (kein PCC / FOCALLEN fehlt): nativer Wert x Faktor
    native = light_cards.get("XPIXSZ") or light_cards.get("YPIXSZ")
    if native:
        try:
            native_f = float(native)
        except (TypeError, ValueError):
            return None
        if native_f > 0:
            return native_f * float(stack_scale_factor)
    return None


# Refactor: moved from processing_agent.py
def annotate_export_header(
    fits_path: Path,
    context: ObservationContext | None,
    wcs: dict | None = None,
    stack_scale_factor: float = 2.0,
    effective_pixel_size_um_fn: Callable[[dict, dict | None, float], float | None] | None = None,
) -> None:
    """F-META-1.2: reichert den Header eines Export-FITS best-effort an.

    - Light-Header-Keys (``EXPORT_LIGHT_HEADER_KEYS``) aus dem ersten
      Light-Frame (``context.get_lights().frames[0].header.raw_cards``).
    - XPIXSZ/YPIXSZ werden auf die EFFEKTIVE Pixelgroesse des gestackten
      Outputs gesetzt (stella Punkt 5): PCC-Skala vorhanden -> aus der
      gemessenen Skala zurueckgerechnet, sonst nativer Wert x
      ``stack_scale_factor`` (Default 2.0). WCS/CDELT bleiben unveraendert.
    - Approximatives TAN-WCS (CRVAL/CRPIX/CDELT/CTYPE/CUNIT) aus ``wcs``
      {ra, dec, pixel_scale_arcsec} — Naeherung, kein Astrometrie-Fit
      (Befund 7, Siril/Plate-Solving).
    - Best effort: fehlende Daten/Fehler -> Header unveraendert, keine
      Ausnahme. Daten werden nie veraendert, nur der Header (additiv).

    Loggt ``export.header_annotated`` (keys_count, wcs, pixel_size_um,
    pixel_size_adjusted).

    Args:
        fits_path: Pfad zum Export-FITS (wird in-place aktualisiert).
        context: ObservationContext fuer die Light-Frame-Header
            (``None`` -> keine Light-Keys).
        wcs: {ra, dec, pixel_scale_arcsec} fuer approximatives TAN-WCS
            (``None`` -> kein WCS).
        stack_scale_factor: Binning-Faktor fuer die effektive Pixelgroesse
            (Default 2.0, Teleskop (z.B. Dwarf3): 2x Superpixel-Debayer).
        effective_pixel_size_um_fn: Callable fuer die effektive
            Pixelgroesse (Default: Modul-Funktion ``effective_pixel_size_um``;
            austauschbar fuer Tests/Ersetzbarkeit).
    """
    if effective_pixel_size_um_fn is None:
        effective_pixel_size_um_fn = effective_pixel_size_um
    light_cards: dict = {}
    if context is not None:
        try:
            frames = context.get_lights().frames
            if frames and frames[0].header is not None:
                light_cards = getattr(frames[0].header, "raw_cards", None) or {}
        except Exception:  # noqa: BLE001 - best effort (F-META-1.2)
            light_cards = {}
    if not light_cards and not wcs:
        return
    try:
        with fits.open(fits_path, mode="update") as hdul:
            header = hdul[0].header
            keys_written = 0
            for key in EXPORT_LIGHT_HEADER_KEYS:
                value = light_cards.get(key)
                if value not in (None, ""):
                    header[key] = value
                    keys_written += 1
            # F-META-1.2 (stella Punkt 5): XPIXSZ/YPIXSZ auf die
            # EFFEKTIVE Pixelgroesse setzen — Siril ignoriert CDELT und
            # leitet die Pixel-Scale aus XPIXSZ/FOCALLEN ab; mit dem
            # nativen Wert (2.9) kaeme 3.99 statt real 7.98 arcsec/px
            # -> Platesolve schlaegt fehl.
            pixel_size_adjusted = False
            pixel_size_um: float | None = None
            effective_pixel = effective_pixel_size_um_fn(
                light_cards, wcs, stack_scale_factor,
            )
            if effective_pixel is not None:
                header["XPIXSZ"] = effective_pixel
                header["YPIXSZ"] = effective_pixel
                header.add_comment(
                    "Pixel size adjusted for stacked scale (PCC)"
                )
                pixel_size_adjusted = True
                pixel_size_um = round(effective_pixel, 4)
            wcs_written = False
            if wcs:
                ra = wcs.get("ra")
                dec = wcs.get("dec")
                scale = wcs.get("pixel_scale_arcsec", 0.0)
                if ra is not None and dec is not None and scale and scale > 0:
                    naxis1 = header.get("NAXIS1", 0)
                    naxis2 = header.get("NAXIS2", 0)
                    header["CRVAL1"] = float(ra)
                    header["CRVAL2"] = float(dec)
                    header["CRPIX1"] = (naxis1 + 1) / 2.0 if naxis1 else 0.0
                    header["CRPIX2"] = (naxis2 + 1) / 2.0 if naxis2 else 0.0
                    header["CDELT1"] = -float(scale) / 3600.0
                    header["CDELT2"] = float(scale) / 3600.0
                    header["CTYPE1"] = "RA---TAN"
                    header["CTYPE2"] = "DEC--TAN"
                    header["CUNIT1"] = "deg"
                    header["CUNIT2"] = "deg"
                    header.add_comment(
                        "Approximate WCS from target/PCC - not an "
                        "astrometric fit"
                    )
                    wcs_written = True
            logger.info(
                "export.header_annotated",
                path=str(fits_path),
                keys_count=keys_written,
                wcs=wcs_written,
                pixel_size_um=pixel_size_um,
                pixel_size_adjusted=pixel_size_adjusted,
            )
    except Exception as e:  # noqa: BLE001 - F-META-1.2 best effort
        logger.warning(
            "export.header_annotate_failed",
            path=str(fits_path),
            error=str(e),
            msg="Final export header left unchanged (best effort)",
        )


# Refactor: moved from processing_agent.py
def _apply_asinh_display(data: np.ndarray, a: float) -> np.ndarray:
    """V1.8-3: Per-Channel Asinh-Stretch fuer Display-FITS.

    Im Gegensatz zu ``preview.auto_asinh`` wird hier KEIN Hintergrund
    abgezogen, damit der gestretchte FITS in Lightroom/Photoshop hell
    erscheint (Median deutlich hoeher als im linearen FITS). Das Ergebnis
    wird auf den urspruenglichen Kanal-Max-Wert skaliert.

    Formula: ``stretched = asinh(data * a) / asinh(max * a) * max``
    """
    data = data.astype(np.float64)
    result = np.zeros_like(data)

    if data.ndim == 3:
        for c in range(data.shape[-1]):
            ch = data[:, :, c]
            mx = float(ch.max()) if ch.size else 0.0
            if mx > 0 and a > 0:
                denom = np.arcsinh(mx * a)
                if denom > 0:
                    result[:, :, c] = np.arcsinh(ch * a) / denom * mx
                else:
                    result[:, :, c] = ch
            else:
                result[:, :, c] = ch
    else:
        mx = float(data.max()) if data.size else 0.0
        if mx > 0 and a > 0:
            denom = np.arcsinh(mx * a)
            if denom > 0:
                result = np.arcsinh(data * a) / denom * mx
            else:
                result = data
        else:
            result = data
    return result


def _apply_stretch_for_fits(
    data: np.ndarray,
    stretch_config: "ExportConfig",
) -> np.ndarray:
    """V1.8-3: Wende den konfigurierten Stretch auf lineare float32-Daten an.

    - ``asinh``: Display-Asinh (per-channel, KEINE Hintergrund-Subtraktion),
      skaliert auf den urspruenglichen Max-Wert.
    - ``linear``: lineare Normalisierung auf [0, 1], dann Skalierung auf
      den urspruenglichen Max-Wert.
    - ``none``: kein Stretch (nur cast nach float64).

    Args:
        data: Lineares Array (H, W, C) oder (H, W).
        stretch_config: ExportConfig mit ``stretch.method`` und ``stretch.a``.

    Returns:
        Gestretchtes Array (float64), auf den urspruenglichen Max-Wert
        skaliert.
    """
    data = data.astype(np.float64)
    linear_max = float(data.max()) if data.size else 1.0

    method = stretch_config.stretch.method
    if method == "none":
        stretched = data
    elif method == "linear":
        stretched = data
        if linear_max > 0:
            stretched = stretched / linear_max
    else:  # asinh
        stretched = _apply_asinh_display(data, stretch_config.stretch.a)

    # Sicherstellen, dass der gestretchte FITS im positiven Bereich bleibt.
    return np.clip(stretched, 0.0, None)


def export_stretched_fits(
    source: Path | np.ndarray,
    path: Path,
    stretch_config: "ExportConfig",
) -> Optional[Path]:
    """V1.8-3 (AC-FITS-A2): Schreibe einen gestretchten FITS fuer Display-Zwecke.

    Der gestretchte FITS ist eine **additive** Display-Variante neben dem
    linearen FITS. Er wird NIE fuer wissenschaftliche Steps (Platesolve,
    PCC, Photometrie) verwendet.

    - Float32, NAXIS=3 fuer RGB.
    - Header ``STRETCH=<method>`` + Kommentar
      ``stretched for display, linear is scientific``.
    - ``asinh``: Display-Asinh via ``_apply_asinh_display`` (per-Channel, KEINE
      Hintergrund-Subtraktion, skaliert auf den absoluten Kanal-Max — hellt den
      FITS fuer Lightroom/Photoshop auf, bewusst abweichend von
      ``preview.auto_asinh``, welches den Median-Hintergrund abzieht).

    Args:
        source: Lineare FITS-Datei oder ndarray (H, W, C) bzw. (H, W).
        path: Zielpfad fuer den gestretchten FITS.
        stretch_config: ExportConfig mit ``stretch.*`` Einstellungen.

    Returns:
        ``path`` bei Erfolg, ``None`` bei Fehler (best effort).
    """
    try:
        if isinstance(source, Path):
            with fits.open(source) as hdul:
                data = hdul[0].data.astype(np.float32)
        else:
            data = source.astype(np.float32)

        # Achsenordnung: FITS speichert (C, H, W), intern arbeiten wir (H, W, C)
        if data.ndim == 3 and data.shape[0] == 3:
            data = data.transpose(1, 2, 0)

        stretched = _apply_stretch_for_fits(data, stretch_config)

        out = stretched.astype(np.float32)
        if out.ndim == 3:
            out = out.transpose(2, 0, 1)
        hdu = fits.PrimaryHDU(out)
        if data.ndim == 3:
            hdu.header["CTYPE3"] = "RGB"
            hdu.header["CUNIT3"] = "channel"
        hdu.header["STRETCH"] = stretch_config.stretch.method
        hdu.header.add_comment("stretched for display, linear is scientific")

        path.parent.mkdir(parents=True, exist_ok=True)
        hdu.writeto(path, overwrite=True)
        logger.info(
            "export.stretched_fits_created",
            path=str(path),
            method=stretch_config.stretch.method,
            a=stretch_config.stretch.a,
        )
        return path
    except Exception as e:  # noqa: BLE001 - best effort
        logger.warning(
            "export.stretched_fits_failed",
            path=str(path),
            error=str(e),
        )
        return None


def export(
    final_image: Optional[Path],
    target_name: str,
    context: ObservationContext | None = None,
    wcs: dict | None = None,
    stack_scale_factor: float = 2.0,
    working_dir: Optional[Path] = None,
    annotate_export_header_fn: Callable[..., None] | None = None,
    preview_config: Optional["PreviewExportConfig"] = None,
    export_config: Optional["ExportConfig"] = None,
) -> List[Path]:
    """Export as 32-bit FITS only (linear, RGB, unstreched) + auto-stretched JPG preview.

    F-META-1.2: wenn ``context`` gegeben, wird der Final-FITS-Header
    best-effort angereichert (Light-Header-Keys + approximatives WCS +
    effektive Pixelgroesse XPIXSZ/YPIXSZ, stella Punkt 5).

    V1.8-2: ``preview_config`` aktiviert die erweiterte Preview-Pipeline
    (background_neutralization -> scnr -> stretch -> saturation -> jpg).
    ``None`` -> Asinh-only (byte-identisch zu v1.6).

    V1.8-3: ``export_config.stretched_fits`` aktiviert einen zusaetzlichen
    gestreckten FITS (``*_stretched.fits``) neben dem linearen FITS.
    Default ``False`` -> byte-identisch zu v1.6/V1.8-2.

    Args:
        final_image: Gestackter FITS (``None``/fehlend -> leere Liste).
        target_name: Zielname fuer die Export-Dateien
            (``safe_name = target_name.replace(" ", "_")...``).
        context: ObservationContext fuer die Header-Anreicherung
            (``None`` -> keine Anreicherung).
        wcs: {ra, dec, pixel_scale_arcsec} fuer approximatives TAN-WCS.
        stack_scale_factor: Binning-Faktor fuer die effektive Pixelgroesse
            (Default 2.0).
        working_dir: Ziel-Verzeichnis (ersetzt ``self.working_dir`` des
            Agents; ``None`` nur sinnvoll, wenn ``final_image`` fehlt).
        annotate_export_header_fn: Callable fuer die Header-Anreicherung
            (Default: Modul-Funktion ``annotate_export_header``;
            austauschbar fuer Tests/Ersetzbarkeit).
        preview_config: V1.8-2 Preview/Export-Pipeline Einstellungen.
        export_config: V1.8-3 Export-Einstellungen (``stretched_fits``,
            ``stretch``). ``None`` -> kein gestreckter FITS.
    """
    if annotate_export_header_fn is None:
        annotate_export_header_fn = annotate_export_header
    if not final_image or not final_image.exists():
        return []

    exports = []
    safe_name = target_name.replace(" ", "_").replace("(", "").replace(")", "")

    # FITS copy (linear, kanonisch, wissenschaftlich)
    fits_out = working_dir / f"{safe_name}_final.fits"
    shutil.copy2(final_image, fits_out)
    if context is not None:
        annotate_export_header_fn(
            fits_out, context, wcs=wcs, stack_scale_factor=stack_scale_factor,
        )
    exports.append(fits_out)

    # V1.8-3: optionaler gestreckter FITS (additiv, nie Ersatz)
    stretched_enabled = (
        export_config is not None and export_config.stretched_fits is True
    )
    if stretched_enabled:
        stretched_out = working_dir / f"{safe_name}_stretched.fits"
        stretched = export_stretched_fits(fits_out, stretched_out, export_config)
        if stretched:
            exports.append(stretched)

    # Auto-stretched JPG preview (for quick visual inspection without Siril)
    jpg_out = working_dir / f"{safe_name}_final_preview.jpg"
    preview = create_preview_jpg(fits_out, jpg_out, preview_config=preview_config)
    if preview:
        exports.append(preview)

    # Write final seq
    seq_path = working_dir / "final.seq"
    write_seq(seq_path, [fits_out], prefix=f"{safe_name}_final")

    logger.info("pipeline.export_complete", formats=[".fits", ".jpg" if preview else ""])
    return exports
