"""Cosmetic Correction — Bad-Pixel-Map + Interpolation (Leo-Auftrag 2026-08-10, Teil A).

Ziel (stella-Diagnose C20 `20260810-052954`): ε-Flecken im Stack sind
light-only Hot Pixels (zeitlich instabil, Dark aus anderer Session kennt
sie nicht; Median-Stacking entfernt sie nicht, weil sie in mehreren Frames
konstant heiss sind). Nur eine Bad-Pixel-Korrektur auf dem CFA (vor dem
Debayer) entfernt sie.

Algorithmus (Siril-Analogie ``find_cosme`` + ``cosme_cfa``, aber Map aus
den KALIBRIERTEN Lights statt aus dem Dark — die ε sind light-only):

1. **Detektion** (``detect_bad_pixels``): Ein Pixel ist defekt, wenn ueber
   N Frames (Default 3 von >= 8) sein Wert um die Schwelle (Default
   +50 DN) ueber der LOKALEN Umgebung liegt UND der Master-Dark dort
   normal ist (Dark < Dark-BG + 20). Die lokale Umgebung ist der Median
   der 8 Nachbarpixel DERSELBEN Bayer-Farbe in Distanz 2 (identisch zur
   Interpolations-Nachbarschaft — ein defektes Pixel in Kanal R wird nie
   gegen G/B-Nachbarn verglichen).
2. **Interpolation** (``interpolate_bad_pixels``): defekte Pixel werden
   durch den Median der Nachbarpixel derselben Bayer-Farbe (Distanz 2)
   ersetzt. Defekte Nachbarn werden dabei uebersprungen (nur valide
   Nachbarn fliessen in den Median) — bei Clustern bleibt die Umgebung
   unverschmutzt.

Bayer-Layout (RGGB, siehe ``core/debayer.BAYER_RGGB``):
    R = (0,0)  G1 = (0,1)  G2 = (1,0)  B = (1,1)
Ein Pixel (y, x) hat dieselbe Bayer-Farbe wie (y+dy, x+dx) genau dann,
wenn dy und dx beide gerade sind (paritaetserhaltend, Distanz 2).
"""
from __future__ import annotations

from typing import Iterable, Optional, Union

import numpy as np

# Nachbarschaft derselben Bayer-Farbe in Distanz 2 (8 Nachbarn):
# dy, dx ∈ {-2, 0, 2}² ohne (0, 0).
_SAME_COLOR_OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dy, dx)
    for dy in (-2, 0, 2)
    for dx in (-2, 0, 2)
    if not (dy == 0 and dx == 0)
)


def _pad(data: np.ndarray) -> np.ndarray:
    """Reflect-Pad um 2 Pixel (paritaetserhaltend an den Raendern).

    ``np.pad(mode="reflect")`` spiegelt Zeile 0 auf Pad-Position 2 und
    Zeile 2 auf Pad-Position 0 — ein Pixel am Rand (z.B. y=0) erreicht
    seinen same-color-Nachbarn y=2 ueber dy=-2 korrekt (kein Wrap-around
    wie bei ``np.roll``).
    """
    return np.pad(data, 2, mode="reflect")


def same_color_neighbor_median(data: np.ndarray) -> np.ndarray:
    """Median der 8 Nachbarpixel derselben Bayer-Farbe (Distanz 2).

    Liefert fuer jeden Pixel (y, x) den Median der Werte an
    (y+dy, x+dx) fuer alle (dy, dx) ∈ {-2, 0, 2}², ohne (0, 0). Das ist
    sowohl die Detektions-Referenz ("lokale Umgebung") als auch die
    Interpolations-Basis.

    Args:
        data: 2D-CFA-Array (H, W), float32.

    Returns:
        (H, W)-Array mit dem same-color-Nachbarmedian je Pixel.
    """
    data = np.asarray(data, dtype=np.float32)
    if data.ndim != 2:
        raise ValueError(f"expected 2D CFA array, got shape {data.shape}")
    padded = _pad(data)
    h, w = data.shape
    neighbors = []
    for dy, dx in _SAME_COLOR_OFFSETS:
        neighbors.append(
            padded[2 + dy: 2 + dy + h, 2 + dx: 2 + dx + w]
        )
    return np.median(np.stack(neighbors, axis=0), axis=0)


def detect_bad_pixels(
    frames: Union[np.ndarray, Iterable[np.ndarray]],
    master_dark: Optional[np.ndarray] = None,
    n_frames: int = 3,
    threshold: float = 50.0,
    dark_tolerance: float = 20.0,
) -> np.ndarray:
    """Bad-Pixel-Map aus kalibrierten Lights ableiten (CFA, vor dem Debayer).

    Ein Pixel ist defekt, wenn es in mindestens ``n_frames`` Frames um
    mehr als ``threshold`` ueber seinem same-color-Nachbarmedian
    (Distanz 2, ``same_color_neighbor_median``) liegt UND der
    Master-Dark dort normal ist (``dark < median(dark) + dark_tolerance``).

    Args:
        frames: 3D-Array (N, H, W) ODER Iterable von 2D-Arrays (H, W).
            Kalibrierte Light-Frames (CFA, vor Debayer).
        master_dark: Optionaler Master-Dark (H, W). Ist er None, wird die
            Dark-Bedingung uebersprungen (nur Light-Detektion) — der
            Aufrufer (Agent) loggt in dem Fall eine Warning.
        n_frames: Mindestanzahl Frames, in denen der Pixel heiss sein muss
            (Default 3 — stella-Vorgabe "3 von >= 8").
        threshold: Schwelle in DN ueber der lokalen Umgebung (Default 50).
        dark_tolerance: Toleranz fuer "Dark dort normal":
            ``dark < median(dark) + dark_tolerance`` (Default 20).

    Returns:
        Bool-Maske (H, W): True = defektes Pixel.
    """
    if n_frames < 1:
        raise ValueError(f"n_frames must be >= 1, got {n_frames}")
    if threshold <= 0:
        raise ValueError(f"threshold must be > 0, got {threshold}")

    counts: Optional[np.ndarray] = None
    shape: Optional[tuple[int, int]] = None

    if isinstance(frames, np.ndarray):
        if frames.ndim != 3:
            raise ValueError(
                f"expected 3D (N,H,W) array, got shape {frames.shape}"
            )
        count = _count_hot_frames(frames, threshold)
        counts, shape = count, frames.shape[1:]
    else:
        for frame in frames:
            frame = np.asarray(frame, dtype=np.float32)
            if shape is None:
                shape = frame.shape
            if frame.shape != shape:
                raise ValueError(
                    f"frame shape {frame.shape} != first frame shape {shape}"
                )
            # Achtung: np.bool_ + np.bool_ bleibt bool (OR) — deshalb
            # explizit int16 akkumulieren (Frames-Anzahl je Pixel).
            count = _hot_mask(frame, threshold).astype(np.int16)
            counts = count if counts is None else counts + count

    assert shape is not None and counts is not None
    mask = counts >= n_frames

    if master_dark is not None:
        dark = np.asarray(master_dark, dtype=np.float32)
        if dark.shape != shape:
            raise ValueError(
                f"master_dark shape {dark.shape} != frame shape {shape}"
            )
        dark_bg = float(np.median(dark))
        dark_normal = dark < (dark_bg + dark_tolerance)
        mask = mask & dark_normal

    return mask


def _hot_mask(frame: np.ndarray, threshold: float) -> np.ndarray:
    """Bool-Maske: Pixel ueber Schwelle ueber dem same-color-Nachbarmedian."""
    excess = frame - same_color_neighbor_median(frame)
    return excess > threshold


def _count_hot_frames(frames: np.ndarray, threshold: float) -> np.ndarray:
    """(H, W): Anzahl Frames, in denen der Pixel heiss ist (memory-schonend)."""
    counts = np.zeros(frames.shape[1:], dtype=np.int16)
    for i in range(frames.shape[0]):
        counts += _hot_mask(frames[i], threshold)
    return counts


def interpolate_bad_pixels(
    frame: np.ndarray,
    bad_mask: np.ndarray,
) -> np.ndarray:
    """Ersetzt defekte Pixel durch den Median der Nachbarpixel derselben
    Bayer-Farbe (Distanz 2). Nur defekte Pixel werden ersetzt.

    Defekte Nachbarn werden uebersprungen (nur valide Nachbarn fliessen
    in den Median). Sollten weniger als 2 valide Nachbarn existieren
    (dichtes Cluster), wird auf die volle Nachbarschaft zurueckgegriffen
    (best effort — kein unersetztes defektes Pixel).

    Args:
        frame: 2D-CFA-Array (H, W) — kalibriertes Light.
        bad_mask: Bool-Maske (H, W) aus ``detect_bad_pixels``.

    Returns:
        Kopie von ``frame`` mit ersetzten defekten Pixeln.
    """
    frame = np.asarray(frame, dtype=np.float32)
    bad_mask = np.asarray(bad_mask, dtype=bool)
    if frame.shape != bad_mask.shape:
        raise ValueError(
            f"frame shape {frame.shape} != bad_mask shape {bad_mask.shape}"
        )
    if not np.any(bad_mask):
        return frame.copy()

    out = frame.copy()
    padded = _pad(frame)
    padded_mask = _pad(bad_mask.astype(np.int16)).astype(bool)
    h, w = frame.shape
    ys, xs = np.nonzero(bad_mask)

    for y, x in zip(ys, xs):
        values: list[float] = []
        for dy, dx in _SAME_COLOR_OFFSETS:
            ny, nx = y + dy, x + dx
            # In gepolsterter Indizierung: Pixel (y,x) liegt bei (y+2, x+2).
            if not padded_mask[y + 2 + dy, x + 2 + dx]:
                values.append(float(padded[y + 2 + dy, x + 2 + dx]))
        if len(values) < 2:
            # Dichtes Cluster: alle 8 Nachbarn (auch defekte) verwenden —
            # best effort, kein unersetztes Pixel zuruecklassen.
            values = [
                float(padded[y + 2 + dy, x + 2 + dx])
                for dy, dx in _SAME_COLOR_OFFSETS
            ]
        out[y, x] = float(np.median(values))

    return out
