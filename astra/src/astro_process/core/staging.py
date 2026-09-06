"""Input-Staging: Pipeline liest NUR aus `generated/<ts>/00_input`.

Punkt 3 (Input-Staging): Der Target-Ordner wird ausschliesslich vom
Staging-Schritt gelesen (explizite konventionelle Input-Ordner), der Rest
des Targets (Siril-Dateien, App-Stacks, Thumbnail-Ordner, Exporte) ist fuer
die Pipeline komplett irrelevant.

Gewollte Konsequenz: `scan_directory` bleibt rekursiv — ungefaehrlich, weil
der 00_input-Ordner nur gewollte Dateien enthaelt (kein rglob/glob ueber das
Target).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Konventionelle Input-Ordner — die EINZIGEN Ordner, die gestagt werden.
# Explizite Pfade, KEIN rglob/glob("**/*.fit*") ueber das Target.
STAGED_INPUT_SUBDIRS = ("lights", "darks", "flats", "bias")

# FITS-Suffixe fuer die Anzahl-Zaehlung im stage.input.complete-Log.
FITS_SUFFIXES = (".fit", ".fits", ".fts")


def _count_fits(directory: Path) -> int:
    """Anzahl FITS-Dateien in einem Ordner inkl. Unterordnern.

    Wird sowohl auf dem Quell-Ordner (vor dem Kopieren, Leer-Check fuer
    darks/flats/bias) als auch auf dem gestagten Ziel-Ordner (Zaehlung
    fuer stage.input.complete) verwendet.
    """
    return sum(
        1
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in FITS_SUFFIXES
    )


def stage_input(target_dir: Path, working_dir: Path) -> Path:
    """Kopiert die konventionellen Input-Ordner nach `generated/<ts>/00_input`.

    Args:
        target_dir: Target-Root (z.B. C:\\Astra\\M3 Kugelsternhaufen).
        working_dir: `generated/<ts>` — Ziel fuer `00_input`.

    Returns:
        Pfad zu `generated/<ts>/00_input` (existiert immer nach dem Aufruf).

    Hinweis: Kopieren, nicht verschieben — Originale bleiben unangetastet.
    Fehlender lights-Ordner -> Warning `stage.input.missing_lights` (die
    Pipeline bricht danach wie bisher in Discovery mit "No light frames
    found" ab). Fehlende darks/flats/bias-Ordner -> Warning, Rest laeuft
    weiter.
    Leere darks/flats/bias-Ordner (0 FITS) -> still uebersprungen (kein
    Warning, kein Kopieren); lights wird IMMER kopiert, wenn der Ordner
    existiert (Abbruch "No light frames found" passiert in Discovery).
    """
    input_dir = working_dir / "00_input"
    input_dir.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for sub in STAGED_INPUT_SUBDIRS:
        src = target_dir / sub
        dst = input_dir / sub
        if not src.is_dir():
            logger.warning(
                f"stage.input.missing_{sub}",
                target=str(target_dir),
                source=str(src),
            )
            counts[sub] = 0
            continue
        # Leere darks/flats/bias-Ordner (0 FITS) -> nicht stagen (kein
        # Warning, kein Kopieren). lights ist der Sonderfall: existiert der
        # Ordner, wird er IMMER kopiert — der Abbruch "No light frames
        # found" passiert wie bisher in Discovery.
        if sub != "lights" and _count_fits(src) == 0:
            counts[sub] = 0
            continue
        shutil.copytree(src, dst, dirs_exist_ok=True)
        counts[sub] = _count_fits(dst)

    logger.info(
        "stage.input.complete",
        target=str(target_dir),
        source=str(target_dir),
        dest=str(input_dir),
        lights=counts["lights"],
        darks=counts["darks"],
        flats=counts["flats"],
        bias=counts["bias"],
    )
    return input_dir
