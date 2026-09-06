"""Stacking — Rejection-Mapping, Winsor-Sigma, Frame-Stacking (Clean-Room).

Dieses Modul enthaelt die Stacking-Logik, die am 2026-08-14 im Refactor
(Cluster 1, processing_agent.py entflechten) aus
``astro_process/agents/processing_agent.py`` in ``core/`` verschoben wurde.
KEINE Verhaltensaenderung — Logik, Logger-Events und Fehler sind 1:1
uebernommen. Geaendert hat sich nur die Aufruf-Konvention: statt
Instanz-Methoden (``self._stack_frames``, ``self._stack_frames_python``,
``self._stack_2d``, ``self._load_frame``/``self._save_frame``) gibt es
Modul-Funktionen mit expliziten Parametern (``stacked_dir``,
``load_frame``/``save_frame``-Callables). Der Modul-Logger ist NICHT
``processing_agent.logger`` (Test-Patches: ``core.stacking.logger``).

Herkunft/Historie (aus processing_agent.py uebernommen):
- stella-Diagnose C20 20260810-052954: nebula_standard setzt
  `rejection: "winsorized"`, aber der Stack-Code nutzte nur
  `params.get("stacking_method", "average")` — `rejection` wurde nirgends
  verarbeitet, der C20-Stack lief mit purem Average. `resolve_stack_method`
  mappt `rejection` auf die `stack_2d`-Methode (stella-Vorgabe Z. 83-84);
  `winsorized_sigma_clip` ist die echte iterative Siril-Stil-Implementierung
  (ersetzt den frueheren Perzentil-Clip 5/95 + Mean, stella Z. 62-63).

Abgrenzung V1.7-3 (SCS-A) — winsorized vs sigma_clipped_mean:
- ``winsorized_sigma_clip`` KLEMMT Ausreisser auf [med - kσ, med + kσ]
  (``np.clip``) und mittelt danach ALLE Werte — verwandtschaftsrisiko
  (Risiko-Tabelle v17-sigma-clipped-stack.md) — gemeinsame Struktur
  (Median/RMS je Iteration, vektorisiert, keine Python-Pixel-Schleife).
- ``sigma_clipped_mean`` VERWIRFT Ausreisser vollstaendig (Maske) und
  mittelt nur ueber die verbleibenden Pixel — harte Spuren (Satellit,
  Hotpixel-Cluster) verschwinden statt Restanteil zu behalten. Parameter
  fest verdrahtet (OQ-SCS-2 A: low=3.0/high=3.0/iterations=5), iterativ mit
  Early-Stop (OQ-SCS-1 A), Pixel-total-Mask → Median-Fallback (AC-SCS-A4).
"""

from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


# Refactor: moved from processing_agent.py
def resolve_stack_method(params: dict) -> str:
    """Stacking-Methode fuer `stack_2d` aus Processing-Params aufloesen.

    Precedence (Teil B3, analog --merge-method / resolve_registration):
    1. Explizites ``stacking_method`` (Preset, Config oder CLI-Flag
       ``--stacking-method``) — gewinnt immer.
    2. ``rejection``-Mapping (stella-Vorgabe, Auftrag Z. 83-84):
       winsorized -> winsorized, average -> average, none -> average.
    3. Default "average" (bisheriges Fallback-Verhalten).

    Args:
        params: ``ProcessingParams.model_dump()``-dict (oder Teilmenge).

    Returns:
        Eine der Methoden, die `stack_2d` kennt (average/median/
        winsorized/weighted); unbekannte Werte fallen auf "average"
        zurueck (v1.3-Verhalten).
    """
    method = params.get("stacking_method")
    if method:
        return method
    rejection = params.get("rejection")
    if rejection == "winsorized":
        return "winsorized"
    if rejection in ("average", "none"):
        return "average"
    return "average"


# Refactor: moved from processing_agent.py
def winsorized_sigma_clip(data: np.ndarray, low_sigma: float = 2.0,
                           high_sigma: float = 2.0,
                           iterations: int = 5) -> np.ndarray:
    """Siril-Stil Winsorized Sigma Clipping ueber die Stack-Achse (axis=0).

    Leo-Auftrag 2026-08-10 (Teil B2): ersetzt den frueheren Perzentil-Clip
    (5/95 + Mean) — stella: "Siril-Winsor = iteratives Sigma-Clipping mit
    Winsorisierung, nicht nur Perzentil-Clip" (Auftrag Z. 62-63). Referenz:
    Siril-Handbuch 04-Siril-Referenz.md §7 "Winsor Sigma" (Deep-Sky-
    Standard; entfernt Satelliten, Flugzeuge, einzelne Hotpixel).

    Algorithmus je Pixel ueber die Frames (iterativ, vektorisiert — keine
    Python-Pixel-Schleife):
    1. Median m und Streuung s = RMS-Abweichung um den Median.
    2. Grenzen: low = m - low_sigma*s, high = m + high_sigma*s.
    3. Winsorisieren: Werte ausserhalb [low, high] auf die Grenze klemmen
       statt verwerfen (erhaelt den Fluss besser als Rejection, Siril).
    4. Wiederholen (Default 5 = Siril-Default), danach Mean der
       winsorisierten Werte.

    Args:
        data: (N, H, W) Frames entlang Achse 0. MUSS finite Werte haben
            (der NaN-Guard in `stack_2d` laeuft vorher).
        low_sigma: Untere Sigma-Grenze (Siril-Default 2.0).
        high_sigma: Obere Sigma-Grenze (Siril-Default 2.0).
        iterations: Anzahl Iterationen (Siril-Default 5).

    Returns:
        (H, W) Winsor-Sigma-Stack (Mean der winsorisierten Werte).
    """
    stack = data.astype(np.float64, copy=True)
    for _ in range(iterations):
        med = np.median(stack, axis=0)
        dev = stack - med[np.newaxis, ...]
        sigma = np.sqrt(np.mean(dev * dev, axis=0))
        low = med - low_sigma * sigma
        high = med + high_sigma * sigma
        # sigma == 0 -> low == high == med -> alles auf med geklemmt (ok)
        np.clip(stack, low, high, out=stack)
    return np.mean(stack, axis=0)


def sigma_clipped_mean(data: np.ndarray, low_sigma: float = 3.0,
                       high_sigma: float = 3.0,
                       iterations: int = 5) -> np.ndarray:
    """Sigma-Clipped Mean ueber die Stack-Achse (axis=0) — Verwerfen statt Klemmen.

    V1.7-3 SCS-A (OQ-SCS-1 A iterativ + EarlyStop, OQ-SCS-2 A fest verdrahtet):
    Alternative zu ``winsorized_sigma_clip``. Verwandtschaftsrisiko dokumentiert
    im Modul-Docstring — gemeinsame Struktur (Median/RMS je Iteration,
    vektorisiert, keine Python-Pixel-Schleife), aber anderes Clipping:

    - winsorized: ``np.clip`` → Ausreisser an Grenzen klemmen, danach Mean
      ueber ALLE Werte (Siril-Winsor, Fluss-erhaltend).
    - sigma_clipped: Maske [med - low·σ, med + high·σ] → Ausreisser VERWERFEN,
      danach Mean nur ueber verbleibende Werte (Siril-Rejection, harte Spuren).

    Algorithmus je Pixel ueber die Frames (iterativ, vektorisiert):
    1. Median m und Streuung s = RMS-Abweichung um den Median ueber die noch
       NICHT maskierten Werte (axis=0, ``nanmean``-Semantik — astropy-
       Konvention, OQ-SCS-1 A). Erste Iteration: alle Werte gueltig.
    2. Grenzen: low = m - low_sigma*s, high = m + high_sigma*s.
    3. Maskieren: Werte ausserhalb [low, high] werden verworfen (nicht
       geklemmt, Unterschied zu ``np.clip`` in winsorized, Spec SCS-A).
    4. Wiederholen (Default 5, Backlog-Vorgabe AC-SCS-A3), Early-Stop wenn
       sich die Maske nicht mehr aendert (OQ-SCS-1 A). Danach Mean der
       verbleibenden Werte je Pixel.
    5. Pixel mit ausschliesslich maskierten Werten → Fallback auf den
       Pixel-Median der Originaldaten (kein NaN — sonst wuerde der harte
       Final-Guard in ``stack_frames_python`` Z.212-217 den ganzen Stack
       verwerfen, AC-SCS-A4).

    2-pass-Semantik je Iteration: Pass 1 Statistik (Median/σ), Pass 2
    Clip+Mean — der stella-proposal-Pseudo-Code ist die 1-Iter-Minimalform
    davon (OQ-SCS-1 Beschluss: astropy-Konvention).

    Args:
        data: (N, H, W) Frames entlang Achse 0. MUSS finite Werte haben
            (NaN-Guard in ``stack_2d`` laeuft vorher, Bestandsverhalten).
        low_sigma: Untere Sigma-Grenze (Backlog-Default 3.0, AC-SCS-A3).
        high_sigma: Obere Sigma-Grenze (Backlog-Default 3.0).
        iterations: Max. Iterationen (Backlog-Default 5).

    Returns:
        (H, W) Sigma-Clipped Stack (Mean der nicht-maskierten Werte,
        all-masked → Median).
    """
    import warnings

    orig = data.astype(np.float64, copy=False)
    # Original median je Pixel fuer all-masked Fallback (immer finite,
    # da Eingabe finite — Bestandsverhalten).
    orig_median = np.median(orig, axis=0)

    # Maske: True = behalten, False = verworfen. Vektorisiert (N,H,W).
    mask = np.ones(orig.shape, dtype=bool)

    for _ in range(iterations):
        # Maskierte Werte als NaN fuer nanmedian/nanmean (vektorisiert).
        masked = np.where(mask, orig, np.nan)
        # Median je Pixel ueber verbliebene Werte (nanmedian ignoriert NaN).
        # Unterdruecke "All-NaN slice" Warning — all-masked wird unten via
        # Fallback behandelt.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered")
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            med = np.nanmedian(masked, axis=0)
            # RMS-Streuung um den Median nur ueber verbliebene Werte.
            # med[np.newaxis,...] broadcast auf (N,H,W); nanmean ignoriert NaN.
            dev = masked - med[np.newaxis, ...]
            sigma = np.sqrt(np.nanmean(dev * dev, axis=0))

        low = med - low_sigma * sigma
        high = med + high_sigma * sigma

        # sigma==0 -> low==high==med -> nur exakt med bleibt (ok).
        # sigma nan oder med nan (all-masked Pixel) -> low/high nan ->
        # Vergleich liefert False -> Pixel bleibt all-masked.
        # Inklusive Grenzen [low, high] (wie winsorized).
        within_low = orig >= low[np.newaxis, ...]
        within_high = orig <= high[np.newaxis, ...]
        within = within_low & within_high
        # within ist False wo low/high nan (korrekt: all-masked bleibt).
        # Monotone Maske: nur verwerfen, nie zurueckholen (astropy-Konvention).
        new_mask = mask & within

        if np.array_equal(new_mask, mask):
            mask = new_mask
            break
        mask = new_mask

    # Finaler Mean nur ueber verbliebene Werte.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice")
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        masked_final = np.where(mask, orig, np.nan)
        result = np.nanmean(masked_final, axis=0)

    # All-masked Pixel: NaN -> Fallback auf Original-Median (AC-SCS-A4,
    # verhindert Final-Guard Z.212-217).
    all_masked = ~np.isfinite(result)
    if np.any(all_masked):
        result[all_masked] = orig_median[all_masked]

    return result


# Refactor: moved from processing_agent.py
def stack_frames(registered_frames: List[Path], params: dict, is_3d: bool = False,
                 stacked_dir: Optional[Path] = None,
                 load_frame: Optional[Callable] = None,
                 save_frame: Optional[Callable] = None) -> Optional[Path]:
    """Stack registered frames. For 3D, stacks each channel independently.

    Args:
        registered_frames: Registrierte Frame-Pfade (Stack-Eingabe).
        params: ``ProcessingParams.model_dump()``-dict (oder Teilmenge).
        is_3d: True -> 3D-RGB-Frames (H, W, C), Kanaele unabhaengig.
        stacked_dir: Zielverzeichnis fuer ``stacked.fits`` (vorher
            ``self.stacked_dir``).
        load_frame: Callable zum Laden eines Frames (vorher
            ``self._load_frame``). None -> Laden nicht moeglich; Aufrufer
            muss es fuer echte Stacks setzen.
        save_frame: Callable zum Speichern des Ergebnisses (vorher
            ``self._save_frame``). None -> Speichern nicht moeglich.

    Returns:
        Pfad zum Stack (``stacked_dir/stacked.fits``) oder None bei
        Skip/Fehlen des Ausgabefiles.
    """
    if not registered_frames:
        return None
    # P2-1 (ray-Review, R3-Randfall): nur der Referenz-Frame registriert
    # (alle Nicht-Referenz-Frames per registration.frame_rejected
    # verworfen oder fehlgeschlagen) -> sauberer Skip statt ValueError
    # ("Need at least 2 frames to stack"). Default-Pfad (>= 2 Frames)
    # bleibt unveraendert; der Aufrufer (run/process_multi_group) reicht
    # den Skip durch (stacked=None, Gruppe faehrt als Skip fort).
    if len(registered_frames) < 2:
        logger.warning(
            "processing.stack_skipped",
            frames=len(registered_frames),
            reason="insufficient_frames",
        )
        return None

    output = stacked_dir / "stacked.fits"
    # Leo-Auftrag 2026-08-10 (Teil B1): `rejection` aus Preset/Config
    # auf die `stack_2d`-Methode mappen (winsorized->winsorized,
    # average->average, none->average); explizites `stacking_method`
    # (Preset/Config/CLI-Flag --stacking-method) gewinnt. Vorher fiel
    # der Code ohne `stacking_method` immer auf Average zurueck
    # (stella-Diagnose C20: nebula_standard rejection "winsorized"
    # lief mit purem Average).
    stack_frames_python(
        registered_frames, output,
        method=resolve_stack_method(params),
        normalization=params.get("normalization", "mul"),
        is_3d=is_3d,
        load_frame=load_frame,
        save_frame=save_frame,
    )

    if output.exists():
        logger.info("processing.stack_complete", path=str(output))
        return output
    return None


# Refactor: moved from processing_agent.py
def stack_frames_python(input_paths: List[Path], output_path: Path,
                        method: str = "average", normalization: str = "mul",
                        is_3d: bool = False,
                        load_frame: Optional[Callable] = None,
                        save_frame: Optional[Callable] = None) -> None:
    """Stack frames. Handles both 2D and 3D (per-channel stacking).

    Args:
        input_paths: Frame-Pfade (>= 2).
        output_path: Zielpfad des Stacks.
        method: average/median/winsorized/weighted/sigma_clipped_mean
            (Default average).
        normalization: "mul" (Default), "add" oder "no".
        is_3d: True -> (H, W, C)-Frames, Kanaele unabhaengig stacken.
        load_frame: Callable zum Laden eines Frames (vorher
            ``self._load_frame``).
        save_frame: Callable zum Speichern des Ergebnisses (vorher
            ``self._save_frame``).
    """
    if len(input_paths) < 2:
        raise ValueError("Need at least 2 frames to stack")

    # Load all frames
    frames = [load_frame(p) for p in input_paths]
    stack = np.stack(frames, axis=0)  # (N, H, W) or (N, H, W, C)

    if is_3d:
        # Per-channel stacking: transpose to (C, N, H, W) for channel-independent ops
        n_channels = stack.shape[-1]
        channels = []
        for c in range(n_channels):
            ch_data = stack[..., c]  # (N, H, W)
            ch_result = stack_2d(ch_data, method, normalization)
            channels.append(ch_result)
        result = np.stack(channels, axis=-1)  # (H, W, C)
    else:
        result = stack_2d(stack, method, normalization)

    # Leo-Auftrag 2026-08-09 (Teil 3, Final-Export-Guard): kein kaputtes
    # FITS schreiben. Nach dem Frame-Ausschluss sind die Eingaben finite
    # und die Mediane != 0, daher ist ein NaN-Ergebnis hier reine
    # Defensive. Bewusst HART (jedes nicht-finite Pixel -> FAIL) statt
    # der 5 %-Config aus der Auftragsquelle: ein FITS mit NaN-Loechern
    # ist fuer Downstream (PCC/Stretch/Export) unbrauchbar.
    if not np.all(np.isfinite(result)):
        n_nonfinite = int(np.count_nonzero(~np.isfinite(result)))
        raise ValueError(
            f"stack.non_finite_result: {n_nonfinite}/{result.size} "
            "non-finite pixels — refusing to write a broken stack"
        )

    save_frame(result, output_path)
    # V1.7-3 (AC-SCS-C1..C3): method im Log-Feld fuer Transparenz
    # (welche Stacking-Methode wurde tatsaechlich verwendet?).
    logger.info("stack.complete", output=str(output_path), frames=len(frames), is_3d=is_3d, method=method)


# Refactor: moved from processing_agent.py
def stack_2d(data: np.ndarray, method: str, normalization: str) -> np.ndarray:
    """Stack a 2D frame set (N, H, W) into (H, W)."""
    # Leo-Auftrag 2026-08-09 (Teil 3): NaN-Guard — Frames mit nicht-
    # finiten Werten oder Frame-Median == 0 werden ausgeschlossen
    # (Warning stack.non_finite_frame) statt still NaN in den Final-
    # Stack zu exportieren. Median == 0 wuerde bei normalization="mul"
    # durch 0 teilen (C20-Bug 2026-08-09: divide by zero -> 100 %-NaN-
    # Stack, generated/20260809-072146/C_20_final.fits).
    n_in = data.shape[0]
    keep = []
    for i in range(n_in):
        frame = data[i]
        frame_median = float(np.median(frame))
        if (not np.isfinite(frame_median)) or frame_median == 0.0 \
                or (not np.all(np.isfinite(frame))):
            logger.warning(
                "stack.non_finite_frame",
                frame_index=i,
                frames_total=n_in,
                median=(None if not np.isfinite(frame_median)
                        else round(frame_median, 6)),
            )
            continue
        keep.append(i)
    if len(keep) != n_in:
        data = data[keep]
    if data.shape[0] == 0:
        raise ValueError(
            "stack.non_finite: all frames excluded (non-finite values or "
            "zero median) — refusing to write a broken stack"
        )

    # Normalization
    if normalization == "mul":
        medians = np.median(data, axis=(1, 2))
        data = data / medians[:, np.newaxis, np.newaxis]
    elif normalization == "add":
        medians = np.median(data, axis=(1, 2))
        data = data - medians[:, np.newaxis, np.newaxis]

    # Stack method
    if method == "average":
        return np.mean(data, axis=0)
    elif method == "median":
        return np.median(data, axis=0)
    elif method == "winsorized":
        # Leo-Auftrag 2026-08-10 (Teil B2): Siril-Stil iteratives
        # Winsorized Sigma Clipping (ersetzt den frueheren Perzentil-
        # Clip 5/95 + Mean — stella Z. 62-63: "nicht nur
        # Perzentil-Clip"). Entfernt transiente Ausreisser
        # (Satelliten, Flugzeuge, einzelne Hotpixel).
        return winsorized_sigma_clip(data)
    elif method == "sigma_clipped_mean":
        # V1.7-3 SCS-A: 5. Zweig — Sigma-Clipped Mean (Verwerfen statt
        # Klemmen, Abgrenzung zu winsorized im Modul-Docstring). VOR dem
        # else-Fallback, damit AC-SCS-A6 (unbekannt -> average) unveraendert.
        return sigma_clipped_mean(data)
    elif method == "weighted":
        variances = np.var(data, axis=0)
        weights = 1.0 / (variances + 1e-10)
        return np.sum(data * weights, axis=0) / np.sum(weights, axis=0)
    else:
        return np.mean(data, axis=0)
