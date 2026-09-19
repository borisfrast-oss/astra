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


def stage_input(target_dir: Path, working_dir: Path, require_groups: bool = False, selected_groups: list[str] | None = None) -> Path:
    """Kopiert die konventionellen Input-Ordner nach `generated/<ts>/00_input`.

    ORG-X1 (V1.12-ORGANIZE): Lights-Handling jetzt exklusiv:
    - Gruppen vorhanden (lights/group_* exists) → NUR Gruppenordner nach 00_input/lights/group_*/ kopieren, Root-Frames werden IGNORIERT (Warning organize.pending_frames)
    - KEINE Gruppen + require_groups True → Hard-Stop Exit 2 process.no_groups + Hint "Run 'astra organize' first" (process, non-dry-run)
    - KEINE Gruppen + require_groups False → Legacy: flat lights kopieren (Backward-Compat für Tests/inspect/dry-run)
    - Fremde Unterordner in lights (z.B. siril) → Warning stage.input.skipped_subfolder, nicht kopieren (Exklusivitäts-Guard ORG-X1-Guard)
    - V1.12-GROUP-SELECT (GROUP-SEL-3): selected_groups Filter — nur gewählte Gruppen werden gestaged, andere ignoriert (ORG-X1 Interaction)
    - Weiterhin STAGED_INPUT_SUBDIRS exklusiv, kein rglob über Target

    Args:
        target_dir: Target-Root (z.B. C:\\Astra\\M3 Kugelsternhaufen).
        working_dir: `generated/<ts>` — Ziel fuer `00_input`.
        require_groups: Wenn True, Hard-Stop bei fehlenden Gruppen (process real run). False = Legacy flat copy (tests/inspect/dry-run).
        selected_groups: Wenn gesetzt, nur diese Gruppenordner stagen (GROUP-SELECT, ORG-X2 bereits aufgelöst).

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
    import click

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
        if sub == "lights":
            # ORG-X1 exklusiv + ORG-X1-Guard
            group_dirs = [d for d in src.iterdir() if d.is_dir() and d.name.lower().startswith("group_")]
            unexpected_dirs = [d for d in src.iterdir() if d.is_dir() and not d.name.lower().startswith("group_")]
            for ud in unexpected_dirs:
                try:
                    cnt = sum(1 for p in ud.rglob("*") if p.is_file() and p.suffix.lower() in FITS_SUFFIXES)
                except Exception:
                    cnt = 0
                logger.warning("stage.input.skipped_subfolder", subfolder=ud.name, files=cnt, target=str(target_dir))
            if group_dirs:
                # Gruppen vorhanden: nur Gruppenordner stagen
                # V1.12-GROUP-SELECT: wenn selected_groups gesetzt, nur diese stagen (ORG-X1 Interaction)
                if selected_groups is not None:
                    # Reuse ORG-X2 matching (exact/Prefix/Did-you-mean) via organize helper
                    # selected_groups kommt bereits aufgelöst aus CLI, aber direkter staging-Aufruf (Tests) may need resolution
                    try:
                        from .organize import resolve_group_selection as _resolve_groups
                        existing_names = [d.name for d in group_dirs]
                        canonical = _resolve_groups(list(selected_groups), existing_names)
                        # Map canonical → Path
                        name_to_path = {d.name: d for d in group_dirs}
                        # Also case-insensitive map for resolved lower? canonical sind exacte Namen
                        lower_map = {d.name.lower(): d for d in group_dirs}
                        filtered_dirs: list[Path] = []
                        for c in canonical:
                            if c in name_to_path:
                                filtered_dirs.append(name_to_path[c])
                            elif c.lower() in lower_map:
                                filtered_dirs.append(lower_map[c.lower()])
                        if filtered_dirs:
                            logger.info("stage.input.group_filtered", selected=list(selected_groups), filtered=[d.name for d in filtered_dirs], total_available=len(group_dirs))
                        else:
                            logger.warning("stage.input.group_filter_no_match", selected=list(selected_groups), available=existing_names)
                        group_dirs = filtered_dirs
                        logger.info(
                            "process.group_selection",
                            selected=[d.name for d in filtered_dirs],
                            existing=existing_names,
                            requested=list(selected_groups),
                        )
                    except ValueError as ve:
                        msg = str(ve)
                        # Hard-Stop mit Did-you-mean (GROUP-SEL-2) — auch via staging direkt
                        logger.error("process.group_not_found", error=msg, selected=list(selected_groups), available=[d.name for d in group_dirs])
                        raise click.UsageError(msg) from None
                root_fits = sum(1 for p in src.iterdir() if p.is_file() and p.suffix.lower() in FITS_SUFFIXES)
                if root_fits > 0:
                    msg = f"{root_fits} unsorted frames in lights\\ root will be skipped — run astra organize {target_dir.name} first"
                    logger.warning("organize.pending_frames", count=root_fits, target=str(target_dir))
                    try:
                        click.echo(f"Warning: {msg}", err=True)
                    except Exception:
                        pass
                dst.mkdir(parents=True, exist_ok=True)
                total = 0
                for gd in sorted(group_dirs):
                    dst_g = dst / gd.name
                    try:
                        shutil.copytree(gd, dst_g, dirs_exist_ok=True)
                        total += _count_fits(dst_g)
                    except Exception as e:
                        logger.warning("stage.input.copy_failed", group=gd.name, error=str(e))
                counts[sub] = total
                # Wenn durch GROUP-SELECT gefiltert und result leer → Discovery wird "No light frames" melden;
                # aber eigentlich ist Filter valide (nur gewählte Gruppen hatten keine FITS? Guard bereits in CLI).
                # Für Konsistenz: wenn selected_groups gesetzt und total==0, warnung
                if selected_groups is not None and total == 0 and group_dirs == []:
                    # Filter ergab keine Gruppen (CLI hätte bereits geprüft, aber race oder stale)
                    logger.warning("stage.input.group_selected_empty", selected=list(selected_groups), target=str(target_dir))
            else:
                # KEINE Gruppen
                has_any_fits = _count_fits(src) > 0
                if selected_groups is not None:
                    # GROUP-SELECT: Selektion verlangt Gruppen, aber keine existieren → Hard-Stop unabhängig von dry_run Exit 2
                    msg = f"process.no_groups: No group_* folders found in {src}. Run 'astra organize \"{target_dir}\" first."
                    logger.error("process.no_groups", target=str(target_dir), lights=str(src), hint="Run 'astra organize' first", selected=selected_groups)
                    raise click.UsageError(msg)
                if has_any_fits and require_groups:
                    msg = f"process.no_groups: No group_* folders found in {src}. Run 'astra organize \"{target_dir}\" first."
                    logger.error("process.no_groups", target=str(target_dir), lights=str(src), hint="Run 'astra organize' first")
                    raise click.ClickException(msg)
                elif has_any_fits:
                    # Legacy path for tests/dry-run/inspect: copy flat lights
                    logger.warning("stage.input.no_groups_legacy_copy", target=str(target_dir), hint="Run 'astra organize' first (legacy flat copy for tests/dry-run)")
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    # But still warn pending? For dry-run we already handle
                    # Remove group dirs from destination? They don't exist, so fine. But need to exclude unexpected subfolders?
                    # Our copytree copied everything including unexpected subfolders; need to remove them if they were copied?
                    for ud in unexpected_dirs:
                        copied_ud = dst / ud.name
                        if copied_ud.exists():
                            try:
                                shutil.rmtree(copied_ud)
                                logger.warning("stage.input.skipped_subfolder", subfolder=ud.name, files=0, target=str(target_dir))
                            except Exception:
                                pass
                    counts[sub] = _count_fits(dst)
                else:
                    # Keine Gruppen und keine FITS → wie bisher (Discovery wird melden)
                    logger.warning("stage.input.missing_lights", target=str(target_dir), source=str(src))
                    counts[sub] = 0
            continue
        # darks/flats/bias wie bisher
        if _count_fits(src) == 0:
            counts[sub] = 0
            continue
        shutil.copytree(src, dst, dirs_exist_ok=True)
        counts[sub] = _count_fits(dst)

    logger.info(
        "stage.input.complete",
        target=str(target_dir),
        source=str(target_dir),
        dest=str(input_dir),
        lights=counts.get("lights", 0),
        darks=counts.get("darks", 0),
        flats=counts.get("flats", 0),
        bias=counts.get("bias", 0),
    )
    return input_dir
