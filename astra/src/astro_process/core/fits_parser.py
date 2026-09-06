"""FITS header parser with robust alias handling and filename-based metadata extraction."""

from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from datetime import datetime
import re
from astropy.io import fits
import numpy as np
import structlog

if TYPE_CHECKING:
    from ..config.models import FilenamePatterns

from ..models.core import (
    FitsHeader, FrameInfo, FrameType, FrameSet, TargetType, compute_group_hash,
)

logger = structlog.get_logger(__name__)


# V1.3-6 (H3/AC-EQ-A1): zentrale EQMODE-Quelle — Export
# (EXPORT_LIGHT_HEADER_KEYS in core/export.py) und Discovery
# (HEADER_ALIASES/eq_mode-Parsing) referenzieren dieselbe Konstante,
# keine zweite unabhaengige Definition (sonst divergieren zwei Wahrheiten).
EQMODE_KEY = "EQMODE"

# Header key aliases (standard -> list of possible FITS keys)
# FITS header keys vary by manufacturer (ZWO, QHY, Canon, Nikon, DwarfLab).
# These aliases ensure compatibility across devices. See DADR-002.
HEADER_ALIASES = {
    "object": ["OBJECT", "OBJNAME", "TARGET"],
    "exptime": ["EXPTIME", "EXPOSURE", "ELAPSED", "ELAPSEDTIME"],
    "gain": ["GAIN", "EGAIN", "CCDGAIN"],
    "offset": ["OFFSET", "BIAS", "CCDOFFSET", "PEDESTAL"],
    "ccd_temp": ["CCD-TEMP", "TEMPERAT", "TEMP", "CCD_TEMP", "SET-TEMP", "CCDTEMP", "DET-TEMP"],
    "filter_name": ["FILTER", "FILTNAM", "FILTER1", "FILTNAM1"],
    "xbinning": ["XBINNING", "BINX", "XBIN"],
    "ybinning": ["YBINNING", "BINY", "YBIN"],
    "date_obs": ["DATE-OBS", "DATE_OBS", "DATEOBS", "OBSDATE"],
    "telescope": ["TELESCOP", "TELESCOPE"],
    "instrument": ["INSTRUME", "CAMERA", "INSTRUMENT"],
    "focal_length": ["FOCALLEN", "FOCALLENGTH", "FL"],
    "aperture": ["APERTURE", "APTDIA", "DIAMETER"],
    "pixel_size_x": ["XPIXSZ", "PIXSIZE1", "PIXSIZEX"],
    "pixel_size_y": ["YPIXSZ", "PIXSIZE2", "PIXSIZEY"],
    "site_lat": ["SITELAT", "OBSLAT", "LATITUDE"],
    "site_lon": ["SITELONG", "OBSLONG", "LONGITUDE"],
    "site_elev": ["SITEELEV", "OBSELEV", "ELEVATION", "ALTITUDE"],
    "ra": ["RA", "OBJCTRA", "CRVAL1"],
    "dec": ["DEC", "OBJCTDEC", "CRVAL2"],
    "eq_mode": [EQMODE_KEY],
}


def normalize_value(value: any, target_type: type) -> any:
    """Normalize FITS header value to target type."""
    if value is None:
        return None
    
    # Handle astropy Quantity
    if hasattr(value, "value"):
        value = value.value
    
    # Strip units from strings
    if isinstance(value, str):
        value = value.strip()
        # DEF-003 (Fix): Einheiten-Suffixe NUR bei numerischen Zieltypen
        # strippen. Der Regex entfernt sonst als "Einheit" interpretierte
        # Bestandteile aus String-Werten ("Duo-Band" -> "Duo-", "Astro" -> ""),
        # wodurch compute_group_hash/_collect_light_filters verfaelschte
        # Filterwerte sahen (Gruppenname 120s40_Duo- statt 120s40_Duo-Band).
        # String-Zieltypen (filter_name, OBJECT, ...) bleiben unangetastet;
        # numerische Werte mit Einheiten-Suffix ("30s", "-5C") werden weiterhin
        # korrekt konvertiert.
        if target_type in (float, int):
            value = re.sub(r'\s*[a-zA-Z/]+$', '', value)
    
    try:
        if target_type == float:
            return float(value)
        elif target_type == int:
            return int(float(value))
        elif target_type == datetime:
            if isinstance(value, str):
                # Try common datetime formats
                for fmt in [
                    "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y/%m/%d %H:%M:%S",
                ]:
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
            return None
        return value
    except (ValueError, TypeError):
        return None


def get_header_value(header: fits.Header, aliases: list[str], target_type: type = str) -> any:
    """Get value from header trying multiple alias keys."""
    for alias in aliases:
        if alias in header:
            return normalize_value(header[alias], target_type)
    return None


# Filename patterns for metadata extraction
FILENAME_PATTERNS = {
    # dark_exp_15.000000_gain_60_bin_1_26C_stack_1.fits
    "dark": re.compile(
        r'(?:dark|bias|flat|offset)'
        r'(?:_exp)?_?(?P<exptime>[\d.]+)'
        r'(?:s|sec)?'
        r'(?:_gain[_\-]?)(?P<gain>\d+)'
        r'(?:_bin[_\-]?)(?P<binning>\d+)'
        r'(?:_(?P<temp>-?\d+)C)?'
        r'(?:_stack[_\-]?)(?P<stack>\d+)',
        re.IGNORECASE
    ),
    # NOTE: dark_dwarf3 pattern exists because DwarfLab firmware does not
    # write FITS headers for dark/bias/flat frames. This is a known firmware
    # bug. See: decisions-astro.md DADR-002, plan.md V1.6-8.
    # Teleskop (z.B. Dwarf3/M13)-Schema: dark_15s_60g_30C_1.fits (Header oft leer —
    # Metadaten werden NUR aus dem Dateinamen gewonnen)
    "dark_dwarf3": re.compile(
        r'(?:dark|bias|flat|offset)'
        r'(?:_exp)?_?(?P<exptime>[\d.]+)'
        r'(?:s|sec)?'
        r'(?:_|-)(?P<gain>\d+)g'
        r'(?:_|-)(?P<temp>-?\d+)C'
        r'(?:_(?P<stack>\d+))?',
        re.IGNORECASE
    ),
    # Kompaktes {n}s{gain}-Schema: Dark_30s40.fits (C20-Dump, header-los —
    # kein _gain-/-g-Trenner, kein Temp im Namen). Bewusst NACH
    # dark/dark_dwarf3 pruefen: die liefern mehr Metadaten, und
    # dark_15s_60g_30C_1.fits darf hier NICHT landen (wuerde temp/stack
    # verlieren). Der dark|bias|flat|offset-Praefix verhindert Kollision
    # mit {name}s{name}-Licht-Dateinamen.
    "dark_compact": re.compile(
        r'(?:dark|bias|flat|offset)'
        r'(?:_exp)?_?(?P<exptime>[\d.]+)s'
        r'(?P<gain>\d+)',
        re.IGNORECASE
    ),
    # HD 182761_15s60_Astro_20260717-231509939_33C.fits
    "light": re.compile(
        r'(?P<target>.+?)'
        r'(?:_|-)(?P<exptime>[\d.]+)s'
        r'(?:_|-)?(?P<gain>\d+)'
        r'(?:_|-)(?P<filter>Astro|Duo-Band)'
        r'(?:_|-)(?P<date>\d{8})[-_]?(?P<time>\d{6,})?'
        r'(?:_|-)(?P<temp>-?\d+)C',
        re.IGNORECASE
    ),
    # Generic: any numbers in filename
    "generic": re.compile(
        r'(?:_|-)(?P<exptime>[\d.]+)s?'
        r'(?:_|-)(?P<gain>\d+)'
        r'(?:_|-)(?P<binning>\d+)'
        r'(?:_|-)(?P<temp>-?\d+)C',
        re.IGNORECASE
    ),
}


# V1.6-1 (SSOT-C): Reihenfolge der Filename-Patterns (deterministisch).
# Light zuerst (häufigster Case), dann Calibration-Patterns absteigend
# nach Spezifität (dark → dark_dwarf3 → dark_compact → generic).
_PATTERN_ORDER = ["light", "dark", "dark_dwarf3", "dark_compact", "generic"]


def _build_effective_patterns(
    config_patterns: FilenamePatterns | None = None,
) -> dict[str, re.Pattern]:
    """Baue effektive Patterns: Config-Overrides > hardcoded Defaults (AC-SSOT-C4).

    Wenn config_patterns=None oder einzelne Felder None sind, werden die
    hardcoded Defaults aus FILENAME_PATTERNS verwendet.
    """
    if config_patterns is None:
        return dict(FILENAME_PATTERNS)

    effective = dict(FILENAME_PATTERNS)  # Defaults Kopie
    for key in _PATTERN_ORDER:
        cfg_pattern = getattr(config_patterns, key, None)
        if cfg_pattern is not None:
            effective[key] = re.compile(cfg_pattern.regex, re.IGNORECASE)
    return effective


def parse_filename_metadata(
    filepath: Path,
    config_patterns: FilenamePatterns | None = None,
) -> dict:
    """Extract metadata from filename when FITS header is incomplete.

    V1.6-1 (SSOT-C): Akzeptiert optionale config_patterns (FilenamePatterns
    aus AppConfig). Wenn gesetzt, werden die Config-Patterns statt der
    hardcoded Defaults verwendet (Precedence: Config > Defaults, AC-SSOT-C4).
    """
    name = filepath.stem  # filename without extension
    patterns = _build_effective_patterns(config_patterns)

    # Patterns in definierter Reihenfolge ausprobieren
    for key in _PATTERN_ORDER:
        if key not in patterns:
            continue
        match = patterns[key].search(name)
        if match:
            return match.groupdict()

    return {}


def parse_fits_header(filepath: Path) -> FitsHeader:
    """Parse FITS file header into standardized FitsHeader model."""
    with fits.open(filepath, memmap=False) as hdul:
        header = hdul[0].header
        # header.cards is list of (key, value, comment) tuples
        raw_cards = {card[0]: card[1] for card in header.cards if card[0]}
        
        # Extract standard fields using aliases
        obj = get_header_value(header, HEADER_ALIASES["object"])
        exptime = get_header_value(header, HEADER_ALIASES["exptime"], float)
        gain = get_header_value(header, HEADER_ALIASES["gain"], int)
        offset = get_header_value(header, HEADER_ALIASES["offset"], int)
        ccd_temp = get_header_value(header, HEADER_ALIASES["ccd_temp"], float)
        filter_name = get_header_value(header, HEADER_ALIASES["filter_name"])
        xbinning = get_header_value(header, HEADER_ALIASES["xbinning"], int) or 1
        ybinning = get_header_value(header, HEADER_ALIASES["ybinning"], int) or 1
        date_obs = get_header_value(header, HEADER_ALIASES["date_obs"], datetime)
        
        telescope = get_header_value(header, HEADER_ALIASES["telescope"])
        instrument = get_header_value(header, HEADER_ALIASES["instrument"])
        focal_length = get_header_value(header, HEADER_ALIASES["focal_length"], float)
        aperture = get_header_value(header, HEADER_ALIASES["aperture"], float)
        pixel_size_x = get_header_value(header, HEADER_ALIASES["pixel_size_x"], float)
        pixel_size_y = get_header_value(header, HEADER_ALIASES["pixel_size_y"], float)
        site_lat = get_header_value(header, HEADER_ALIASES["site_lat"], float)
        site_lon = get_header_value(header, HEADER_ALIASES["site_lon"], float)
        site_elev = get_header_value(header, HEADER_ALIASES["site_elev"], float)
        ra = get_header_value(header, HEADER_ALIASES["ra"], float)
        dec = get_header_value(header, HEADER_ALIASES["dec"], float)
        # V1.3-6 (EQ-B): EQMODE aus dem Light-Header — best effort
        # (AC-EQ-B2): fehlend/unlesbar -> None, nie ein Crash.
        # Das Mapping 0->AZ / 1->EQ passiert in resolve_eq_flag
        # (discovery.py); hier wird nur der Rohwert normalisiert (0/1/None).
        eq_mode_raw = get_header_value(header, HEADER_ALIASES["eq_mode"], int)
        eq_mode = 1 if eq_mode_raw == 1 else 0 if eq_mode_raw == 0 else None

        # V1.6-1 (SSOT-A): Filename-Fallback wird NICHT mehr in parse_fits_header
        # angewendet. Fuer Light-Frames gilt FITS-Header als SSOT (Mandatory-
        # Validation separat in DiscoveryAgent._validate_mandatory_fields).
        # Fuer Calibration-Frames wird apply_filename_fallback() nach dem
        # parse_fits_header() aufgerufen (in scan_directory).
        
        return FitsHeader(
            object=obj,
            exptime=exptime,
            gain=gain,
            offset=offset,
            ccd_temp=ccd_temp,
            filter_name=filter_name,
            xbinning=xbinning,
            ybinning=ybinning,
            date_obs=date_obs,
            telescope=telescope,
            instrument=instrument,
            focal_length=focal_length,
            aperture=aperture,
            pixel_size_x=pixel_size_x,
            pixel_size_y=pixel_size_y,
            site_lat=site_lat,
            site_lon=site_lon,
            site_elev=site_elev,
            ra=ra,
            dec=dec,
            eq_mode=eq_mode,
            raw_cards=raw_cards,
        )


def apply_filename_fallback(
    filepath: Path,
    header: FitsHeader,
    config_patterns: FilenamePatterns | None = None,
) -> FitsHeader:
    """V1.6-1 (SSOT-B): Filename-Fallback nur fuer Calibration-Frames.

    Bei Dark/Flat/Bias mit leerem FITS-Header (DwarfLab Firmware-Bug) werden
    Metadaten aus dem Dateinamen extrahiert. Fuer Light-Frames ist dieser
    Aufruf NICHT vorgesehen (SSOT: FITS-Header = einzige Quelle).

    Args:
        filepath: Pfad zur FITS-Datei
        header: Bestehender FitsHeader (evtl. mit None-Werten)
        config_patterns: Optional FilenamePatterns aus AppConfig (AC-SSOT-C3).
            Wenn None, werden hardcoded Defaults verwendet (AC-SSOT-C4).

    Returns:
        Aktualisierter FitsHeader mit Filename-Fallback-Werten (wo moeglich).
    """
    # Nur anwenden, wenn mindestens ein Mandatory-Feld fehlt
    if (header.object is not None and header.exptime is not None
            and header.gain is not None and header.ccd_temp is not None):
        return header

    filename_meta = parse_filename_metadata(filepath, config_patterns)
    if not filename_meta:
        return header

    # Aktualisiere nur None-Werte mit Filename-Metadaten
    if header.object is None and filename_meta.get("target"):
        header = header.model_copy(update={"object": filename_meta["target"]})
    if header.exptime is None and filename_meta.get("exptime"):
        header = header.model_copy(update={
            "exptime": float(filename_meta["exptime"])
        })
    if header.gain is None and filename_meta.get("gain"):
        header = header.model_copy(update={
            "gain": int(filename_meta["gain"])
        })
    if header.ccd_temp is None and filename_meta.get("temp"):
        header = header.model_copy(update={
            "ccd_temp": float(filename_meta["temp"])
        })
    if header.filter_name is None and filename_meta.get("filter"):
        header = header.model_copy(update={
            "filter_name": filename_meta["filter"]
        })
    if header.xbinning == 1 and filename_meta.get("binning"):
        binning = int(filename_meta["binning"])
        header = header.model_copy(update={
            "xbinning": binning,
            "ybinning": binning,
        })

    logger.info(
        "discovery.calibration.filename_fallback",
        path=str(filepath),
        source="filename",
        meta_keys=list(filename_meta.keys()),
    )
    return header


def detect_frame_type(filepath: Path, header: Optional[FitsHeader] = None) -> FrameType:
    """Detect frame type from filename or header."""
    name = filepath.name.lower()
    
    if "dark" in name and "flat" in name:
        return FrameType.DARK_FLAT
    elif "dark" in name:
        return FrameType.DARK
    elif "flat" in name:
        return FrameType.FLAT
    elif "bias" in name or "offset" in name:
        return FrameType.BIAS
    elif "light" in name or "obj" in name or "image" in name:
        return FrameType.LIGHT
    
    # Fallback to header OBJECT key
    if header and header.object:
        obj = header.object.lower()
        if "dark" in obj:
            return FrameType.DARK
        elif "flat" in obj:
            return FrameType.FLAT
        elif "bias" in obj or "offset" in obj:
            return FrameType.BIAS
    
    # Default to light
    return FrameType.LIGHT


# Output + working subdirectories to skip during scanning
# Numbered phases enable natural file-explorer sorting + backwards compat
# GR-03 (QG4-Close): `_siril` = Fremd-Arbeitsordner (Siril-Produkte wie
# *_stacked.fit/_GraXpert) — kein Pipeline-Scan-Input (S1-A12-Annahme
# widerlegt: rekursiver Glob zaehlte sie als Light/Dark).
OUTPUT_SUBDIRS = {
    "masters", "00_masters",
    # V1.3-Batch (Input-Struktur-Konsolidierung, 2026-08-10): Master-Darks
    # liegen jetzt unter 00_input/master — Singular ergaenzen, damit der
    # Discovery-Scan sie nicht als Darks interpretiert.
    # "masters"/"00_masters" bleiben fuer alte Struktur (Backward-Compat).
    "master",
    "calibrated", "01_calibrated",
    "debayered", "02_debayered",
    "registered", "03_registered",
    "stacked", "04_stacked",
    "generated", "00_input",
    "_siril",
}


def _extract_target_name(dirname: str) -> str:
    """Extract short target name from directory name (e.g. 'HD 182761' from 'HD 182761 A-Typ...')."""
    # Match first meaningful token group: letters, numbers, spaces, dots, hyphens
    m = re.match(r'^([A-Za-z0-9][A-Za-z0-9 ._-]*)', dirname)
    if m:
        name = m.group(1).strip().rstrip('.-_ ')
        return name if name else dirname
    return dirname


def scan_directory(
    root: Path,
    recursive: bool = True,
    config_patterns: FilenamePatterns | None = None,
) -> dict[FrameType, FrameSet]:
    """Scan directory for FITS files and categorize them.

    Args:
        root: Root directory to scan
        recursive: Scan subdirectories recursively
        config_patterns: Optional FilenamePatterns from AppConfig (AC-SSOT-C3).
            When None, hardcoded defaults are used (AC-SSOT-C4).
    """
    pattern = "**/*.fit*" if recursive else "*.fit*"  # matches .fit, .fits, .fts
    frame_sets = {ft: FrameSet(frame_type=ft) for ft in FrameType}
    
    index = 0
    # T5 (E1): Gruppe eines Light-Frames, dessen Header unlesbar ist, wird
    # aus dem Dateinamen abgeleitet (parse_filename_metadata). Schlaegt der
    # Scan fuer ALLE Lights einer Gruppe fehl -> discovery.group_empty
    # (kein Crash; Gruppe taucht im Context schlicht nicht auf).
    failed_light_groups: dict[str, int] = {}
    successful_light_groups: set[str] = set()
    
    for filepath in sorted(root.glob(pattern)):
        if not filepath.is_file():
            continue
        # Skip files in pipeline output subdirectories
        if any(part in OUTPUT_SUBDIRS for part in filepath.relative_to(root).parts[:-1]):
            continue
        # Skip final output files, stretched display variants and agent-log
        # V1.8-3: _stretched.fits ist ein reiner Display-Output und darf nie
        # als Input fuer wissenschaftliche Steps (Platesolve/PCC) entdeckt werden.
        if "_final." in filepath.name or "_stretched." in filepath.name or filepath.name == "agent-log.yaml":
            continue
        if filepath.suffix.lower() not in (".fit", ".fits", ".fts"):
            continue
        
        try:
            header = parse_fits_header(filepath)
            frame_type = detect_frame_type(filepath, header)
            
            # V1.6-1 (SSOT-B): Filename-Fallback NUR fuer Calibration-Frames.
            # Light-Frames nutzen FITS-Header als SSOT (Mandatory-Validation
            # separat in DiscoveryAgent._validate_mandatory_fields).
            if frame_type in (FrameType.DARK, FrameType.FLAT, FrameType.BIAS, FrameType.DARK_FLAT):
                header = apply_filename_fallback(filepath, header, config_patterns)
                # V1.6-1 (AC-SSOT-B2): Calibration-Frames brauchen exptime + gain
                # fuer die Kalibrierung. Weder FITS-Header noch Filename liefert
                # gueltige Metadaten -> Hard-Error (kein stilles Durchlaufen
                # mit None-Werten durch die Kalibrierung).
                if header.exptime is None or header.gain is None:
                    missing = []
                    if header.exptime is None:
                        missing.append("exptime")
                    if header.gain is None:
                        missing.append("gain")
                    raise ValueError(
                        f"Kalibrationsframe {filepath.name}: weder FITS-Header "
                        f"noch Filename liefern gueltige Metadaten "
                        f"(fehlend: {', '.join(missing)}). "
                        f"AC-SSOT-B2: Abbruch."
                    )
            
            # Get image dimensions
            with fits.open(filepath, memmap=False) as hdul:
                data = hdul[0].data
                if data is not None:
                    height, width = data.shape[-2:]
                else:
                    height, width = 0, 0
            
            frame_info = FrameInfo(
                path=filepath,
                frame_type=frame_type,
                header=header,
                index=index,
                size_bytes=filepath.stat().st_size,
                width=width,
                height=height,
            )
            
            frame_sets[frame_type].frames.append(frame_info)
            index += 1
            
            # T5: Gruppe eines erfolgreich gelesenen Light-Frames merken
            if frame_type == FrameType.LIGHT:
                exptime = header.exptime if header.exptime is not None else 0.0
                gain = header.gain if header.gain is not None else 0
                filter_name = header.filter_name if header.filter_name else "none"
                successful_light_groups.add(
                    compute_group_hash(float(exptime), int(gain), str(filter_name))
                )
            
        except Exception as e:
            # T5 (E1): Kein stiller Fehler — structlog-Warning mit Kontext
            # (ersetzt das fruehere print(...) im selben except-Zweig).
            logger.warning("discovery.frame_skip", path=str(filepath), reason=str(e))
            # Gruppe aus dem Dateinamen ableiten, wenn der Header unlesbar ist
            if detect_frame_type(filepath) == FrameType.LIGHT:
                meta = parse_filename_metadata(filepath, config_patterns)
                if meta.get("exptime") and meta.get("gain"):
                    try:
                        gh = compute_group_hash(
                            float(meta["exptime"]), int(float(meta["gain"])), "none"
                        )
                    except (ValueError, TypeError):
                        gh = None
                    if gh:
                        failed_light_groups[gh] = failed_light_groups.get(gh, 0) + 1
            continue
    
    # T5 (E1): ALLE Lights einer Gruppe unlesbar -> error (Gruppe = skipped)
    for group_hash, failed in sorted(failed_light_groups.items()):
        if group_hash not in successful_light_groups:
            logger.error(
                "discovery.group_empty",
                group=group_hash,
                failed=failed,
                path=str(root),
            )
    
    return frame_sets


def build_observation_context(
    source_path: Path,
    target_name: Optional[str] = None,
    config_patterns: FilenamePatterns | None = None,
) -> "ObservationContext":
    """Build complete ObservationContext from directory scan.

    Args:
        source_path: Wurzelordner fuer den Scan. Pipeline (Punkt 3): das
            gestagte `generated/<ts>/00_input` — nicht der Target-Root.
        target_name: Optionaler Anzeige-Name des Targets. Nur Fallback, wenn
            der FITS-Header kein OBJECT liefert (bei Staging ist
            `00_input` kein brauchbarer Name, daher liefert der Caller den
            Target-Root-Namen).
        config_patterns: Optional FilenamePatterns from AppConfig (AC-SSOT-C3).
    """
    from ..models.core import ObservationContext, ObservationTarget, EquipmentInfo, AcquisitionInfo, CalibrationStatus
    
    frame_sets = scan_directory(source_path, config_patterns=config_patterns)
    lights = frame_sets[FrameType.LIGHT]
    darks = frame_sets[FrameType.DARK]
    flats = frame_sets[FrameType.FLAT]
    bias = frame_sets[FrameType.BIAS]
    dark_flats = frame_sets[FrameType.DARK_FLAT]
    
    # Determine target from first light frame
    first_light = lights.frames[0] if lights.frames else None
    if target_name is None:
        target_name = source_path.name
    if first_light and first_light.header and first_light.header.object:
        target_name = first_light.header.object
    else:
        target_name = _extract_target_name(target_name)
    
    # Infer target type from name
    target_type = TargetType.UNKNOWN
    name_lower = target_name.lower()
    if any(x in name_lower for x in ["m31", "m51", "m101", "ngc", "galaxy"]):
        target_type = TargetType.GALAXY
    elif any(x in name_lower for x in ["m42", "ngc6960", "ic1396", "nebula", "sh2-"]):
        target_type = TargetType.NEBULA
    elif any(x in name_lower for x in ["hd", "hip", "star", "arcturus", "vega"]):
        target_type = TargetType.STAR
    
    # Equipment from first frame header
    first_header = first_light.header if first_light else None
    equipment = EquipmentInfo(
        telescope=first_header.telescope if first_header else None,
        aperture_mm=int(first_header.aperture) if first_header and first_header.aperture else None,
        focal_length_mm=int(first_header.focal_length) if first_header and first_header.focal_length else None,
        camera=first_header.instrument if first_header else None,
        pixel_size_um=first_header.pixel_size_x if first_header else None,
        filters=list(lights.group_by_filter().keys()),
    )
    
    # Acquisition info
    acquisition = AcquisitionInfo(
        date=first_header.date_obs if first_header else None,
        gain=first_header.gain if first_header else None,
        offset=first_header.offset if first_header else None,
        temperature_c=first_header.ccd_temp if first_header else None,
        total_integration_time=sum(
            f.header.exptime for f in lights.frames 
            if f.header and f.header.exptime
        ),
    )
    
    # Calibration status
    calibration = CalibrationStatus(
        dark_available=darks.count > 0,
        flat_available=flats.count > 0,
        bias_available=bias.count > 0,
        dark_flat_available=dark_flats.count > 0,
        dark_count=darks.count,
        flat_count=flats.count,
        bias_count=bias.count,
        dark_flat_count=dark_flats.count,
    )
    
    return ObservationContext(
        target=ObservationTarget(
            name=target_name,
            target_type=target_type,
            ra=first_header.ra if first_header else None,
            dec=first_header.dec if first_header else None,
        ),
        frames=frame_sets,
        calibration=calibration,
        equipment=equipment,
        acquisition=acquisition,
        source_path=source_path,
    )


# Export key functions
__all__ = [
    "parse_fits_header",
    "apply_filename_fallback",
    "detect_frame_type",
    "scan_directory",
    "build_observation_context",
    "parse_filename_metadata",
    "HEADER_ALIASES",
    "FrameType",
    "TargetType",
]