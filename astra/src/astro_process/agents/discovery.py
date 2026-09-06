"""Discovery Agent - Scans directory and builds ObservationContext."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from astro_process.config.models import AppConfig
from astro_process.core.equipment import resolve_equipment
from astro_process.core.fits_parser import (
    build_observation_context,
    parse_filename_metadata,
)
from astro_process.models.core import (
    FrameInfo,
    GroupInfo,
    ObservationContext,
    compute_group_hash,
)

logger = structlog.get_logger(__name__)


@dataclass
class DiscoveryResult:
    context: ObservationContext
    warnings: list[str] = None
    # V1.6-7: eq-Flag additiv auf Context-Ebene — lesend, kein Schema-Bruch.
    # Priority-Chain: EQMODE-Header → AZ-Fallback (≤60s) → unknown.
    # shotsInfo aus Pipeline entfernt (Dwarf-spezifisch, nicht geräteunabhängig).
    eq: Optional[bool] = None
    eq_source: str = "unknown"  # eqmode | az_fallback | unknown
    # V1.3-1 (RE-C): situationsabhaengige Empfehlung (additiv, nie steuernd).
    recommendation: Optional[dict] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class DiscoveryAgent:
    """Discovers and analyzes astrophotography data directories."""
    
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config
    
    def run(self, input_path: Path, shots_root: Path | None = None) -> DiscoveryResult:
        """Run discovery on the (gestagten) Input-Ordner.

        Punkt 3 (Input-Staging): Die Pipeline liest NUR aus
        `generated/<ts>/00_input` (input_path) — der Target-Root wird von
        Discovery nie mehr direkt gescannt.

        Args:
            input_path: `generated/<ts>/00_input` — Quelle fuer den Context.
            shots_root: Deprecated (V1.6-7). Wird ignoriert;shotsInfo.json
                ist kein Pipeline-Step mehr. Nur fuer Backward-Compat
                der Signatur beibehalten.

        Returns:
            DiscoveryResult mit ObservationContext (source_path=input_path).
        """
        logger.info("discovery.start", path=str(input_path))

        if not input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")

        if not input_path.is_dir():
            raise ValueError(f"Input path is not a directory: {input_path}")

        # V1.6-7: shotsInfo.json aus Pipeline entfernt (Dwarf-spezifisch).
        # Priority-Chain: EQMODE-Header → AZ-Fallback (≤60s) → unknown.
        # shotsInfo-Dateien bleiben lesbar (manuell/diagnostic via CLI inspect),
        # aber die Pipeline$infoert sich nicht mehr darauf.
        shots_eq = None  # Kein Pipeline-Call; shotsInfo ist legacy/diagnostic.

        # Build observation context (aus 00_input; Name-Fallback = Target-Root)
        context = build_observation_context(
            input_path,
            target_name=(shots_root.name if shots_root is not None else None),
            config_patterns=self.config.filename_patterns if self.config else None,
        )
        
        # Validate
        warnings = self._validate_context(context)
        
        # V1.6-1 (SSOT-A): Mandatory-Validation fuer Light-Frames.
        # Separater Schritt NACH parse_fits_header und build_observation_context.
        # Bei fehlenden Mandatory-Fields: Hard-Error (Pipeline-Abbruch).
        mandatory_warnings = self._validate_mandatory_fields(context)
        warnings.extend(mandatory_warnings)

        # V1.6-7 (Device-Independence): eq-Flag-Prioritaets-Kette ohne shotsInfo.
        # Chain: EQMODE-Header → AZ-Fallback (≤60s) → unknown.
        # Kein shotsInfo-Aufruf mehr — Dwarf-spezifisches Feature entfernt.
        eq, eq_source = self._resolve_eq(context)

        # V1.6-7: shotsInfo-Warnungen entfernt (nicht mehr Pipeline-relevant).
        # Bei unbekanntem Aufnahmemodus bleibt eine neutrale Info.
        if eq_source == "unknown":
            logger.info(
                "discovery.eqmode.unknown",
                target=str(input_path),
                msg=(
                    "Aufnahmemodus (AZ/EQ) unbekannt — kein EQMODE-Header, "
                    "Belichtung >60s oder keine Light-Frames."
                ),
            )

        # V1.7-4 (EQPT-A/B/C/D): Equipment-Aufloesung direkt nach der
        # Discovery, VOR Calibration/Processing. Prioritaets-Kette je Feld:
        # Header (Majority ueber alle Lights) > Config-Equipment-Profil
        # > None + Warning; Quellen landen in context.equipment.sources.
        equipment_report = resolve_equipment(context, self.config)
        warnings.extend(equipment_report.get("warnings", []))

        # V1.3-1 (RE-A/RE-G): situationsabhaengige Empfehlung — additiv,
        # nie steuernd (AC-RE-A2); nur bei Empfehlungs-Trigger loggen.
        # P2-4b (ray-Review): Mixed-Filter-Guard — bei >= 2 distincten
        # nicht-leeren FILTER-Werten unter den Lights ist ein einzelner
        # `_first_light_filter`-Wert irrefuehrend (Multi-Group/Mixed-
        # Session): Empfehlung suppressen + additives, informatives
        # Log-Event `discovery.recommendation_skipped` (reason
        # mixed_filters, gefundene Filter). Einheitliche Filter-Sessions
        # verhalten sich identisch zu vorher (Empfehlung bleibt).
        filters_found = _collect_light_filters(context)
        if len(filters_found) >= 2:
            logger.info(
                "discovery.recommendation_skipped",
                reason="mixed_filters",
                filters=filters_found,
                msg=(
                    "Mehrere distincte FILTER-Werte unter den Lights — "
                    "keine situationsabhaengige Empfehlung (Multi-Group)."
                ),
            )
            recommendation = None
        else:
            filter_name = filters_found[0] if filters_found else None
            recommendation = build_recommendation(
                filter_name=filter_name,
                eq=eq,
                eq_source=eq_source,
                astroalign_available=_astroalign_installed(),
            )
            if recommendation is not None:
                logger.info("discovery.recommendation", **recommendation)
        
        logger.info(
            "discovery.complete",
            target=context.target.name,
            lights=context.total_light_frames,
            darks=context.calibration.dark_count,
            flats=context.calibration.flat_count,
            bias=context.calibration.bias_count,
            integration_time=context.total_integration_time,
        )
        
        return DiscoveryResult(
            context=context,
            warnings=warnings,
            eq=eq,
            eq_source=eq_source,
            recommendation=recommendation,
        )
    
    def _resolve_eq(
        self, context: ObservationContext
    ) -> tuple[Optional[bool], str]:
        """Bestimmt das eq-Flag nach der Prioritaets-Kette (V1.6-7).

        V1.6-7 (Device-Independence): shotsInfo aus Pipeline entfernt.
        Neue Prioritaets-Kette:
          1. EQMODE-Header — 0 -> False (AZ), 1 -> True (EQ); best effort.
          2. AZ-Fallback-Regel (EQ-D): Belichtung <= 60s -> AZ.
             > 60s oder unbestimmbar -> unbekannt.
          3. unknown (kein EQMODE-Header, kein AZ-Fallback).

        Sammelt EQMODE/Belichtung aus den Light-Frames (erster Treffer je Feld)
        und ruft resolve_eq_flag.
        """
        eq_mode: Optional[int] = None
        exptime_sec: Optional[float] = None
        for f in context.get_lights().frames:
            if f.header is not None:
                if eq_mode is None and f.header.eq_mode is not None:
                    eq_mode = f.header.eq_mode
                if exptime_sec is None:
                    exptime_sec = _resolve_exptime_from_frame(f)
            if eq_mode is not None and exptime_sec is not None:
                break

        return resolve_eq_flag(eq_mode, exptime_sec)
    
    def _validate_context(self, context: ObservationContext) -> list[str]:
        warnings = []
        
        if context.total_light_frames == 0:
            warnings.append("No light frames found")
        
        if not context.calibration.dark_available:
            warnings.append("No dark frames - calibration will be limited")
        
        # CR-001 W4 (P4): Warnung nur wenn use_flats=true UND 0 Flats
        use_flats = self.config.use_flats if self.config else False
        if use_flats and not context.calibration.flat_available:
            warnings.append("No flat frames - vignetting correction not possible")
        elif not use_flats and not context.calibration.flat_available:
            # Keine Warnung bei Default (Teleskop (z.B. Dwarf3): keine Flats, Bias im Dark)
            pass
        
        # CR-001 W4 (P4): Warnung nur wenn use_bias=true UND 0 Bias
        use_bias = self.config.use_bias if self.config else False
        if use_bias and not context.calibration.bias_available:
            warnings.append("No bias frames - read noise calibration not possible")
        elif not use_bias and not context.calibration.bias_available:
            # Keine Warnung bei Default
            pass
        
        # Check for temperature mismatches
        lights = context.get_lights()
        darks = context.get_darks()
        if lights.frames and darks.frames:
            light_temps = [f.header.ccd_temp for f in lights.frames if f.header and f.header.ccd_temp is not None]
            dark_temps = [f.header.ccd_temp for f in darks.frames if f.header and f.header.ccd_temp is not None]
            if light_temps and dark_temps:
                avg_light = sum(light_temps) / len(light_temps)
                avg_dark = sum(dark_temps) / len(dark_temps)
                if abs(avg_light - avg_dark) > 5.0:
                    warnings.append(f"Temperature mismatch: lights avg {avg_light:.1f}°C, darks avg {avg_dark:.1f}°C")
        
        # Check exposure time consistency (deactivated for multi-group support)
        # light_exptimes = lights.group_by_exptime()
        # if len(light_exptimes) > 1:
        #     warnings.append(f"Multiple exposure times in lights: {list(light_exptimes.keys())}")
        
        return warnings
    
    def _validate_mandatory_fields(self, context: ObservationContext) -> list[str]:
        """V1.6-1 (SSOT-A): Mandatory-Validation fuer Light-Frames.

        Prueft, ob alle konfigurierten Mandatory-Fields im FITS-Header
        jedes Light-Frames vorhanden sind. Fehlende Mandatory-Fields
        fuehren zu einem Hard-Error (Pipeline-Abbruch, kein Filename-Fallback).
        Fehlende optionale Fields (filter, ra, dec) erzeugen eine Warning.

        Die Mandatory-Field-Liste kommt aus der Config (mandatory_fields),
        Default: [exptime, gain, object, ccd_temp] (Beschluss OQ-SSOT-1).

        Returns:
            Liste von Warning-Strings (fuer optionale Fields).
            Bei Hard-Errors wird ValueError geworfen (AC-SSOT-A2).
        """
        warnings = []
        if not context.total_light_frames:
            return warnings

        # Mandatory-Fields aus Config (Default: exptime, gain, object, ccd_temp)
        mandatory = ["exptime", "gain", "object", "ccd_temp"]
        if self.config and self.config.mandatory_fields:
            mandatory = self.config.mandatory_fields

        lights = context.get_lights()
        for frame in lights.frames:
            if frame.header is None:
                # Kein Header -> alle Mandatory-Fields fehlen -> Hard Error
                logger.error(
                    "discovery.light.missing_mandatory",
                    path=str(frame.path),
                    missing=mandatory,
                    msg=(
                        f"FITS-Header fehlt Pflichtfelder {', '.join(mandatory)}; "
                        "kein Filename-Fallback fuer Light-Frames"
                    ),
                )
                raise ValueError(
                    f"Light-Frame {frame.path.name}: FITS-Header fehlt "
                    f"Pflichtfelder {', '.join(mandatory)}; "
                    "kein Filename-Fallback fuer Light-Frames"
                )

            # Pflichtfelder pruefen (parse_fits_header hat Aliase bereits aufgeloest)
            missing_fields = []
            for field_name in mandatory:
                value = getattr(frame.header, field_name, None)
                if value is None:
                    missing_fields.append(field_name)

            # Optionale Felder (filter, ra, dec) — Warning, kein Abbruch
            optional_fields = ["filter_name", "ra", "dec"]
            optional_missing = []
            for field_name in optional_fields:
                value = getattr(frame.header, field_name, None)
                if value is None:
                    optional_missing.append(field_name)

            if missing_fields:
                logger.error(
                    "discovery.light.missing_mandatory",
                    path=str(frame.path),
                    missing=missing_fields,
                    msg=(
                        f"FITS-Header fehlt Pflichtfeld "
                        f"{', '.join(missing_fields)}; "
                        "kein Filename-Fallback fuer Light-Frames"
                    ),
                )
                raise ValueError(
                    f"Light-Frame {frame.path.name}: FITS-Header fehlt "
                    f"Pflichtfeld {', '.join(missing_fields)}; "
                    "kein Filename-Fallback fuer Light-Frames"
                )

            if optional_missing:
                logger.warning(
                    "discovery.light.missing_optional_field",
                    path=str(frame.path),
                    missing=optional_missing,
                )
                warnings.append(
                    f"Light-Frame {frame.path.name}: "
                    f"optionale Felder fehlen: {', '.join(optional_missing)}"
                )

        return warnings
    
    def discover_groups(self, context: ObservationContext) -> dict[str, GroupInfo]:
        """Discover groups of light frames by acquisition parameters.
        
        Groups lights by (EXPTIME, GAIN, FILTER) and returns GroupInfo
        for each distinct parameter combination.
        
        Args:
            context: The observation context to analyze
            
        Returns:
            Dict mapping group hash to GroupInfo
        """
        lights = context.get_lights()
        groups = lights.group_by_params()
        
        result: dict[str, GroupInfo] = {}
        for key, frameset in groups.items():
            exptime, gain, filter_name = key
            group_hash = compute_group_hash(float(exptime), int(gain), str(filter_name))
            total_exp = sum(
                f.header.exptime for f in frameset.frames
                if f.header and f.header.exptime
            )
            result[group_hash] = GroupInfo(
                key=key,
                hash=group_hash,
                frame_count=frameset.count,
                total_exposure=total_exp,
            )
        
        logger.info("discovery.groups", group_count=len(result),
                     groups=list(result.keys()))
        return result


def create_discovery_agent(config=None) -> DiscoveryAgent:
    """Factory function for DiscoveryAgent."""
    return DiscoveryAgent(config=config)


# ── shotsInfo.json (Dwarflab) — Legacy/Diagnostic (V1.6-7) ────────────────
# V1.6-7 (Device-Independence): shotsInfo.json ist ein Dwarf-spezifisches
# Feature und gehoert nicht in eine geräteunabhängige Pipeline.
# - find_shots_info() und log_shots_info() sind MANUELL nutzbar
#   (z.B. CLI inspect, Debugging), werden aber NICHT in der Pipeline aufgerufen.
# - Die Prioritaets-Kette (resolve_eq_flag) arbeitet nur mit EQMODE-Header
#   und AZ-Fallback;shotsInfo ist kein Quelle mehr.

SHOTS_INFO_FILENAME = "shotsInfo.json"

# V1.3-1 (RE-B/OQ-V1.3-2, Boris 2026-08-08): zentraler Vorschlagswert fuer
# die Rotationstoleranz in AZ-Situationen — 30° (UGC-10822-Beleg 43/43),
# NIE der SanityGuard-Default 2.0° (AC-RE-B1/B2).
MAX_ROTATION_SUGGESTION_DEG = 30.0

SHOTSINFO_MISSING_HINT = (
    "Keine shotsInfo.json gefunden; Aufnahmemodus (AZ/EQ) unbekannt — "
    "bei AZ-Aufnahmen ist Feldrotation möglich. Wird trotzdem bestmöglich "
    "verarbeitet."
)

SHOTSINFO_AZ_HINT = (
    "Aufnahmemodus AZ (eq=false): Feldrotation möglich — FFT-Korrelation "
    "kann dabei zuverlässig scheitern. astroalign-Registration wäre "
    "empfehlenswert (--registration-method astroalign "
    f"--max-rotation {MAX_ROTATION_SUGGESTION_DEG:.0f}). "
    "Keine automatische Umstellung."
)


def find_shots_info(target_path: Path) -> Path | None:
    """Sucht `shotsInfo.json` im Target-Root (MANUELL/DIAGNOSTIC, V1.6-7).

    V1.6-7: Nicht in der Pipeline aufrufen —shotsInfo ist ein
    Dwarf-spezifisches Feature, nicht geräteunabhängig.
    Nur nutzbar fuer CLI inspect und manuelle Diagnostik.

    Bevorzugt die Datei direkt im Root; toleriert die Kopie unter
    `_lights\\...\\shotsInfo.json` (rekursiver Treffer) ueber rglob.
    Liefert None, wenn keine gefunden wird.
    """
    direct = target_path / SHOTS_INFO_FILENAME
    if direct.is_file():
        return direct
    for p in sorted(target_path.rglob(SHOTS_INFO_FILENAME)):
        if p.is_file():
            return p
    return None


def log_shots_info(
    target_path: Path, *, warn_on_missing: bool = True
) -> Optional[bool]:
    """Sucht + parst `shotsInfo.json` und loggt die Session-Info (DIAGNOSTIC, V1.6-7).

    V1.6-7: Nicht in der Pipeline aufrufen —shotsInfo ist ein
    Dwarf-spezifisches Feature, nicht geräteunabhängig.
    Nur nutzbar fuer CLI inspect und manuelle Diagnostik.

    - gefunden: `discovery.shotsinfo.found` mit eq/exp/gain/shots_taken/
      shots_to_take/target (kein Pflichtfeld — nur Info).
      nicht gefunden UND ``warn_on_missing``: Warning
      `discovery.shotsinfo.missing`.
      unlesbar/ungueltig: Warning `discovery.shotsinfo.parse_failed`.
      optional: bei eq == false (AZ) Hinweis-Log `discovery.shotsinfo.az_hint`

    Returns:
        Optional[bool]: expliziter Aufnahmemodus aus shotsInfo.json
            (True=EQ, False=AZ) oder None bei fehlender/unlesbarer Datei
            bzw. fehlendem "eq"-Feld.
    """
    path = find_shots_info(target_path)
    if path is None:
        if warn_on_missing:
            logger.warning(
                "discovery.shotsinfo.missing",
                target=str(target_path),
                hint=SHOTSINFO_MISSING_HINT,
            )
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "discovery.shotsinfo.parse_failed",
            path=str(path),
            error=str(e),
        )
        return None

    eq = data.get("eq")
    logger.info(
        "discovery.shotsinfo.found",
        target=data.get("target"),
        eq=eq,
        exp=data.get("exp"),
        gain=data.get("gain"),
        shots_taken=data.get("shotsTaken"),
        shots_to_take=data.get("shotsToTake"),
        path=str(path),
    )

    # Optional (Auftrag): AZ-Hinweis auf astroalign — NUR Hinweis.
    if eq is False:
        logger.warning(
            "discovery.shotsinfo.az_hint",
            target=data.get("target"),
            hint=SHOTSINFO_AZ_HINT,
        )
    return eq


# ── V1.6-7 (Device-Independence): eq-Flag-Prioritaets-Kette ────────────


def _resolve_exptime_from_frame(frame: FrameInfo) -> Optional[float]:
    """Belichtungs-Precedence (AC-EQ-D5, ray-Review m3): Header-EXPTIME
    zuerst, Dateinamen-Parsing (`parse_filename_metadata`) als Fallback.
    Unbestimmbar -> None (AC-EQ-D4: kein AZ-Fallback, kein Crash)."""
    if frame.header is not None and frame.header.exptime is not None:
        return float(frame.header.exptime)
    meta = parse_filename_metadata(frame.path)
    if meta.get("exptime"):
        try:
            return float(meta["exptime"])
        except (TypeError, ValueError):
            return None
    return None


def resolve_eq_flag(
    eq_mode: Optional[int],
    exptime_sec: Optional[float],
) -> tuple[Optional[bool], str]:
    """Prioritaets-Kette fuer den Aufnahmemodus (V1.6-7, Device-Independence).

    V1.6-7: shotsInfo aus Pipeline entfernt. Neue Kette:
      1. EQMODE-Header — 0 -> False (AZ), 1 -> True (EQ); best effort.
      2. AZ-Fallback (EQ-D): Belichtung <= 60s -> AZ.
         > 60s oder unbestimmbar -> unbekannt.
      3. unknown (kein EQMODE-Header, kein AZ-Fallback).

    Returns:
        (eq, eq_source) mit eq_source in {eqmode, az_fallback, unknown}.
    """
    if eq_mode is not None:
        return eq_mode == 1, "eqmode"
    if exptime_sec is not None and exptime_sec <= 60.0:
        return False, "az_fallback"
    return None, "unknown"


# ── V1.3-1 (RE-A/RE-B/RE-G): situationsabhaengige Empfehlung ──────────


def _astroalign_installed() -> bool:
    """True wenn das astroalign-Extra installiert ist (RE-G, OQ-V1.3-3)."""
    try:
        import astroalign  # noqa: F401
    except ImportError:
        return False
    return True


def build_recommendation(
    filter_name: Optional[str],
    eq: Optional[bool],
    eq_source: str,
    astroalign_available: bool,
) -> Optional[dict]:
    """Situationsabhaengige Registrations-Empfehlung (RE-A, Situationstabelle).

    Total — alle 6 Kombinationen Filter-Klasse x eq-Flag definiert
    (Broadband = nicht-Duo-Band, Catch-all, ray-Review m7):
      1 Duo-Band + AZ      -> astroalign + --max-rotation 30
      2 Duo-Band + EQ      -> astroalign (Default-Rotation reicht)
      3 Duo-Band + unknown -> astroalign + --max-rotation 30 (AZ-Risiko)
      4 Broadband + EQ     -> keine Empfehlung (fft bleibt)
      5 Broadband + AZ     -> Hinweis Feldrotation + astroalign-Option
      6 Broadband + unknown -> keine Empfehlung (v1.2-Pfad bleibt)

    Nur Empfehlung (AC-RE-A2): nie steuernd, kein automatischer
    Methodenwechsel. RE-G (AC-RE-G1/G2/G3): die Empfehlung erscheint
    unabhaengig vom Installationsstand; fehlt das Extra, wird der
    CLI-Vorschlag um den Installations-Hinweis ergaenzt
    (analog registration.astroalign_unavailable).

    Returns:
        dict mit method/suggested_cli/reason/eq_source; `max_rotation_suggestion`
        NUR bei Empfehlungen mit `--max-rotation`-Vorschlag (Duo+AZ,
        Duo+unknown, Broadband+AZ; P2-4a) — oder None (keine
        Umstellungs-Empfehlung).
    """
    filter_lower = (filter_name or "").lower()
    # R9: Duo-Band-Erkennung ueber den bestehenden Substring-Matcher
    # (processing_agent.py Z. 811; deckt DEF-001-Semantik Duo-/Duo-Band ab).
    is_duo = "duo" in filter_lower or "dual" in filter_lower

    if eq is False:
        # Zeilen 1/5: AZ
        if is_duo:
            reason = (
                "Duo-Band + AZ (eq=false): Feldrotation möglich — "
                "SanityGuard-Default 2.0° kann AZ-Rotation blocken."
            )
        else:
            reason = (
                "AZ (eq=false): Feldrotation möglich — FFT-Korrelation "
                "kann zuverlässig scheitern."
            )
        method = "astroalign"
        suggested_cli = (
            f"--registration-method astroalign "
            f"--max-rotation {MAX_ROTATION_SUGGESTION_DEG:.0f}"
        )
    elif eq is True:
        if not is_duo:
            # Zeile 4: Broadband + EQ -> fft bleibt, keine Empfehlung
            return None
        # Zeile 2: Duo-Band + EQ — keine Feldrotation, Default-Rotation reicht
        method = "astroalign"
        suggested_cli = "--registration-method astroalign"
        reason = (
            "Duo-Band + EQ (eq=true): keine Feldrotation — astroalign "
            "mit SanityGuard-Default reicht."
        )
    else:
        if not is_duo:
            # Zeile 6: Broadband + unbekannt -> nicht raten, v1.2-Pfad bleibt
            return None
        # Zeile 3: Duo-Band + unbekannt — AZ-Risiko bleibt moeglich
        method = "astroalign"
        suggested_cli = (
            f"--registration-method astroalign "
            f"--max-rotation {MAX_ROTATION_SUGGESTION_DEG:.0f}"
        )
        reason = (
            "Duo-Band, Aufnahmemodus unbekannt: AZ-Feldrotation möglich — "
            "astroalign mit erhöhter Rotationstoleranz empfohlen."
        )

    recommendation = {
        "method": method,
        "suggested_cli": suggested_cli,
        "reason": reason,
        "eq_source": eq_source,
    }
    # P2-4a (ray-Review): `max_rotation_suggestion` NUR setzen, wenn die
    # Empfehlung tatsaechlich ein `--max-rotation` vorschlaegt (Zeilen
    # Duo+AZ, Duo+unbekannt, Broadband+AZ). Duo+EQ (suggested_cli ohne
    # --max-rotation) erhaelt das Feld NICHT — es waere irrefuehrend,
    # da dort die Default-Rotation reicht.
    if "--max-rotation" in suggested_cli:
        recommendation["max_rotation_suggestion"] = MAX_ROTATION_SUGGESTION_DEG
    if not astroalign_available:
        # RE-G (OQ-V1.3-3, Boris 2026-08-08): Empfehlung trotzdem ausgeben;
        # Installations-Hinweis ist Teil von suggested_cli/reason (AC-RE-G3).
        recommendation["suggested_cli"] = (
            f'{suggested_cli}  # fehlt: pip install "astra[astroalign]"'
        )
        recommendation["reason"] = (
            f'{reason} Installations-Hinweis: pip install "astra[astroalign]".'
        )
    return recommendation


def _first_light_filter(context: ObservationContext) -> Optional[str]:
    """Filter des ersten Light-Frames mit gesetztem FILTER-Wert (RE-A)."""
    for f in context.get_lights().frames:
        if f.header is not None and f.header.filter_name:
            return f.header.filter_name
    return None


def _collect_light_filters(context: ObservationContext) -> list[str]:
    """Distincte, nicht-leere FILTER-Werte unter den Lights (P2-4b).

    Reihenfolge = erstes Auftreten im Frame-Set. Ein einzelner Wert ist
    aequivalent zu `_first_light_filter`; >= 2 Werte bedeuten eine
    Mixed-Filter-/Multi-Group-Session, bei der ein einzelner
    Filter-Wert fuer die Empfehlungs-Logik irrefuehrend waere.
    """
    seen: list[str] = []
    for f in context.get_lights().frames:
        if f.header is not None and f.header.filter_name:
            value = f.header.filter_name
            if value not in seen:
                seen.append(value)
    return seen
