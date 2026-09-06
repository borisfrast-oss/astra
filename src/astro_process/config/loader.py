"""Configuration loader with defaults."""

import os
import re
from pathlib import Path
from typing import Literal

import structlog
import yaml

from .models import (
    AppConfig,
    CFADrizzleConfig,
    CFADrizzleQualityGateConfig,
    ExportConfig,
    FrameSelectionConfig,
    GradientRemovalConfig,
    PipelinePreset,
    PreviewExportConfig,
    RegistrationConfig,
    StretchConfig,
)

logger = structlog.get_logger(__name__)

# ── V19-ENV: .env + expandvars ────────────────────────────────────────

# Regex fuer ${VAR:-default} + ${VAR} + $VAR
# - ${VAR:-default} : VAR leer/unset -> default
# - ${VAR} / $VAR   : VAR leer/unset -> "" (bzw. bleibt leer, Root-Drift Guard unten)
_ENV_VAR_PATTERN = re.compile(
    r"\$\{([^}:]+)(?::-([^\}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)"
)


def _expand_env_string(value: str) -> str:
    """Expandiere ${VAR:-default} + ${VAR} + $VAR via os.environ.

    Python 3.11 os.path.expandvars unterstuetzt ${VAR:-default} NICHT nativ,
    daher manueller Regex-Fallback. Precedence: os.environ gewinnt (Shell > .env).

    - ${VAR:-default}: wenn VAR in environ und nicht-leer -> environ[VAR],
      sonst default (auch wenn VAR=="" )
    - ${VAR} / $VAR: wenn VAR in environ -> environ[VAR], sonst "" (kein Default)
      -> Root-Drift Guard: leere Expansion wird als "" belassen, Caller muss
      damit umgehen (nicht auf CWD resolven).
    """

    def _replace(m: re.Match) -> str:
        braced_var = m.group(1)
        braced_default = m.group(2)
        simple_var = m.group(3)
        if braced_var is not None:
            var_name = braced_var
            env_val = os.environ.get(var_name)
            # ${VAR:-default} mit Default
            if braced_default is not None:
                if env_val is not None and env_val != "":
                    return env_val
                return braced_default
            # ${VAR} ohne Default
            if env_val is not None:
                return env_val
            return ""
        if simple_var is not None:
            env_val = os.environ.get(simple_var)
            return env_val if env_val is not None else ""
        return m.group(0)

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _expand_config_values(obj):
    """Rekursiv alle String-Werte in Dict/List via _expand_env_string expandieren."""
    if isinstance(obj, dict):
        return {k: _expand_config_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_config_values(v) for v in obj]
    if isinstance(obj, str):
        return _expand_env_string(obj)
    return obj


def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """Recursive dict-merge, ``override`` wins on key conflicts.

    Used by the auto-discovery layers (CWD / user-config / pipeline-root,
    see ``load_config``) to implement the "Layered: defaults < user config
    < project config < CLI overrides" contract documented at the top of
    ``DEFAULT_CONFIG`` — a discovered ``config.yaml`` that only sets a
    handful of fields (e.g. Boris' ``~/.config/astra/config.yaml``, which
    only sets ``data_root``/``suggest.target_cache_path``/etc.) must still
    inherit ``pipeline_presets``/``equipment_profiles``/... from
    ``DEFAULT_CONFIG`` instead of silently losing them (``AppConfig``'s
    own Pydantic defaults for those fields are empty lists, NOT
    ``DEFAULT_CONFIG``'s values \u2014 without this merge a minimal discovered
    config.yaml would make every preset lookup fail, V19-Config-Discovery
    Stella-Smoke 2026-09-04 fallout).

    Lists/scalars are replaced wholesale by ``override`` (no element-wise
    merge, e.g. a custom ``pipeline_presets`` list fully replaces the
    default one, matching normal user expectations); only dict values are
    merged recursively.
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_dotenv_files() -> None:
    """Lade .env Dateien mit Precedence CWD > pipeline_root, Shell > .env.

    Reihenfolge: CWD/.env zuerst (wenn vorhanden) mit override=False
    (Shell gewinnt), danach pipeline_root/.env ebenfalls mit override=False.
    So gewinnt CWD ueber pipeline_root, aber keine .env ueberschreibt Shell.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # CWD zuerst, dann pipeline_root -> CWD gewinnt
    for cand in (Path.cwd() / ".env", _pipeline_root() / ".env"):
        if cand.is_file():
            try:
                load_dotenv(dotenv_path=cand, override=False)
                logger.debug("config.dotenv_loaded", path=str(cand))
            except Exception:
                continue


DEFAULT_CONFIG = """
# Astra Pipeline Configuration
# Layered: defaults < user config < project config < CLI overrides

data_root: "C:/Astra"
working_dir: "./working"
output_dir: "./output"
config_dir: "./config"

gimp_path: "gimp"

default_preset: "star_standard"
cpu_threads: 0
gpu_acceleration: true
keep_working: false

quality_accept_threshold: 80
quality_review_threshold: 60

plate_solve_enabled: false
# astrometry_bin: "C:/Tools/astrometry/bin/solve-field.exe"
# astrometry_index_dir: "C:/Tools/astrometry/index"

# CR-001 W4 (P4): Flats/Bias Config-Defaults
# Teleskop (z.B. Dwarf3): keine Flats, Bias im Dark enthalten
use_flats: false
use_bias: false

# --no-calib: Kalibration ueberspringen fuer vor-kalibrierte Daten
# (Lights gehen direkt zu Debayer/Processing; keine Darks/Flats/Bias-Anforderung)
no_calib: false

# V1.8-1 (CFA-Drizzle): Drizzle-Config (Scale 2.0, auto pixfrac, lanczos3)
# enabled: false = Default aus (AC-DRZ-1 byte-identisch v1.7).
# quality_gate: Thresholds fuer Outlier-Filter VOR Drizzle.
# pixfrac_mode: auto (dynamisch <10=1.0, 10-30=0.7, >30=0.5) | fixed.
# fallback: malvar | superpixel | skip (unter min_frames, Default malvar).
# cfa_drizzle:
#   enabled: false
#   scale: 2.0
#   pixfrac_mode: "auto"
#   pixfrac: 0.5
#   kernel: "lanczos3"
#   quality_gate:
#     rejection_enabled: true
#     thresholds:
#       fwhm: [1.5, 5.0]
#       snr: [10, null]
#       star_count: [20, null]
#       correlation: [0.3, null]
#     elongation_unusable: true
#   min_frames: 5
#   fallback: "malvar"

# CR-001 W5 (P5-C): Darks-Bibliothek (Optional)
# Pfad zur zentralen Darks-Bibliothek (_darks/ Ordnerstruktur)
# darks_repository: "C:/Astra/_darks"

# Leo-Auftrag 2026-08-09 (Dark-Offset-Abgleich): Schwellen der Dark-Sanity-
# Warnung calibration.dark_scale_mismatch (calibration.py _apply_calibration).
# Effektive Schwelle: max(dark_scale_mismatch_abs, dark_scale_mismatch_frac *
# light_bg). Defaults 5.0 DN / 4 % — erkennt die C20-Referenz (Dark 214.7 vs
# Light 205.0, delta ~9.7 DN); der Auftragsvorschlag (10 % bzw. 10 DN) wuerde
# C20 knapp verfehlen.
dark_scale_mismatch_abs: 5.0
dark_scale_mismatch_frac: 0.04

# Ray-Review M-1 (Low-Side-Check): Schwelle der Dark-Sanity-Warnung
# calibration.dark_scale_mismatch_low (calibration.py _apply_calibration):
# dark_bg < dark_scale_mismatch_low_frac * light_bg -> Warnung (C20-
# Fehlerklasse 2: Lokal-Dark float32 0.003-0.04 vs Light ~205 -> Subtraktion
# wirkungslos -> Hot Pixels bleiben). Default 0.5 (ray-Vorgabe ~0.5: gesunde
# Darks liegen immer >= ~90 % von light_bg, also keine Fehlwarnungen). Nur
# Warnung, kein Abbruch. Precedence Config > Default (kein CLI-Flag).
dark_scale_mismatch_low_frac: 0.5

# W9-B (AC-W9-B1/B4, ADR-019): Registrations-Methode.
# method: "fft" = v1.1-Verhalten (Default, Translation-only via Hochpass-Grid).
#         "astroalign" = Similarity-Transform (Rotation/Scale) — erfordert das
#         Extra: pip install "astra[astroalign]" (fallback auf fft sonst).
# max_control_points: astroalign-Kontrollpunkt-Limit, flux-sortiert (hellste
# zuerst). null = astroalign-Default 50. Nur relevant bei "astroalign".
# max_rotation_deg: SanityGuard-Schwelle (S1-A7): max. |Rotation| in Grad,
# bevor ein astroalign-Ergebnis verworfen wird (FFT-Fallback). Default 2.0 =
# bisheriges Verhalten. AZ-Aufnahmen (Feldrotation) koennen groessere Werte
# brauchen (M27: ~7 Grad; --max-rotation CLI-Flag, Precedence CLI > Config >
# Preset > Default). Nur relevant bei "astroalign".
# max_scale_dev: SanityGuard-Schwelle (S1-A7): max. |scale - 1| Abweichung.
# Default 0.02 = bisheriges Verhalten. Selten anzupassen — bewusst NUR
# Config/Preset (kein CLI-Flag). Nur relevant bei "astroalign".
# stack_scale_factor: F-META-1.2 (stella Punkt 5): Faktor der EFFEKTIVEN
# Pixelgroesse des gestackten Outputs gegenueber der nativen XPIXSZ/YPIXSZ.
# Default 2.0 (Teleskop (z.B. Dwarf3): nativ 1920x1080 (~2MP), Pixel 2.9 µm, Tele 150 mm
# — der Stack ist durch den 2x2-Superpixel-Debayer genau 2x herunterskaliert;
# KEINE 4K-Annahme mit zusaetzlichem Hardware-Binning) ->
# Export-Header setzt XPIXSZ = nativer Wert x Faktor
# (Fallback ohne PCC-Skala, z.B. nebula_standard/M27), damit Siril die
# korrekte ~7.98 arcsec/px ableitet statt 3.99. Precedence Config > Preset
# > Default (kein CLI-Flag).
registration:
  method: "fft"
  max_control_points: null
  max_rotation_deg: 2.0
  max_scale_dev: 0.02
  stack_scale_factor: 2.0
  zero_shift_threshold: 0.05
  zero_shift_fallback: true

# GR-B (AC-GR-B1): Gradient-Removal-Config (auch ueber CLI-Flags
# --gradient-removal-* ueberschreibbar; Precedence CLI > Config > Preset >
# Default — siehe resolve_gradient_removal).
# enabled: false = Default (OQ-GR-1-A: erst nach Validierung aktiv; die
#     Preset-Steps background_extraction/gradient_removal sind verdrahtet,
#     aber bis zur Aktivierung v1.1-identisch, AC-GR-C3).
# degree: Grad des 2D-Polynom-Hintergrundmodells (2 deckt
#     Teleskop (z.B. Dwarf3)-Vignettierung + typische LP-Gradienten, OQ-GR-3).
# grid: Sampling-Grid (rows, cols) der Zellen-Mediane. Default (16, 16) —
#     M13-Real-Run-Validierung (AC-GR-C4, s2-b4-m13-grid-validierung):
#     16x16 besser als 32x32 (residual_mad -31%/-27%, residual_max -40%).
# sigma_clip: k in k*MAD Sigma-Clipping (OQ-GR-3 Default 3.0).
# min_samples: Mindest-Sample-Zellen fuer den Fit; Unterschreitung ->
#     Schritt uebersprungen + Warning, Pipeline laeuft weiter (AC-GR-B3).
#     null = Anzahl der Polynom-Terme.
gradient_removal:
  enabled: false
  degree: 2
  grid: [16, 16]
  sigma_clip: 3.0
  min_samples: null

# Leo-Auftrag 2026-08-10 (Bad-Pixel-Korrektur, Teil A): Cosmetic-Correction-
# Pipeline-Stufe zwischen Kalibrierung (01_calibrated) und Debayer
# (02_debayered). Bad-Pixel-Map aus den kalibrierten Lights (Detektion),
# defekte Pixel werden vor dem Debayer durch den Median der Nachbarpixel
# derselben Bayer-Farbe (Distanz 2) ersetzt.
# enabled: false = Default (bestehende Pipelines bleiben v1.3-identisch
#     bis zur Freigabe). Precedence Config > Default (kein CLI-Flag).
# n_frames: Mindestanzahl Frames, in denen ein Pixel heiss sein muss
#     (stella-Vorgabe "3 von >= 8").
# threshold: Schwelle in DN ueber der lokalen Umgebung (same-color-
#     Nachbarmedian, Distanz 2).
# dark_tolerance: Toleranz fuer "Master-Dark dort normal":
#     dark < median(dark) + dark_tolerance (stella-Vorgabe Dark-BG + 20).
cosmetic_correction:
  enabled: false
  n_frames: 3
  threshold: 50.0
  dark_tolerance: 20.0

# V1.8-1 (CFA-Drizzle): Drizzle-Config (Scale 2.0, auto pixfrac, lanczos3)
# Default aus (AC-DRZ-1 byte-identisch v1.7). Precedence CLI > Config > Default.
# V19-CFA-GATE G3: quality_gate.mode auto|cfa|debayered (Default auto -> CFA bei is_cfa True)
cfa_drizzle:
  enabled: false
  scale: 2.0
  pixfrac_mode: "auto"
  pixfrac: 0.5
  kernel: "lanczos3"
  quality_gate:
    mode: "auto"
    rejection_enabled: true
    thresholds:
      fwhm: [1.5, 5.0]
      snr: [10, null]
      star_count: [20, null]
      correlation: [0.3, null]
    elongation_unusable: true
    min_stars_cfa: 3
  min_frames: 5
  fallback: "malvar"

# V1.7-2 FSEL-B (AC-FSEL-B1, OQ-FSEL-2 A): Frame-Selection (DwarfLab-Pattern).
# Default disabled (opt-in), keep_percentile 92 (Top 92% behalten), min_frames 3.
# Precedence Config > Preset > Default (siehe resolve_frame_selection).
# weights: null = Default gleichverteilt (snr/star_count/fwhm/elongation).
# Rundungsregel floor (AC-FSEL-B3): discard = floor(N * (100-keep)/100).
# Bei <min_frames verbleibend → skip mit Warning selection.skipped_min_frames
# und ALLE Frames stacken (AC-FSEL-B4). Nur Lights, je Gruppe unabhängig
# (AC-FSEL-B5/B6).
# frame_selection:
#   enabled: false
#   keep_percentile: 92
#   weights: null
#   min_frames: 3

# V19-PCC-FLAG P3: PCC Config (optional, Default null = Preset gewinnt)
# DEF-014 (Fix): pcc.enabled steuert den photometric_color_calibration-Preset-Step.
# null  = Preset gewinnt (kein Override — nebula_standard laeuft ohne PCC,
#         galaxy_standard mit PCC, jeweils wie im Preset definiert).
# true  = PCC-Step wird in den Preset eingefuegt wenn er fehlt (alle Presets mit PCC).
# false = PCC-Step wird aus dem Preset entfernt wenn er vorhanden ist (nie PCC).
# WICHTIG (DEF-014): Auch im Multi-Group-Pfad wird PCC NUR ausgefuehrt wenn
# photometric_color_calibration im Preset-Step vorhanden ist. Ein noop (z.B.
# nebula_standard + false: Step fehlt bereits) bedeutet kein PCC — vorher
# lief PCC trotzdem (Bug, behoben). CLI > File > Config > Preset-Default.
# pcc:
#   enabled: null  # null = Preset gewinnt, true = immer PCC, false = nie PCC (CLI gewinnt immer)
#   quality_gate:
#     enabled: true
#     min_factor: 0.5
#     max_factor: 2.0
pcc:
  enabled: null  # null = Preset gewinnt, true = immer PCC, false = nie PCC (DEF-014)
  quality_gate:
    enabled: true
    min_factor: 0.5
    max_factor: 2.0

# V1.8-8 (DEF-006): Mandatory corr_hp Gate für Average-Pfad (stella a+c).
# Analog V1.4-20 Cross-Group-Gate (MergeConfig.min_correlation 0.1), aber
# intra-group VOR Stacking. Default 0.05 — frames mit corr_hp <0.05
# (katastrophale Registration, Ghosting M92 0.004-0.01) werden auch bei
# rejection_enabled=false verworfen (mandatory, nicht an Flag hängend).
# Kombiniert mit outlier_excluded: verwirft wenn outlier_excluded==True
# ODER corr_hp<Schwelle. Precedence Config > Preset > Default (siehe
# resolve_rejection_min_corr_hp). None/null deaktiviert das Gate.
# Top-level Config-Feld (AppConfig.rejection_min_corr_hp) oder Preset
# (processing_params.rejection_min_corr_hp). CLI-Flag optional, Config Pflicht.
# rejection_min_corr_hp: 0.05

# V1.7-1 FSM-A (AC-FSM-A1/A2, OQ-FSM-2 A): Filter-Auswahl fuer den finalen
# Gruppen-Merge. Default ``filters`` NICHT gesetzt (None) = alle Gruppen mergen
# (v1.6-identisch, keine zusaetzlichen Warnings). Explizite Liste:
# ``filters: ["Astro"]`` = NUR Gruppen deren FILTER-Wert exakt
# case-insensitive getrimmt in der Liste steht, gehen in den finalen Merge
# (kein Glob/Pattern, Beispiel Galaxy-Standard ["Astro"], Duo-Band separat).
# CLI --merge-filter (wiederholbar) ueberschreibt Config (Precedence CLI > Config).
# Leere Liste nach Normalisierung = keine Gruppe passt -> Merge-Skip mit Warning
# (OQ-FSM-4 A, AC-FSM-A5). Auskommentiert = v1.6-Verhalten.
#   filters: ["Astro"]

# V1.7-5 (Always Multi-Group): Multi-Group ist IMMER aktiv — das fruehere
# Flag multi_group.enabled ist entfernt (OQ-AMG-5). Alte Configs mit dem
# Feld laden weiter (extra="ignore").
multi_group:
  # V1.3-5: Default "quality" — Referenz nach Registrierungs-Qualität
  # (registration_metrics, V1.3-3) statt Signalmaß (W14 "signal" wählte im
  # M13-Fall die schwächste Gruppe). "signal" | "largest" | Hash bleiben
  # als Option (Config-Override).
  reference_group: "quality"
  pcc_fallback: "auto"
  merge:
    method: "weighted_average"
    weight_by: "frame_count"
    # CR-001 W3 (AC-W3-1): Nicht-Referenz-Gruppen mit corr_hp < min_correlation
    # (nach W1-Handling) werden aus dem Merge ausgeschlossen (Sicherheitsnetz);
    # die Referenz-Gruppe wird nie geskippt. Stacks bleiben unter
    # group_*/04_stacked/ erhalten.
    min_correlation: 0.1
    # V1.7-1 FSM-A: siehe Kommentar oberhalb (filters, CLI --merge-filter).
    # filters: ["Astro"]
  keep_group_working_dirs: true

equipment_profiles:
  - name: "default"
    telescope: "Unknown"
    aperture_mm: 0
    focal_length_mm: 0
    camera: "Unknown"
    pixel_size_um: 3.76
    gain: 100
    offset: 50
    default_temp_c: -10.0

  - name: "dwarf_mini"
    telescope: "Dwarf Mini"
    aperture_mm: 0
    focal_length_mm: 150
    camera: "Dwarf Mini"
    pixel_size_um: 2.9
    gain: 60
    offset: 10
    default_temp_c: 27.0
    resolution: [1920, 1080]
    debayer_factor: 2.0
    bayer_pattern: "RGGB"
    sensor: "IMX462"
    mount_type: "az"
    preferred_registration: "astroalign"
    max_rotation_deg: 15
    max_exptime_fft_warn: 45

  - name: "dwarf3"
    deprecated: true
    alias_for: "dwarf_mini"

pipeline_presets:
  - name: "galaxy_standard"
    target_types: ["galaxy"]
    steps:
      - name: create_master_dark
      - name: calibrate_lights
      - name: register_frames
      - name: stack_frames
      - name: background_extraction
      - name: photometric_color_calibration
      - name: scnr
      - name: stretch
      - name: export
    processing_params:
      rejection: "winsorized"
      normalization: "mul"
      weight: "noise"
      stretch_method: "asinh"
      stretch_factor: 0.15

  - name: "nebula_standard"
    target_types: ["nebula", "emission_nebula", "reflection_nebula", "dark_nebula", "planetary_nebula"]
    steps:
      - name: create_master_dark
      - name: calibrate_lights
      - name: register_frames
      - name: stack_frames
      - name: gradient_removal
      - name: background_extraction
      - name: structure_enhancement
      - name: stretch
      - name: export
    processing_params:
      rejection: "winsorized"
      normalization: "mul"
      weight: "noise"
      stretch_method: "asinh"
      stretch_factor: 0.12
      preview_export:
        scnr: true
        background_neutralization: true
        saturation: 1.2
        stretch: "asinh"

  - name: "star_standard"
    target_types: ["star", "star_cluster", "globular_cluster", "open_cluster"]
    steps:
      - name: create_master_dark
      - name: calibrate_lights
      - name: register_frames
      - name: stack_frames
      - name: natural_color_processing
      - name: scnr
      - name: stretch
      - name: export
    processing_params:
      rejection: "winsorized"
      normalization: "add"
      weight: "none"
      stretch_method: "histogram"
      stretch_factor: 0.1

  - name: "nebula_narrowband"
    target_types: ["nebula_sh2", "nebula_hoo", "nebula_sh"]
    steps:
      - name: create_master_dark
      - name: calibrate_lights
      - name: register_frames
      - name: stack_frames_per_channel
      - name: channel_combination
      - name: gradient_removal
      - name: stretch
      - name: export
    processing_params:
      rejection: "winsorized"
      normalization: "mul"
      weight: "noise"
      preview_export:
        scnr: true
        background_neutralization: true
        saturation: 1.2
        stretch: "asinh"

  # V1.6-2 (OQ-BIL-1, AC-BIL-B3) + V1.8-0 (MALVAR): Bilinear-Presets fuer volle Aufloesung.
   # nebula_bilinear/galaxy_bilinear: Bilinear ist deprecated (Grace v1.8),
   # Alternative fuer volle Aufloesung ist malvar (Malvar2004, kanten-erhaltend).
   # nebula_bilinear: Bilinear Debayer + stack_scale_factor 1.0 (keine
   # Herunterskalierung) — ideal fuer Detailerkennung (Plate-Solving,
   # Annotierung).
  - name: "nebula_bilinear"
    target_types: ["nebula_bilinear"]
    steps:
      - name: create_master_dark
      - name: calibrate_lights
      - name: register_frames
      - name: stack_frames
      - name: gradient_removal
      - name: background_extraction
      - name: structure_enhancement
      - name: stretch
      - name: export
    processing_params:
      debayer_method: "bilinear"
      rejection: "winsorized"
      normalization: "mul"
      weight: "noise"
      stretch_method: "asinh"
      stretch_factor: 0.12

  - name: "galaxy_bilinear"
    target_types: ["galaxy_bilinear"]
    steps:
      - name: create_master_dark
      - name: calibrate_lights
      - name: register_frames
      - name: stack_frames
      - name: background_extraction
      - name: photometric_color_calibration
      - name: scnr
      - name: stretch
      - name: export
    processing_params:
      debayer_method: "bilinear"
      rejection: "winsorized"
      normalization: "mul"
      weight: "noise"
      stretch_method: "asinh"
      stretch_factor: 0.15
"""


PRESET_CONFIGS_DIR = Path(__file__).parent.parent / "config" / "presets"


def _warn_deprecated_profiles(cfg: AppConfig) -> None:
    """V19-REG-SMART R1: Warn when deprecated equipment profile is used.

    Loggt `equipment.profile_deprecated` fuer jedes Profil mit
    `deprecated==True` (z.B. `dwarf3` Alias fuer `dwarf_mini`).
    """
    for profile in getattr(cfg, "equipment_profiles", []) or []:
        if getattr(profile, "deprecated", False):
            logger.warning(
                "equipment.profile_deprecated",
                profile=profile.name,
                alias=getattr(profile, "alias_for", None),
            )


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration with layering.

    Quelle (Precedence, Leo-Auftrag 2026-08-11 B1; erweitert Stella-Smoke
    2026-09-04: ``suggest`` fand ``~/.config/astra/config.yaml`` nicht,
    weil diese Quelle bis dahin gar nicht Teil der Discovery war):
    1. Expliziter Pfad (CLI --config / -c): unveraendert. Existiert die
       Datei nicht, bleibt das bisherige Verhalten (DEFAULT-Fallback) —
       der CLI verhindert das bereits via ``click.Path(exists=True)``.
    2. Ohne expliziten Pfad: ``config.yaml`` im aktuellen Arbeitsverzeichnis
       (CWD) — ein frischer User, der nur ``process <target>`` ausfuehrt,
       bekommt seine Umgebungs-Config statt des Default-Strings.
    3. Kein CWD-Config: ``~/.config/astra/config.yaml`` (User-Config,
       ``_user_config_dir()`` — plattformunabhaengig ``Path.home()``).
       Ueberlebt einen ``git pull``/Neuinstallation im Projekt-Root und ist
       der Ort, an dem Boris z.B. ``suggest.target_cache_path`` auf die
       orion-KB zeigen laesst, ohne eine repo-lokale ``config.yaml`` zu
       pflegen.
    4. Kein User-Config: ``{pipeline_root}/config.yaml`` (Projekt-Root, das
       Verzeichnis, das ``src/astro_process`` enthaelt).
    5. Sonst: DEFAULT_CONFIG-String (degenerierte Fälle, z.B. Install per
       Wheel ohne Projekt-Root).

    Jede Quelle wird mit ``config.loaded_from`` (source, path) geloggt.

    V19-ENV: Vor yaml.safe_load alle String-Werte via expandvars pre-process
    mit ${VAR:-default} Fallback. .env wird via python-dotenv geladen
    (Precedence CWD .env > pipeline_root .env, Shell > .env).
    """
    # V19-ENV: .env laden vor jeder Expansion
    _load_dotenv_files()

    if config_path is not None:
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            user_config = _expand_config_values(user_config)
            logger.info("config.loaded_from", source="explicit", path=str(config_path))
            cfg = AppConfig(**user_config)
            _warn_deprecated_profiles(cfg)
            return cfg
        # Nicht-existenter expliziter Pfad: bisheriges Verhalten beibehalten
        # (DEFAULT-Fallback, kein stilles Weiter-Entdecken).
        logger.info("config.loaded_from", source="default",
                    reason=f"explicit path does not exist: {config_path}")
        default_data = yaml.safe_load(DEFAULT_CONFIG)
        default_data = _expand_config_values(default_data)
        cfg = AppConfig(**default_data)
        _warn_deprecated_profiles(cfg)
        return cfg

    for source, candidate in (
        ("cwd", Path.cwd() / "config.yaml"),
        ("user_config", _user_config_dir() / "config.yaml"),
        ("pipeline_root", _pipeline_root() / "config.yaml"),
    ):
        if candidate.is_file():
            with open(candidate, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            user_config = _expand_config_values(user_config)
            # Layered ueber DEFAULT_CONFIG (siehe _deep_merge_dicts) — ein
            # partieller Fund (z.B. nur data_root + suggest.*) verliert nicht
            # pipeline_presets/equipment_profiles/etc.
            default_data = yaml.safe_load(DEFAULT_CONFIG)
            merged_config = _deep_merge_dicts(default_data, user_config)
            logger.info("config.loaded_from", source=source, path=str(candidate))
            cfg = AppConfig(**merged_config)
            _warn_deprecated_profiles(cfg)
            return cfg

    logger.info("config.loaded_from", source="default")
    default_data = yaml.safe_load(DEFAULT_CONFIG)
    default_data = _expand_config_values(default_data)
    cfg = AppConfig(**default_data)
    _warn_deprecated_profiles(cfg)
    return cfg


def _user_config_dir() -> Path:
    """User-Config-Verzeichnis fuer ``load_config()`` Discovery-Layer 3.

    ``~/.config/astra`` (``Path.home()`` — funktioniert unter Windows
    genauso wie unter Linux/Mac, kein XDG-Sonderfall noetig, da astra kein
    weiteres XDG-konformes Verzeichnis nutzt). Eigene Funktion (statt
    inline in ``load_config``), damit Tests sie wie ``_pipeline_root``
    monkeypatchen koennen (Isolation von der echten ``~/.config/astra``
    eines Dev-Rechners, siehe test_cli_env_parametrization.py).
    """
    return Path.home() / ".config" / "astra"


def _pipeline_root() -> Path:
    """Projekt-Root der Pipeline (Verzeichnis, das ``src/astro_process`` enthaelt).

    ``src/astro_process/config/loader.py`` -> ``parents[3]`` = Projekt-Root
    (z.B. ``C:/Astra/projects/astra``). Bei Install per Wheel liegt
    das Paket unter ``site-packages/astro_process/config/`` -> ``parents[3]``
    = ``site-packages``; dort existiert kein ``config.yaml``, die Discovery
    faellt auf DEFAULT zurueck (nicht schlechter als bisher).
    """
    return Path(__file__).resolve().parents[3]


def save_default_config(path: Path) -> None:
    """Save default config to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(DEFAULT_CONFIG)


def load_preset(name: str) -> PipelinePreset:
    """Load a pipeline preset by name."""
    preset_file = PRESET_CONFIGS_DIR / f"pipeline_{name}.yaml"
    if preset_file.exists():
        with open(preset_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return PipelinePreset(**data)
    raise ValueError(f"Preset '{name}' not found at {preset_file}")


def resolve_registration(
    cfg: AppConfig,
    pipeline: PipelinePreset,
    cli_method: str | None = None,
    cli_max_rotation: float | None = None,
    cli_zero_shift_threshold: float | None = None,
    cli_zero_shift_fallback: bool | None = None,
) -> RegistrationConfig:
    """W9-B (AC-W9-B1, ADR-019): effektive Registrations-Config aufloesen.

    Precedence: CLI > Config (AppConfig.registration) > Preset
    (pipeline.processing_params.registration) > Default (fft / null /
    2.0 / 0.02 / 2.0 / 0.05 / true) — V19-FIX-12 P1 Mandatory Gate 0.05.

    Feldweise Aufloesung, `None` = "nicht gesetzt" auf jeder Ebene:
    - method: CLI-Flag, sonst Config-Block, sonst Preset, sonst "fft".
    - max_control_points: erster nicht-None-Wert von Config-Block, Preset,
      sonst None. `None` wird erst in `core/registration.astroalign_register`
      explizit in den astroalign-Default 50 uebersetzt (Spike-Befund 1,
      AC-W9-B4) — niemals `null` an die API durchreichen.
    - max_rotation_deg: CLI-Flag (--max-rotation), sonst Config-Block, sonst
      Preset, sonst 2.0 (Default = bisheriges SanityGuard-Verhalten).
    - max_scale_dev: Config-Block, sonst Preset, sonst 0.02. KEIN CLI-Flag
      (selten noetig, bewusst nur Config/Preset).
    - stack_scale_factor: Config-Block, sonst Preset, sonst 2.0 (F-META-1.2,
      stella Punkt 5 — Teleskop (z.B. Dwarf3): nur 2x Superpixel-Debayer). KEIN
      CLI-Flag — nur Config/Preset.
    - zero_shift_threshold: CLI-Flag (--zero-shift-threshold), sonst
      Config-Block, sonst Preset, sonst 0.05 (Default 0.05 = Guard aktiv
      V19-FIX-12, entkoppelt von frame_selection.enabled, P1 Mandatory Gate;
      Fallback/Reject greift bei corr_hp < 0.05; V1.8-8 DEF-006).
    - zero_shift_fallback: CLI-Flag (--no-zero-shift-fallback -> False),
      sonst Config-Block, sonst Preset, sonst True (RE-F, V1.3-24).
    """
    preset_reg = pipeline.processing_params.registration
    config_reg = cfg.registration

    method: Literal["fft", "astroalign", "rotation_fft"] = "fft"
    if preset_reg is not None:
        method = preset_reg.method
    if config_reg is not None:
        method = config_reg.method
    if cli_method == "astroalign":
        method = "astroalign"
    elif cli_method == "fft":
        method = "fft"
    elif cli_method == "rotation_fft":
        method = "rotation_fft"

    max_control_points: int | None = None
    if preset_reg is not None and preset_reg.max_control_points is not None:
        max_control_points = preset_reg.max_control_points
    if config_reg is not None and config_reg.max_control_points is not None:
        max_control_points = config_reg.max_control_points

    max_rotation_deg: float = 2.0
    if preset_reg is not None:
        max_rotation_deg = preset_reg.max_rotation_deg
    if config_reg is not None:
        max_rotation_deg = config_reg.max_rotation_deg
    if cli_max_rotation is not None:
        max_rotation_deg = cli_max_rotation

    max_scale_dev: float = 0.02
    if preset_reg is not None:
        max_scale_dev = preset_reg.max_scale_dev
    if config_reg is not None:
        max_scale_dev = config_reg.max_scale_dev

    stack_scale_factor: float = 2.0
    if preset_reg is not None:
        stack_scale_factor = preset_reg.stack_scale_factor
    if config_reg is not None:
        stack_scale_factor = config_reg.stack_scale_factor

    zero_shift_threshold: float = 0.05
    if preset_reg is not None:
        zero_shift_threshold = preset_reg.zero_shift_threshold
    if config_reg is not None:
        zero_shift_threshold = config_reg.zero_shift_threshold
    if cli_zero_shift_threshold is not None:
        zero_shift_threshold = cli_zero_shift_threshold

    zero_shift_fallback: bool = True
    if preset_reg is not None:
        zero_shift_fallback = preset_reg.zero_shift_fallback
    if config_reg is not None:
        zero_shift_fallback = config_reg.zero_shift_fallback
    if cli_zero_shift_fallback is not None:
        zero_shift_fallback = cli_zero_shift_fallback

    return RegistrationConfig(
        method=method,
        max_control_points=max_control_points,
        max_rotation_deg=max_rotation_deg,
        max_scale_dev=max_scale_dev,
        stack_scale_factor=stack_scale_factor,
        zero_shift_threshold=zero_shift_threshold,
        zero_shift_fallback=zero_shift_fallback,
    )


def resolve_gradient_removal(
    cfg: AppConfig,
    pipeline: PipelinePreset,
    cli_enabled: bool | None = None,
    cli_degree: int | None = None,
    cli_grid: tuple[int, int] | None = None,
    cli_sigma_clip: float | None = None,
    cli_min_samples: int | None = None,
) -> GradientRemovalConfig:
    """GR-B (AC-GR-B1..B3): effektive Gradient-Removal-Config aufloesen.

    Precedence: CLI > Config (AppConfig.gradient_removal) > Preset
    (pipeline.processing_params.gradient_removal) > Default
    (enabled false / degree 2 / grid (16, 16) / sigma_clip 3.0 /
    min_samples None).

    Feldweise Aufloesung, `None` = "nicht gesetzt" auf jeder Ebene
    (analog ``resolve_registration``):
    - enabled: CLI-Flag (nur wenn bool gesetzt), sonst Config-Block,
      sonst Preset, sonst False.
    - degree/grid/sigma_clip/min_samples: erster nicht-None-Wert von
      CLI, Config-Block, Preset, sonst Default.
    """
    preset_gr = pipeline.processing_params.gradient_removal
    config_gr = cfg.gradient_removal

    def _field(name: str, default, cli_val=None):
        value = default
        preset_value = getattr(preset_gr, name)
        if preset_value is not None:
            value = preset_value
        if config_gr is not None and getattr(config_gr, name) is not None:
            value = getattr(config_gr, name)
        if cli_val is not None:
            value = cli_val
        return value

    enabled = _field("enabled", False, cli_enabled)
    degree = _field("degree", 2, cli_degree)
    grid = _field("grid", (16, 16), cli_grid)
    sigma_clip = _field("sigma_clip", 3.0, cli_sigma_clip)
    min_samples = _field("min_samples", None, cli_min_samples)

    return GradientRemovalConfig(
        enabled=enabled,
        degree=degree,
        grid=grid,
        sigma_clip=sigma_clip,
        min_samples=min_samples,
    )


def resolve_stack_scale_factor(
    debayer_method: str = "superpixel",
    explicit_value: float | None = None,
    preset_value: float | None = None,
    input_is_rgb: bool = False,
) -> float:
    """V1.6-2 (BIL-E, AC-BIL-E1..E4) + V1.7-4 (EQPT-C, OQ-EQPT-3) + V1.8-0 (MALVAR).

    Precedence: explicit Config > Preset > Auto from data/debayer_method > Default.
    - explicit_value is not None: nutze explicit_value (manueller Override,
      AC-EQPT-C3 — gewinnt IMMER).
    - preset_value is not None: Preset-Wert (Fix B2, ray-Review 2026-08-23 —
      Stufe zwischen explicit und datengetrieben, OQ-EQPT-3-Kette).
    - input_is_rgb: bereits debayerte 3D-Lights -> 1.0 unabhaengig von der
      Methode (AC-EQPT-C2).
    - debayer_method in ("bilinear", "malvar"): 1.0 (keine Herunterskalierung,
      V1.8-0 malvar = volle Auflösung).
    - debayer_method == "superpixel": 2.0 (Teleskop (z.B. Dwarf3)-Default).
    - Default (weder Config noch Auto): 2.0 (Rueckwaertskompatibilitaet).

    Duenne Delegation an ``core.equipment.resolve_debayer_factor`` (V1.7-4):
    eine Wahrheit fuer die Faktor-Ableitung; der Rueckgabewert ist
    identisch zum v1.6-Verhalten fuer alle v1.6-Eingaben (kein Bruch).

    Args:
        debayer_method: Aktive Debayer-Methode ("superpixel", "bilinear" oder "malvar").
        explicit_value: Expliziter Config-Override (None = nicht gesetzt).
        preset_value: Preset-Wert aus resolve_registration (None = nicht
            gesetzt; der 2.0-Sentinel wird vom Aufrufer (cli.py) gefiltert).
        input_is_rgb: True, wenn die Lights bereits RGB/3D sind (V1.7-4).

    Returns:
        Effektiver stack_scale_factor (float).
    """
    from ..core.equipment import resolve_debayer_factor

    factor, _source = resolve_debayer_factor(
        debayer_method=debayer_method,
        explicit_value=explicit_value,
        preset_value=preset_value,
        input_is_rgb=input_is_rgb,
    )
    return factor


def resolve_frame_selection(
    cfg: AppConfig,
    pipeline: PipelinePreset,
    cli_enabled: bool | None = None,
    cli_keep_percentile: int | None = None,
) -> FrameSelectionConfig:
    """V1.7-2 FSEL-B (AC-FSEL-B1): effektive FrameSelectionConfig aufloesen.

    Precedence: CLI > Config (AppConfig.frame_selection) > Preset
    (pipeline.processing_params.frame_selection) > Default (enabled false,
    keep_percentile 92, weights None, min_frames 3) — OQ-FSEL-2 A opt-in.

    Feldweise Aufloesung, None = nicht gesetzt:
    - enabled: CLI-Flag, sonst Config, sonst Preset, sonst False.
    - keep_percentile: CLI, sonst Config, sonst Preset, sonst 92.
    - weights: erster nicht-None-Wert von CLI (nicht vorgesehen), Config,
      Preset, sonst None (Default gleichverteilt).
    - min_frames: Config, sonst Preset, sonst 3. Kein CLI-Flag.

    Rundungsregel floor der Verwurf-Anzahl (AC-FSEL-B3) liegt im Consumer
    (``_apply_frame_selection``), nicht hier.
    """
    preset_fs: FrameSelectionConfig = pipeline.processing_params.frame_selection
    config_fs: FrameSelectionConfig | None = cfg.frame_selection

    enabled = preset_fs.enabled
    if config_fs is not None:
        enabled = config_fs.enabled
    if cli_enabled is not None:
        enabled = cli_enabled

    keep_percentile = preset_fs.keep_percentile
    if config_fs is not None and config_fs.keep_percentile is not None:
        keep_percentile = config_fs.keep_percentile
    if cli_keep_percentile is not None:
        keep_percentile = cli_keep_percentile

    weights = preset_fs.weights
    if config_fs is not None and config_fs.weights is not None:
        weights = config_fs.weights
    # CLI weights nicht vorgesehen (FSEL-D via CLI-Flags separat)

    min_frames = preset_fs.min_frames
    if config_fs is not None and config_fs.min_frames is not None:
        min_frames = config_fs.min_frames

    return FrameSelectionConfig(
        enabled=enabled,
        keep_percentile=keep_percentile,
        weights=weights,
        min_frames=min_frames,
    )


def resolve_rejection_min_corr_hp(
    cfg: AppConfig,
    pipeline: PipelinePreset,
) -> float | None:
    """V1.8-8 (DEF-006): effektiven rejection_min_corr_hp aufloesen.

    Precedence: Config (AppConfig.rejection_min_corr_hp) > Preset
    (pipeline.processing_params.rejection_min_corr_hp) > Default 0.05.
    Explizites None (null in YAML) deaktiviert das Gate (kein corr_hp-Ausschluss).
    Analog V1.4-20 MergeConfig.min_correlation (0.1), aber intra-group VOR
    Stacking und mandatory für average (stella a+c, nicht an rejection_enabled).

    Returns:
        float Schwelle (0.0-1.0) oder None wenn deaktiviert.
    """
    preset_val: float | None = getattr(pipeline.processing_params, "rejection_min_corr_hp", 0.05)
    # preset_val defaults to 0.05 via model, None means disabled at preset level
    effective: float | None = preset_val
    # Config override — unterscheide "nicht gesetzt" vs. explizit null zur Deaktivierung
    # via model_fields_set (Pydantic v2)
    if cfg is not None:
        if "rejection_min_corr_hp" in getattr(cfg, "model_fields_set", set()):
            # Explizit gesetzt (inkl. None zum Deaktivieren)
            effective = cfg.rejection_min_corr_hp
        elif cfg.rejection_min_corr_hp is not None:
            # Fallback für Direktkonstruktion ohne fields_set (Tests)
            effective = cfg.rejection_min_corr_hp
    if effective is not None:
        try:
            fv = float(effective)
        except Exception:
            return 0.05
        if not (0.0 <= fv <= 1.0):
            # Clamp via Validation, aber hier robust
            return 0.05
        return fv
    return None


def resolve_preview_export_config(
    cfg: AppConfig,
    pipeline: PipelinePreset,
) -> PreviewExportConfig:
    """V1.8-2 (AC-PREV-A4/A5): effektive Preview/Export-Pipeline Config.

    Precedence: Config (AppConfig.export.preview) > Preset
    (pipeline.processing_params.preview_export) > Default.

    Ohne ``export``-Block in der Config greift der Preset-Default,
    der Asinh-only ist (stretch=asinh, scnr=false, saturation=1.0,
    background_neutralization=false) -> byte-identisch zu v1.6.
    """
    preset_pe: PreviewExportConfig = pipeline.processing_params.preview_export
    config_pe: PreviewExportConfig | None = None
    if cfg.export is not None:
        config_pe = cfg.export.preview

    def _field(name: str, default):
        value = default
        preset_value = getattr(preset_pe, name)
        if preset_value is not None:
            value = preset_value
        if config_pe is not None:
            config_value = getattr(config_pe, name)
            if config_value is not None:
                value = config_value
        return value

    stretch = _field("stretch", "asinh")
    scnr = _field("scnr", False)
    saturation = _field("saturation", 1.0)
    background_neutralization = _field("background_neutralization", False)

    return PreviewExportConfig(
        stretch=stretch,  # type: ignore
        scnr=scnr,
        saturation=saturation,
        background_neutralization=background_neutralization,
    )


def resolve_export_config(
    cfg: AppConfig,
    pipeline: PipelinePreset,
) -> ExportConfig:
    """V1.8-3 (AC-FITS-A1..A4): effektive Export-Config aufloesen.

    Precedence: Config (AppConfig.export) > Preset
    (pipeline.processing_params.export) > Default
    (``stretched_fits=false``, ``stretch.method=asinh``, ``stretch.a=0.01``).

    Ohne ``export``-Block in der Config greifen die Defaults ->
    ``stretched_fits=false`` (byte-identisch zu v1.6/V1.8-2).
    """
    preset_ec: ExportConfig | None = getattr(
        pipeline.processing_params, "export", None
    )
    config_ec: ExportConfig | None = cfg.export

    def _field(name: str, default):
        value = default
        preset_value = getattr(preset_ec, name) if preset_ec is not None else None
        if preset_value is not None:
            value = preset_value
        if config_ec is not None:
            config_value = getattr(config_ec, name)
            if config_value is not None:
                value = config_value
        return value

    preview = _field("preview", PreviewExportConfig())
    stretched_fits = _field("stretched_fits", False)
    stretch = _field("stretch", StretchConfig())

    return ExportConfig(
        preview=preview,
        stretched_fits=stretched_fits,
        stretch=stretch,
    )


# ── V1.7-1 FSM-A: Merge Filter-Auswahl ──────────────────────────────────

def resolve_cfa_drizzle(
    cfg: AppConfig,
    cli_enabled: bool | None = None,
    cli_scale: float | None = None,
    cli_pixfrac: float | None = None,
    cli_kernel: str | None = None,
) -> CFADrizzleConfig:
    """V1.8-1 (AC-DRZ-1/4/9): effektive CFA-Drizzle-Config aufloesen.

    Precedence: CLI > Config (AppConfig.cfa_drizzle) > Default
    (enabled false, scale 2.0, pixfrac_mode auto, pixfrac 0.5,
    kernel lanczos3, quality_gate defaults, min_frames 5, fallback malvar).

    CLI-Felder:
    - enabled: --cfa-drizzle / --no-cfa-drizzle
    - scale: --drizzle-scale
    - pixfrac: --drizzle-pixfrac (setzt implizit pixfrac_mode=fixed)
    - kernel: --drizzle-kernel
    """
    config_drz: CFADrizzleConfig | None = getattr(cfg, "cfa_drizzle", None)
    # Defaults
    enabled = False
    scale = 2.0
    pixfrac_mode: Literal["auto", "fixed"] = "auto"
    pixfrac = 0.5
    kernel: Literal["lanczos3", "gaussian", "tophat"] = "lanczos3"
    quality_gate = CFADrizzleQualityGateConfig()
    min_frames = 5
    fallback: Literal["malvar", "superpixel", "skip"] = "malvar"

    if config_drz is not None:
        enabled = bool(config_drz.enabled)
        scale = float(config_drz.scale)
        pixfrac_mode = config_drz.pixfrac_mode  # type: ignore
        pixfrac = float(config_drz.pixfrac)
        kernel = config_drz.kernel  # type: ignore
        # Deep copy quality_gate
        if config_drz.quality_gate is not None:
            qg = config_drz.quality_gate
            quality_gate = CFADrizzleQualityGateConfig(
                rejection_enabled=bool(qg.rejection_enabled),
                thresholds=dict(qg.thresholds) if qg.thresholds else {},
                elongation_unusable=bool(qg.elongation_unusable),
                min_stars_cfa=int(qg.min_stars_cfa),
                star_count_cfa=qg.star_count_cfa,
                highpass_sigma=float(qg.highpass_sigma),
            )
        min_frames = int(config_drz.min_frames)
        fallback = config_drz.fallback  # type: ignore

    if cli_enabled is not None:
        enabled = bool(cli_enabled)
    if cli_scale is not None:
        scale = float(cli_scale)
    if cli_pixfrac is not None:
        pixfrac = float(cli_pixfrac)
        pixfrac_mode = "fixed"
    if cli_kernel is not None:
        kernel = cli_kernel  # type: ignore

    return CFADrizzleConfig(
        enabled=enabled,
        scale=scale,
        pixfrac_mode=pixfrac_mode,  # type: ignore
        pixfrac=pixfrac,
        kernel=kernel,  # type: ignore
        quality_gate=quality_gate,
        min_frames=min_frames,
        fallback=fallback,  # type: ignore
    )


def normalize_merge_filters(filters: list[str] | None) -> list[str] | None:
    """V1.7-1 FSM-A (AC-FSM-A2, OQ-FSM-2 A): Filter-Liste normalisieren.

    Normalisierung: strip + lower (case-insensitive, getrimmt) je Eintrag.
    Leere Strings nach dem Trimmen werden verworfen (best effort). Duplikate
    bleiben erhalten (keine Deduplizierung noetig, Matching nutzt Set).

    Args:
        filters: Rohliste aus Config oder CLI (None = alle mergen).

    Returns:
        Normalisierte Liste (lower, getrimmt) oder None wenn Input None.
        Leere Eingabe -> [] (kein Match -> Merge-Skip, AC-FSM-A5) — NICHT None.
    """
    if filters is None:
        return None
    normalized: list[str] = []
    for raw in filters:
        if not isinstance(raw, str):
            raw = str(raw)
        trimmed = raw.strip()
        if not trimmed:
            continue
        normalized.append(trimmed.lower())
    return normalized


def is_merge_filter_match(
    filter_value: str | None,
    normalized_filters: list[str] | None,
) -> bool:
    """V1.7-1 FSM-A: Prueft ob ein Gruppen-FILTER zur Auswahl passt.

    Args:
        filter_value: FILTER-Wert der Gruppe (aus group_metadata["filter"]
                      oder FITS HEADER FILTER; None/"" -> "none"/leer).
        normalized_filters: Normalisierte Auswahl via normalize_merge_filters.
                            None = alle mergen (AC-FSM-A1), [] = keine passt.

    Returns:
        True wenn Gruppe Merge-Kandidat ist, False wenn filter_excluded.
    """
    if normalized_filters is None:
        return True
    if not normalized_filters:
        return False
    # Gruppen-FILTER normalisieren: None/"" -> "" (nach trim/lower)
    if filter_value is None:
        candidate = ""
    else:
        candidate = str(filter_value).strip().lower()
    return candidate in normalized_filters


# ── V19-REG-SMART R3/R5 — Registration Priority Chain + Multi-Group ───


def _normalize_equipment_dict(equipment) -> dict | None:
    """Normalize equipment param (dict | EquipmentProfile | None) to dict."""
    if equipment is None:
        return None
    if isinstance(equipment, dict):
        # Empty dict -> treat as None (no profile)
        if not equipment:
            return None
        return dict(equipment)
    # EquipmentProfile object
    try:
        d: dict = {}
        # Only populate if attributes exist; Pydantic profile always has these
        if hasattr(equipment, "preferred_registration"):
            d["preferred_registration"] = equipment.preferred_registration
        if hasattr(equipment, "max_rotation_deg"):
            d["max_rotation_deg"] = equipment.max_rotation_deg
        if hasattr(equipment, "max_exptime_fft_warn"):
            d["max_exptime_fft_warn"] = equipment.max_exptime_fft_warn
        if hasattr(equipment, "mount_type"):
            d["mount_type"] = equipment.mount_type
        if hasattr(equipment, "name"):
            d["name"] = equipment.name
        return d if d else None
    except Exception:
        return None


def _mount_type_from_eqmode(header) -> str | None:
    """DEF-009: EQMODE-basierter Mount-Typ hat Vorrang vor Profil-Heuristik.

    Returns "az" fuer EQMODE=0, "eq" fuer EQMODE=1, None wenn EQMODE fehlt
    oder nicht interpretierbar ist.
    """
    if header is None:
        return None
    try:
        eq_mode = header.get("EQMODE", None)
        if eq_mode is None:
            return None
        eq_mode = int(eq_mode)
    except Exception:
        return None
    if eq_mode == 0:
        return "az"
    if eq_mode == 1:
        return "eq"
    return None


def _detect_equipment_from_header(header, cfg) -> dict:
    """Best-effort single-header equipment detection for R5 per-group.

    Matches TELESCOP header against AppConfig equipment_profiles (case-insensitive
    substring, longest wins via simple loop). Fallback hardcoded dwarf_mini AZ.
    Returns dict with preferred_registration, max_rotation_deg, max_exptime_fft_warn,
    mount_type, name — or {} if no match.

    DEF-009: EQMODE ueberschreibt das Profil-mount_type (0=az, 1=eq), damit
    Header-Wissen nicht vom Profil ueberschrieben wird.
    """
    if header is None or cfg is None:
        return {}
    try:
        telescop_raw = header.get("TELESCOP", "") if header is not None else ""
        telescop = str(telescop_raw or "").upper().strip()
    except Exception:
        telescop = ""
    if not telescop:
        return {}
    profiles = list(getattr(cfg, "equipment_profiles", None) or [])
    # Prefer exact/longest substring match (simplified vs. match_equipment_profile)
    best_len = -1
    best_profile = None
    t_lower = telescop.lower()
    for profile in profiles:
        for attr in ("name", "camera", "telescope"):
            pat = getattr(profile, attr, None)
            if not isinstance(pat, str) or not pat.strip():
                continue
            if pat.strip().lower() == "unknown":
                continue
            p_lower = pat.strip().lower()
            if p_lower in t_lower:
                cur_len = len(p_lower)
                # Exact match outranks substring by length bonus
                if p_lower == t_lower:
                    cur_len += 100
                if cur_len > best_len:
                    best_len = cur_len
                    best_profile = profile
    result: dict | None = None
    if best_profile is not None:
        result = {
            "preferred_registration": getattr(best_profile, "preferred_registration", "fft"),
            "max_rotation_deg": getattr(best_profile, "max_rotation_deg", 2.0),
            "max_exptime_fft_warn": getattr(best_profile, "max_exptime_fft_warn", 45),
            "mount_type": getattr(best_profile, "mount_type", "unknown"),
            "name": getattr(best_profile, "name", None),
        }
    # Hardcoded fallback for DWARF MINI without explicit profile (AZ 15 deg)
    elif "DWARF" in telescop and "MINI" in telescop:
        # Try to find dwarf_mini profile for values
        for profile in profiles:
            if str(getattr(profile, "name", "")).lower() == "dwarf_mini":
                result = {
                    "preferred_registration": getattr(profile, "preferred_registration", "astroalign"),
                    "max_rotation_deg": getattr(profile, "max_rotation_deg", 15),
                    "max_exptime_fft_warn": getattr(profile, "max_exptime_fft_warn", 45),
                    "mount_type": getattr(profile, "mount_type", "az"),
                    "name": getattr(profile, "name", "dwarf_mini"),
                }
                break
        if result is None:
            result = {
                "preferred_registration": "astroalign",
                "max_rotation_deg": 15.0,
                "max_exptime_fft_warn": 45.0,
                "mount_type": "az",
                "name": "dwarf_mini",
            }
    # SEESTAR etc. -> generic AZ if profile missing but header indicates AZ device
    if result is None:
        return {}

    # DEF-009: EQMODE ueberschreibt Profil-mount_type, damit Header-Wissen
    # gewinnt und logging/run-info konsistent bleiben.
    mt_from_eqmode = _mount_type_from_eqmode(header)
    if mt_from_eqmode is not None:
        result["mount_type"] = mt_from_eqmode
    return result


def resolve_registration_config(
    cfg: AppConfig,
    equipment: dict | None,
    header=None,
    exptimes: list[float] | None = None,
    cli_method: str | None = None,
    mount_type: str | None = None,
) -> dict:
    """V19-REG-SMART R3: Priority Chain CLI > Equipment-Profil > Auto-Detect > Config Default > hardcoded fft.

    Erweitert resolve_registration (nicht ersetzt, LEO prüft Signatur-Kollision; hal Resolver-Kollision beachten).
    Integrationspunkt cli.py:531 (inject mount_type via detect_mount_type).
    Spec R3 result dict mit method, max_control_points, max_rotation_deg, max_scale_dev,
    zero_shift_threshold, zero_shift_fallback, max_exptime_fft_warn.

    DEF-009: Optionaler mount_type-Override wird an detect_preferred_registration
    durchgereicht, wenn Auto-Detect greift (vermeidet doppelte Header-Analyse).
    """
    # Lazy import to avoid circular
    try:
        from ..core.equipment import detect_preferred_registration  # type: ignore
    except Exception:
        detect_preferred_registration = None  # type: ignore

    # Normalize equipment (dict | profile obj | None -> dict | None)
    equip_dict = _normalize_equipment_dict(equipment)

    result: dict = {
        "method": "fft",
        "max_control_points": None,
        "max_rotation_deg": 2.0,
        "max_scale_dev": 0.02,
        "zero_shift_threshold": 0.05,
        "zero_shift_fallback": True,
        "max_exptime_fft_warn": 45,
        "stack_scale_factor": 2.0,
    }
    # 5. hardcoded fft (already in result)
    # 4. Config Default (AppConfig.registration)
    try:
        if cfg is not None and getattr(cfg, "registration", None) is not None:
            cfg_reg = cfg.registration  # type: ignore
            cfg_method = getattr(cfg_reg, "method", None)
            if cfg_method:
                result["method"] = cfg_method
            # Also propagate other config fields if explicitly set (model_fields_set guard)
            # Use explicit check to avoid overwriting hardcoded with defaults when not set
            fields_set = getattr(cfg_reg, "model_fields_set", set()) if cfg_reg is not None else set()
            for field in ("max_control_points", "max_rotation_deg", "max_scale_dev",
                          "zero_shift_threshold", "zero_shift_fallback",
                          "max_exptime_fft_warn", "stack_scale_factor"):
                if field in fields_set:
                    try:
                        result[field] = getattr(cfg_reg, field)
                    except Exception:
                        pass
                else:
                    # Fallback for direct construction without fields_set (tests): if value differs from hardcoded, adopt
                    try:
                        val = getattr(cfg_reg, field, None)
                        if val is not None and val != result.get(field):
                            # For max_control_points None is valid default; only override if non-None distinct
                            if field == "max_control_points" and val is not None:
                                result[field] = val
                            elif field != "max_control_points":
                                # Only override if not equal to hardcoded (to preserve auto-detect vs config precedence)
                                # Use simple inequality
                                if val != result.get(field):
                                    # But need to avoid overriding when cfg is default-constructed with same defaults
                                    # We check if val != hardcoded default initial; if cfg method etc were default, they equal hardcoded
                                    pass
                    except Exception:
                        pass
    except Exception:
        pass

    # 3. Auto-Detect (falls kein Equipment-Profil matched) — V19-FIX-10: 15° dwarf_mini, 30° generic AZ
    if not equip_dict and header is not None and detect_preferred_registration is not None:
        try:
            auto_method = detect_preferred_registration(
                header, exptimes or [], mount_type=mount_type
            )
            result["method"] = auto_method
            if auto_method in ("astroalign", "rotation_fft"):
                # Generic AZ (Seestar, AZ ohne Dwarf-Mini Profil) braucht 30° (M27 Ghosting), Dwarf-Mini bleibt 15° (Spec dwarf_mini 15°)
                try:
                    telescop_upper = str(header.get("TELESCOP", "")).upper() if header is not None else ""
                except Exception:
                    telescop_upper = ""
                is_dwarf_mini = "DWARF" in telescop_upper and "MINI" in telescop_upper
                # mount_type bereits bekannt (via EQMODE oder detect_mount_type); fallback via header wenn None
                effective_mount = mount_type
                if effective_mount is None:
                    try:
                        from ..core.equipment import detect_mount_type as _dt  # type: ignore
                        effective_mount = _dt(header)
                    except Exception:
                        effective_mount = "az" if auto_method in ("astroalign", "rotation_fft") else "eq"
                if effective_mount == "az" and not is_dwarf_mini:
                    result["max_rotation_deg"] = 30.0
                else:
                    result["max_rotation_deg"] = 15.0
        except Exception:
            pass
    # 2. Equipment-Profil
    if equip_dict:
        try:
            if "preferred_registration" in equip_dict and equip_dict.get("preferred_registration"):
                result["method"] = equip_dict.get("preferred_registration", result["method"])
            if "max_rotation_deg" in equip_dict and equip_dict.get("max_rotation_deg") is not None:
                result["max_rotation_deg"] = float(equip_dict.get("max_rotation_deg", result["max_rotation_deg"]))  # type: ignore
            if "max_exptime_fft_warn" in equip_dict and equip_dict.get("max_exptime_fft_warn") is not None:
                result["max_exptime_fft_warn"] = float(equip_dict.get("max_exptime_fft_warn", 45))  # type: ignore
            # Also propagate mount_type-aware max_control_points if present? Keep result
        except Exception:
            pass
    # 1. CLI Override (höchste Priorität)
    if cli_method:
        result["method"] = cli_method
    return result


def resolve_group_registration_configs(
    cfg: AppConfig,
    groups: dict[str, list[Path]],
    cli_override: str | None = None,
    global_equipment: dict | None = None,
    eqmode_by_group: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """V19-REG-SMART R5: Registration-Config fuer jede Gruppe einzeln aufloesen.

    Pro Gruppe Header aus groups[group_name][0] lesen, exptimes aus fits header
    EXPTIME sammeln, group_equipment via detect_equipment_from_header / match +
    global_equipment mergen, dann resolve_registration_config aufrufen.
    Logger.info multi_group.group_registration_config je Gruppe.
    Cross-Group Config ist fest astroalign 20 deg (separater Helper).

    DEF-009: eqmode_by_group kann die aus den Original-Light-Headers bekannte
    EQMODE-Mehrheit pro Gruppe enthalten. Sie hat Vorrang vor dem erneuten
    Header-Lesen aus den Zwischen-Dateien (die EQMODE u.U. nicht bewahrt haben)
    und verhindert irrefuehrende discovery.mount_unknown-Warnungen.
    """
    from astropy.io import fits as _fits  # lazy

    group_configs: dict[str, dict] = {}
    # Normalize global_equipment
    norm_global = _normalize_equipment_dict(global_equipment)
    for group_name, frame_paths in (groups or {}).items():
        header = None
        exptimes: list[float] = []
        # Header from first frame
        try:
            if frame_paths:
                with _fits.open(str(frame_paths[0])) as hdul:
                    header = hdul[0].header
        except Exception:
            header = None
        # Exptimes from all frames
        try:
            for fp in frame_paths or []:
                try:
                    hdr = _fits.getheader(str(fp))
                    v = hdr.get("EXPTIME", 0)
                    if v is None:
                        continue
                    exptimes.append(float(v))
                except Exception:
                    continue
        except Exception:
            exptimes = []
        group_equipment = _detect_equipment_from_header(header, cfg)
        # Merge global + group (group wins)
        if norm_global and group_equipment:
            effective = {**norm_global, **group_equipment}
        elif norm_global:
            effective = dict(norm_global)
        elif group_equipment:
            effective = dict(group_equipment)
        else:
            effective = {}
        # DEF-009: Bekannte EQMODE-Mehrheit aus Original-Light-Headers hat
        # Vorrang (Zwischen-Dateien haben EQMODE u.U. nicht bewahrt).
        eqmode_majority = None
        eqmode_info = (eqmode_by_group or {}).get(group_name)
        if eqmode_info is not None:
            eqmode_majority = eqmode_info.get("majority")
        mt_from_eqmode = None
        if eqmode_majority == 0:
            mt_from_eqmode = "az"
        elif eqmode_majority == 1:
            mt_from_eqmode = "eq"

        effective_param = effective if effective else None
        cfg_result = resolve_registration_config(
            cfg=cfg, equipment=effective_param, header=header, exptimes=exptimes,
            cli_method=cli_override, mount_type=mt_from_eqmode,
        )
        group_configs[group_name] = cfg_result
        # Logging
        try:
            mount_type = effective.get("mount_type", "unknown") if effective else "unknown"
            if mount_type == "unknown" and mt_from_eqmode is not None:
                mount_type = mt_from_eqmode
            # Nur wenn weder Equipment noch EQMODE-Info vorliegt: Header-Heuristik.
            if mount_type == "unknown" and header is not None:
                try:
                    from ..core.equipment import detect_mount_type  # type: ignore
                    mount_type = detect_mount_type(header)
                except Exception:
                    mount_type = "unknown"
            max_exptime = max(exptimes) if exptimes else 0
            logger.info(
                "multi_group.group_registration_config",
                group=group_name,
                method=cfg_result.get("method"),
                mount_type=mount_type,
                max_exptime=max_exptime,
            )
        except Exception:
            pass
    return group_configs


def get_cross_group_registration_config() -> dict:
    """V19-REG-SMART R5 Cross-Group: immer rotation-fähig astroalign 20 deg."""
    return {"method": "astroalign", "max_rotation_deg": 20.0, "max_scale_dev": 0.05}


def resolve_merge_filters(
    cfg: AppConfig,
    cli_filters: tuple[str, ...] | list[str] | None = None,
) -> list[str] | None:
    """V1.7-1 FSM-A (AC-FSM-A3): Effektive Merge-Filter-Liste aufloesen.

    Precedence: CLI > Config (AppConfig.multi_group.merge.filters) > Default
    (None = alle mergen, AC-FSM-A1). CLI ist ``multiple=True`` — leeres
    Tuple bedeutet "nicht gesetzt" (kein Override), sonst akkumulierte Liste.

    Normalisierung findet HIER zentral statt (trim+lower, AC-FSM-A2) — robust
    fuer CLI UND Config (ein Ort, keine Duplikation im Merge-Filter).

    Args:
        cfg: AppConfig (bereits via load_config geladen).
        cli_filters: Tuple/Liste aus Click ``multiple=True`` oder None.

    Returns:
        Normalisierte Liste (lower, getrimmt) oder None (alle mergen).
        Leere Liste bedeutet: Filter gesetzt aber nach Trimmen leer -> spaeter
        <2 Kandidaten -> Merge-Skip (AC-FSM-A5). Keine Warnung bei None
        (Default, AC-FSM-A1).
    """
    # Config-Wert (None = nicht gesetzt, [] = explizit leer)
    config_filters: list[str] | None = None
    if cfg.multi_group is not None and cfg.multi_group.merge is not None:
        config_filters = cfg.multi_group.merge.filters

    # CLI gewinnt wenn gesetzt (nicht-leeres Tuple/Liste)
    if cli_filters is not None and len(cli_filters) > 0:
        # Click liefert Tuple; auch Liste erlauben (Tests)
        raw_cli = list(cli_filters)
        return normalize_merge_filters(raw_cli)

    # Sonst Config (inkl. None)
    return normalize_merge_filters(config_filters)
