"""Configuration data models."""

from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RegistrationConfig(BaseModel):
    """W9-B (AC-W9-B1/B4, ADR-019): Registrations-Methoden-Wahl.

    method: "fft" = v1.1-Verhalten (Translation-only, Hochpass-Grid);
        "astroalign" = Similarity (Rotation/Scale, optionales Extra);
        "rotation_fft" (V1.4-2) = Log-Polar-FFT-Rotation (AZ-Feldrotation,
        M27 ~7 Grad, M13 bis ~13 Grad) mit Compute-both-Arbitration gegen
        fft (Gewinn nur bei corr_hp_rot >= corr_hp + 0.02).
    max_control_points: astroalign-RANSAC-Kontrollpunkt-Limit (flux-sortiert,
        hellste zuerst). `null` wird im Code EXPLIZIT in den astroalign-
        Default 50 uebersetzt (Spike-Befund 1: `max_control_points=None`
        wuerde von astroalign als `array[:None]` = ALLE Punkte interpretiert —
        M13-Fehl-Asterismen-Risiko). Nur relevant bei method="astroalign".
    max_rotation_deg: SanityGuard-Schwelle (S1-A7) fuer die maximale
        |Rotation| in Grad. Default 2.0 = bisheriges Verhalten. AZ-Aufnahmen
        (Feldrotation) koennen groessere Werte erfordern (M27: ~7 Grad;
        CLI-Flag --max-rotation, Precedence CLI > Config > Preset > Default).
        Relevant bei method="astroalign" und method="rotation_fft".
    max_scale_dev: SanityGuard-Schwelle (S1-A7) fuer die maximale
        |scale - 1| Abweichung. Default 0.02 = bisheriges Verhalten. Selten
        anzupassen — bewusst NUR Config/Preset (kein CLI-Flag).
        Relevant bei method="astroalign" und method="rotation_fft" (dort
        Metrik aus der Log-Polar-Phasenkorrelation; die Skala wird NICHT
        auf die Daten angewendet).
    stack_scale_factor: F-META-1.2 (stella Punkt 5): Faktor der EFFEKTIVEN
        Pixelgroesse des gestackten Outputs gegenueber der nativen
        Equipment-Pixelgroesse (XPIXSZ/YPIXSZ im Light-Header). Default 2.0
        (Teleskop (z.B. Dwarf3): nativ 1920x1080 (~2MP), Pixel 2.9 µm, Tele 150 mm —
        der Stack ist durch den 2x2-Superpixel-Debayer genau 2x herunter-
        skaliert; KEINE 4K-Annahme mit zusaetzlichem Hardware-
        Binning) -> XPIXSZ = 2.9 x 2.0 = 5.8 µm -> Siril leitet
        206.265 x 5.8 / 150 = 7.98 arcsec/px ab (statt 3.99 aus dem
        nativen XPIXSZ). Precedence Config > Preset > Default (kein
        CLI-Flag). Greift im Export-Header als Fallback, wenn keine
        PCC-Skala verfuegbar ist (nebula-Presets, z.B. M27).
    zero_shift_threshold: RE-F (V1.3-24, AC-RE-F3): corr_hp-Schwelle fuer
        den W1-Zero-Shift-Fallback (fft-Zweig). Default 0.0 = Guard praktisch
        deaktiviert (Fallback/Reject greift nur bei corr_hp < 0.0, d.h.
        praktisch nie); Werte > 0 bewusst setzen, um den W1-Guard (RE-F,
        V1.3-24) zu aktivieren.
        Bei astroalign-Gewinner ist dieselbe Schwelle die Reject-Schwelle:
        corr_hp_aa < Schwelle -> Frame verwerfen statt zeroshift-stapeln
        (AC-RE-F1). CLI-Flag --zero-shift-threshold.
    zero_shift_fallback: RE-F (V1.3-24, AC-RE-F3): True = W1-Guard aktiv
        (v1.2-Default; fft -> Zero-Shift, astroalign-Gewinner -> Reject);
        False (--no-zero-shift-fallback) = Guard komplett deaktiviert
        (weder Zero-Shift noch astroalign-Reject).
    max_exptime_fft_warn: V1.9: configurable FFT warning threshold in
        seconds. Propagated by the resolver/equipment profile (default 45.0)
        and used in cli.py for the E4 warning.
    """

    method: Literal["fft", "astroalign", "rotation_fft"] = "fft"
    max_control_points: Optional[int] = None
    max_rotation_deg: float = 2.0
    max_scale_dev: float = 0.02
    stack_scale_factor: float = 2.0
    zero_shift_threshold: float = 0.0
    zero_shift_fallback: bool = True
    max_exptime_fft_warn: float = 45.0


class GradientRemovalConfig(BaseModel):
    """GR-B (AC-GR-B1/B3): Gradient-Removal-Config-Block.

    Liegt auf zwei Ebenen:
    - Preset: ``pipeline.processing_params.gradient_removal``.
    - Config: ``AppConfig.gradient_removal`` (ueberschreibt Preset).
    Precedence CLI > Config > Preset > Default (siehe
    ``resolve_gradient_removal``).

    enabled: ``False`` = Default (OQ-GR-1-A: erst nach Validierung aktiv;
        bestehende Presets bleiben v1.1-identisch bis der User aktiviert).
    degree: Grad des 2D-Polynom-Hintergrundmodells (2 deckt
        Teleskop (z.B. Dwarf3)-Vignettierung + typische LP-Gradienten).
    grid: ``(rows, cols)`` Sampling-Grid der Zellen-Mediane. Default
        (16, 16) — M13-Real-Run-Validierung (AC-GR-C4,
        s2-b4-m13-grid-validierung): 16x16 besser als 32x32
        (residual_mad -31%/-27%, residual_max -40%).
    sigma_clip: ``k`` fuer das k*MAD-Sigma-Clipping (OQ-GR-3 Default 3.0).
    min_samples: Mindest-Sample-Zellen fuer den Fit. Wird der Wert
        unterschritten, ueberspringt die Pipeline den Schritt mit Warning
        (AC-GR-B3, E1). ``None`` = Anzahl der Polynom-Terme.
    """

    enabled: bool = False
    degree: int = 2
    grid: tuple[int, int] = (16, 16)
    sigma_clip: float = 3.0
    min_samples: Optional[int] = None


class CosmeticCorrectionConfig(BaseModel):
    """Leo-Auftrag 2026-08-10 (Bad-Pixel-Korrektur, Teil A): Cosmetic-Correction-
    Config-Block.

    Pipeline-Stufe zwischen Kalibrierung (``01_calibrated``) und Debayer
    (``02_debayered``): Bad-Pixel-Map wird aus den kalibrierten Lights
    abgeleitet (Detektion, ``core/cosmetic.detect_bad_pixels``), defekte
    Pixel werden vor dem Debayer durch den Median der Nachbarpixel
    derselben Bayer-Farbe (Distanz 2) ersetzt
    (``core/cosmetic.interpolate_bad_pixels``). Nur fuer CFA-Daten
    (1080x1920, Teleskop (z.B. Dwarf3)), kein Eingriff nach dem Debayer.

    enabled: ``True`` = Stufe aktiv. Default False (bestehende Pipelines
        bleiben v1.3-identisch bis zur Freigabe — gleiche Politik wie
        GradientRemovalConfig.enabled).
    n_frames: Mindestanzahl Frames, in denen ein Pixel heiss sein muss,
        um als defekt zu gelten. Default 3 (stella-Vorgabe "3 von >= 8").
    threshold: Schwelle in DN ueber der lokalen Umgebung (same-color-
        Nachbarmedian, Distanz 2). Default 50.
    dark_tolerance: Toleranz fuer "Master-Dark dort normal":
        ``dark < median(dark) + dark_tolerance``. Default 20 (stella-
        Vorgabe "Dark < Dark-BG + 20").
    """

    enabled: bool = False
    n_frames: int = 3
    threshold: float = 50.0
    dark_tolerance: float = 20.0


class FilenamePatternConfig(BaseModel):
    """V1.6-1 (SSOT-C): Konfigurierbare Filename-Patterns fuer Metadaten-Extraktion.

    Ermöglicht geräteunabhängiges Parsing von Dateinamen fuer Calibration-Frames
    (Dark/Flat/Bias), bei denen der FITS-Header oft leer ist (DwarfLab Firmware-Bug).
    Light-Frames nutzen ausschliesslich den FITS-Header (SSOT).
    """

    regex: str
    fields: list[str] = Field(default_factory=list)

    @field_validator("regex")
    @classmethod
    def validate_regex(cls, v: str) -> str:
        """AC-SSOT-C2: Regex beim Config-Load validieren (Compilation-Check)."""
        import re as _re
        try:
            _re.compile(v)
        except _re.error as e:
            raise ValueError(f"Ungültiges Regex-Pattern: {e}") from e
        return v


class FilenamePatterns(BaseModel):
    """V1.6-1 (SSOT-C): Sammlung aller Filename-Patterns + Presets."""

    dark: Optional[FilenamePatternConfig] = None
    light: Optional[FilenamePatternConfig] = None
    dark_dwarf3: Optional[FilenamePatternConfig] = None
    dark_compact: Optional[FilenamePatternConfig] = None
    generic: Optional[FilenamePatternConfig] = None
    presets: dict[str, dict[str, str]] = Field(default_factory=dict)


class PreviewExportConfig(BaseModel):
    """V1.8-2 (AC-PREV-A1..A5): Preview/Export-Pipeline Einstellungen.

    Konfigurierbar ueber ``export.preview`` in ``config.yaml``.
    Default-Werte in diesem Model sind die V1.8-2 Feature-Defaults
    (scnr=true, saturation=1.2, background_neutralization=true).
    Fuer die Rueckwaertskompatibilitaet sorgt ``ProcessingParams.preview_export``,
    dessen Defaults Asinh-only sind (ohne Config-Block -> byte-identisch v1.6).

    Reihenfolge im Code (stella OQ-PEX-1):
        background_neutralization -> scnr -> asinh -> saturation -> jpg
    """

    stretch: Literal["asinh", "linear", "none"] = "asinh"
    scnr: bool = True
    saturation: float = 1.2
    background_neutralization: bool = True

    @field_validator("saturation")
    @classmethod
    def validate_saturation(cls, v: float) -> float:
        if not 0.5 <= v <= 2.0:
            raise ValueError(f"saturation must be 0.5..2.0, got {v!r}")
        return v


class StretchConfig(BaseModel):
    """V1.8-3 (AC-FITS-A1..A4): Stretch-Parameter fuer gestretchten FITS-Export.

    Konfigurierbar ueber ``export.stretch`` in ``config.yaml``.
    Default method="asinh" mit a=0.01 (identisch zum Preview-Default).
    """

    method: Literal["asinh", "linear", "none"] = "asinh"
    a: float = 0.01


class ExportConfig(BaseModel):
    """V1.8-2 + V1.8-3: Export-Konfiguration (``export.*`` in ``config.yaml``).

    V1.8-2: ``preview`` steuert die JPG-Preview-Pipeline.
    V1.8-3: ``stretched_fits`` aktiviert den optionalen gestretchten FITS-Export
    (``*_stretched.fits``) zusätzlich zum linearen FITS. ``stretch`` enthaelt
    die Stretch-Parameter (method, a). Default ``stretched_fits=false`` haelt
    das Verhalten byte-identisch zu v1.6/V1.8-2.
    """

    preview: PreviewExportConfig = Field(default_factory=PreviewExportConfig)
    stretched_fits: bool = False
    stretch: StretchConfig = Field(default_factory=StretchConfig)


class CFADrizzleQualityGateConfig(BaseModel):
    """V1.8-1 (AC-DRZ-5): Quality Gate VOR CFA-Drizzle.

    rejection_enabled: True = Frames werden gefiltert (nur non-outlier).
    thresholds: Per-Metrik (min, max) Bounds. None = kein Bound.
    elongation_unusable: Alias fuer rejection_elongation (bool).

    V1.8-1 (DEF-004): CFA-Raw Star-Detection braucht niedrigere Schwellen,
    weil un-debayerter CFA-Frames weniger Sterne liefern. ``min_stars_cfa``
    steuert den FWHM-Guard in ``compute_frame_quality``; ``star_count_cfa``
    ueberschreibt den ``star_count``-Rejection-Threshold fuer den CFA-Pfad.
    ``highpass_sigma`` konfiguriert den Luminanz-Hochpass vor der Detection.

    V19-CFA-GATE G3: mode auto|cfa|debayered (Default auto -> CFA bei is_cfa True).
    """

    mode: Literal["auto", "cfa", "debayered"] = "auto"
    rejection_enabled: bool = True
    thresholds: dict[str, tuple[Optional[float], Optional[float]]] = Field(default_factory=dict)
    elongation_unusable: bool = True
    min_stars_cfa: int = 3
    # Default (3, None) ensures the CFA path does not reject all frames
    # when the user config only carries the debayered-RGB star_count threshold.
    # Explicit `null` disables the override (uses thresholds["star_count"]).
    star_count_cfa: Optional[tuple[Optional[float], Optional[float]]] = Field(default=(3.0, None))
    highpass_sigma: float = 30.0

    @field_validator("thresholds", mode="before")
    @classmethod
    def coerce_thresholds(cls, v):
        # Spec schreibt elongation_unusable:true INNERHALB thresholds dict.
        # Falls dort, extrahieren (bool -> nicht Threshold).
        if isinstance(v, dict) and "elongation_unusable" in v:
            # Wird als separate Eigenschaft behandelt, aber hier nur
            # tolerieren: entferne bool-Eintrag, damit Tuple-Validierung nicht bricht.
            v = dict(v)
            # Behalte Wert fuer elongation_unusable falls dort gesetzt
            # Der Caller kann ihn separat auslesen; hier nur sanitize.
            val = v.pop("elongation_unusable")
            # Falls bool, nicht als Threshold speichern
            if isinstance(val, bool):
                pass
            else:
                # Falls Tuple-artig, wieder einsetzen (unwahrscheinlich)
                v["elongation_unusable"] = val
        return v


class CFADrizzleConfig(BaseModel):
    """V1.8-1 CFA-Drizzle (Scale 2.0).

    enabled: false = Default aus (byte-identisch v1.7, AC-DRZ-1).
    scale: 2.0 = doppelte Aufloesung.
    pixfrac_mode: "auto" (dynamisch <10=1.0, 10-30=0.7, >30=0.5) | "fixed".
    pixfrac: Nur bei fixed, Default 0.5.
    kernel: "lanczos3" (Default, Siril-Standard) | "gaussian" | "tophat".
    quality_gate: VOR Drizzle (nur non-outlier Frames).
    min_frames: Minimum fuer Drizzle (< -> Fallback, Default 5).
    fallback: "malvar" | "superpixel" | "skip".
    """

    enabled: bool = False
    scale: float = 2.0
    pixfrac_mode: Literal["auto", "fixed"] = "auto"
    pixfrac: float = 0.5
    kernel: Literal["lanczos3", "gaussian", "tophat"] = "lanczos3"
    quality_gate: CFADrizzleQualityGateConfig = Field(default_factory=CFADrizzleQualityGateConfig)
    min_frames: int = 5
    fallback: Literal["malvar", "superpixel", "skip"] = "malvar"


class FrameSelectionConfig(BaseModel):
    """V1.7-2 FSEL-B (AC-FSEL-B1): Perzentilbasierte Frame-Selection.

    DwarfLab-Pattern: Top keep_percentile % behalten, Rest verwerfen.
    Default disabled (opt-in, OQ-FSEL-2 A), keep_percentile 92, min_frames 3,
    weights konfigurierbar (AC-FSEL-A4, AC-FSEL-B1). Rundungsregel floor
    der Verwurf-Anzahl (AC-FSEL-B3).
    """

    enabled: bool = False
    keep_percentile: int = 92
    weights: Optional[dict[str, float]] = None
    min_frames: int = 3

    @field_validator("keep_percentile")
    @classmethod
    def validate_keep_percentile(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError(f"keep_percentile must be 1..100, got {v!r}")
        return v

    @field_validator("min_frames")
    @classmethod
    def validate_min_frames(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"min_frames must be >=1, got {v!r}")
        return v


class ProcessingParams(BaseModel):
    """Processing parameters."""
    rejection: str = "winsorized"
    # Leo-Auftrag 2026-08-10 (Teil B3): Explizite Stacking-Methode.
    # None = nicht gesetzt -> die `stack_2d`-Methode wird aus `rejection`
    # gemappt (Teil B1: winsorized->winsorized, average->average,
    # none->average; siehe `resolve_stack_method` in core/stacking.py).
    # Explizit gesetzt (Preset, Config oder CLI-Flag --stacking-method)
    # gewinnt ueber das Rejection-Mapping. Vorher wurde dieser Wert von
    # Pydantic (extra="ignore") still verworfen — der Stack-Code fiel auf
    # Average zurueck.
    stacking_method: Optional[str] = None
    normalization: str = "mul"
    weight: str = "noise"
    stretch_method: str = "asinh"
    stretch_factor: float = 0.15
    scnr_amount: float = 0.5
    # F-P2-GAIA-TIMEOUT (v1.2, S3-C5): Timeout fuer GAIA-Katalog-Queries
    # (PCC). Ersetzt den Hardcode 30.0 in core/pcc.py als Config-Feld;
    # Default 30.0 = bisheriges Verhalten (rueckwaertskompatibel).
    # Rechtfertigt sich im QG4-Run (Duo-Band: schmales Sternfeld ->
    # weniger Katalog-Matches -> laengere/unsicherere Query).
    gaia_timeout: float = 30.0
    # VizieR-Timeouts (separat konfigurierbar, Bug 3 Fix 2026-08-17):
    # VizieR-Kataloge werden nach GAIA-Retry-Backoff abgefragt; eigene
    # Timeouts ermoeglichen feinere Kontrolle (z.B. langsame Verbindungen).
    vizier_apass_timeout: float = 30.0
    vizier_refcat2_timeout: float = 30.0
    registration: RegistrationConfig = Field(default_factory=RegistrationConfig)
    gradient_removal: GradientRemovalConfig = Field(default_factory=GradientRemovalConfig)

    # V1.8-0 (MALVAR): Debayer-Methode — "superpixel" (Default, DADR-003),
    # "malvar" (volle 1920x1080, High-Quality Malvar2004, kanten-erhaltend),
    # "bilinear" deprecated (Grace v1.8, use malvar or superpixel).
    # Precedence CLI > Config > Preset > Default.
    debayer_method: Literal["superpixel", "bilinear", "malvar"] = "superpixel"

    # V1.5-9 (AC-SD-5): Star-double detection config.
    # double_detection: Enable/disable the double-rate metric (default True).
    # double_radius_px: Pixel radius for neighbor search (OQ-SD-2, default 5.0).
    double_detection: bool = True
    double_radius_px: float = 5.0

    # V1.5-3 (AC-EL-7): Elongation check config.
    # elongation_check: Enable/disable x/y FWHM elongation measurement
    # (default False = AC-EL-7, Default-off, byte-identical to v1.2).
    elongation_check: bool = False
    elongation_warn_threshold: float = 0.8
    elongation_unusable_threshold: float = 0.6
    elongation_min_stars: int = 10

    # V1.5-8 (AC-OR-2): Outlier-rejection config.
    # rejection_enabled: Enable/disable frame-based outlier rejection
    # (default False = AC-OR-2, Default-off, byte-identical to v1.2).
    rejection_enabled: bool = False
    # rejection_thresholds: Per-metric (min, max) bounds.
    # None = no bound on that side. Empty dict = no rejection.
    # Example: {"snr": (5.0, null), "fwhm": (null, 8.0)} rejects
    # frames with snr < 5.0 or fwhm > 8.0.
    rejection_thresholds: dict[str, tuple[Optional[float], Optional[float]]] = Field(
        default_factory=dict
    )
    # rejection_elongation: When True, frames with elongation_unusable=True
    # are also rejected (V1.5-3 + V1.5-8 integration).
    rejection_elongation: bool = True

    # V1.8-8 (DEF-006): Mandatory corr_hp Gate für Average-Pfad (stella a+c).
    # Analog V1.4-20 Cross-Group-Gate (MergeConfig.min_correlation 0.1), aber
    # intra-group VOR Stacking. Default 0.05 — frames mit corr_hp <0.05
    # (katastrophale Registration, Ghosting M92 0.004-0.01) werden auch bei
    # rejection_enabled=False verworfen (mandatory, nicht an Flag hängend).
    # None = Gate deaktiviert. Kombiniert mit outlier_excluded: verwirft wenn
    # outlier_excluded==True ODER corr_hp<Schwelle (stella Empfehlung a+c).
    # Precedence Config > Preset > Default (siehe resolve_rejection_min_corr_hp).
    rejection_min_corr_hp: Optional[float] = Field(default=0.05, ge=0.0, le=1.0)

    # V1.7-2 FSEL-B (AC-FSEL-B1): Frame-Selection (DwarfLab-Pattern).
    # Perzentilbasierte Auswahl je Gruppe vor Stacking (AC-FSEL-B2..B6).
    # Default disabled (opt-in, OQ-FSEL-2 A), keep_percentile 92 (Top 92%),
    # min_frames 3 (Guard), weights konfigurierbar (AC-FSEL-A4).
    frame_selection: FrameSelectionConfig = Field(default_factory=FrameSelectionConfig)

    # V1.8-2 (AC-PREV-A1..A5): Preview/Export-Pipeline Einstellungen.
    # Default Asinh-only (rueckwaertskompatibel zu v1.6).
    # Die empfohlenen Feature-Defaults liegen in config.yaml (export.preview)
    # bzw. in PreviewExportConfig.
    preview_export: PreviewExportConfig = Field(
        default_factory=lambda: PreviewExportConfig(
            stretch="asinh",
            scnr=False,
            saturation=1.0,
            background_neutralization=False,
        )
    )


class PipelineStep(BaseModel):
    """Single pipeline step definition."""
    name: str
    params: dict = Field(default_factory=dict)
    condition: Optional[str] = None  # Optional condition expression


class PipelinePreset(BaseModel):
    """Pipeline preset for a target type."""
    name: str
    target_types: list[str]
    steps: list[PipelineStep]
    processing_params: ProcessingParams = Field(default_factory=ProcessingParams)
    description: str = ""


class EquipmentProfile(BaseModel):
    """Equipment profile for FITS header fallback. V19-REG-SMART R1."""

    model_config = ConfigDict(extra="ignore")

    name: str
    telescope: str = "Unknown"
    aperture_mm: int = 0
    focal_length_mm: int = 0
    camera: str = "Unknown"
    pixel_size_um: float = 3.76
    gain: int = 100
    offset: int = 50
    default_temp_c: float = -10.0
    mount_type: Literal["az", "eq", "unknown"] = "unknown"
    preferred_registration: Literal["fft", "astroalign", "rotation_fft"] = "fft"
    max_rotation_deg: float = 2.0
    max_exptime_fft_warn: float = 45.0
    deprecated: bool = Field(default=False)
    alias_for: Optional[str] = None


class MergeConfig(BaseModel):
    """Merge configuration for multi-group stacking.

    V1.7-1 FSM-A (AC-FSM-A1/A2, OQ-FSM-2 A): Filter-Auswahl fuer den finalen
    Gruppen-Merge. ``filters=None`` (Default) = alle Gruppen mergen
    (v1.6-verhalten, byte-identisch, keine zusaetzlichen Warnings).
    ``filters=[...]`` = NUR Gruppen deren FILTER-Wert exakt
    case-insensitive getrimmt in der Liste steht, gehen in den finalen Merge
    (kein Glob/Pattern, keine feste Astro/Duo-Klassifikation).
    Leere Liste nach Normalisierung bedeutet: keine Gruppe passt
    (Merge-Skip mit Warning, OQ-FSM-4 A — AC-FSM-A5).
    """

    method: Literal["weighted_average", "average", "median"] = "weighted_average"
    weight_by: Literal["frame_count", "total_exposure"] = "frame_count"
    min_correlation: float = 0.1  # CR-001 W3: corr_hp-Schwelle für Merge-Skip (AC-W3-1)
    filters: Optional[list[str]] = None  # V1.7-1 FSM-A: None = alle mergen


class MultiGroupConfig(BaseModel):
    """Multi-group stacking configuration.

    V1.7-5 (Always Multi-Group): Das fruehere Feld ``enabled`` ist entfernt
    (OQ-AMG-5: funktionslos — kein Leser im Code). Alte Configs mit
    ``multi_group.enabled`` laden weiter (AppConfig: extra="ignore").
    """
    # V1.3-5 (Boris-Entscheidung 2026-08-11): Default "quality" — Referenz
    # nach REGISTRIERUNGS-QUALITÄT (registration_metrics, V1.3-3) statt
    # Signalmaß (W14 "signal" wählte im M13-Fall die schwächste Gruppe →
    # Cross-Group-Registration scheiterte). "signal" | "largest" | Hash
    # bleiben als Option (Config-Override).
    reference_group: str = "quality"
    # V1.4-19 (Boris/stella 2026-08-16): Default "auto" — stufenweise
    # PCC-Fallback-Kette (GAIA-Retry 1x/2x/3x gaia_timeout → VizieR
    # APASS DR9/ATLAS Refcat2 → preset-abhaengig gray_world/skip) statt
    # sofort gray_world (51-Cyg-Erfahrung: gray_world zerstoert
    # Stern-Bilder). "gray_world" (Deep-Sky), "skip" (Sterne), "fail"
    # bleiben als explizite Overrides.
    pcc_fallback: Literal["gray_world", "skip", "fail", "auto"] = "auto"
    # V1.6 (stella/Boris 2026-08-20): PCC auf MERGED Stack (alle Frames, max S/N)
    # statt pro Gruppe (kleine Gruppen -> zu wenige Matches). Default True.
    pcc_per_group: bool = False
    merge: MergeConfig = Field(default_factory=MergeConfig)
    keep_group_working_dirs: bool = True  # CR-001 P1: Gruppen-Dirs bleiben per Default (AC-P1-1/2)


class PCCQualityGateConfig(BaseModel):
    """PCC Quality Gate (2026-08-21): plausible Farb-Faktoren erzwingen.

    Nach der Faktor-Berechnung, VOR dem Apply/Overwrite: Ablehnung wenn
    irgendein Kanal-Faktor <= 0 (Kanal-Inversion) ODER ausserhalb
    [min_factor, max_factor]. Bei Ablehnung bleibt der Stack linear
    (kein Overwrite), Marker PCC_REJECTED_FACTORS.txt + Log-Event
    pcc.rejected_implausible_factors, pcc_status =
    "rejected_implausible_factors" (agent-log.yaml + run-info.json).
    Die Ablehnung ENDET die PCC-Kette (leo 2026-08-21) — kein weiterer
    Katalog-Fallback; die Leiter existiert fuer "kein Match", nicht fuer
    "physisch unplausibler Match".

    enabled: True = Gate aktiv (Default). False = Verhalten wie v1.6.
    min_factor: Untere Plausibilitaetsgrenze (Default 0.5).
    max_factor: Obere Plausibilitaetsgrenze (Default 2.0).
    """

    enabled: bool = True
    min_factor: float = 0.5
    max_factor: float = 2.0


class PCCConfig(BaseModel):
    """PCC-Konfiguration (config.yaml: pcc.*)."""

    enabled: Optional[bool] = None  # None = Preset gewinnt (kein Breaking), True/False = Config-Override
    quality_gate: PCCQualityGateConfig = Field(default_factory=PCCQualityGateConfig)


class RuntimeConfig(BaseModel):
    """Runtime configuration (CLI overrides)."""
    target_path: Optional[Path] = None
    preset: Optional[str] = None
    output_dir: Optional[Path] = None
    working_dir: Optional[Path] = None
    dry_run: bool = False
    resume: bool = False
    keep_working: bool = False
    cpu_threads: Optional[int] = None
    no_gpu: bool = False
    verbose: bool = False
    cosmetic_correction_enabled: Optional[bool] = None  # CLI override


class AppConfig(BaseSettings):
    """Main application configuration with layered loading."""
    
    model_config = SettingsConfigDict(
        env_prefix="ASTRA_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Paths
    data_root: Path = Path("C:/Astra")
    working_dir: Path = Path("./working")
    output_dir: Path = Path("./output")
    config_dir: Path = Path("./config")
    
    # External tools
    gimp_path: Path = Path("gimp")
    # graxpert handled via Python package
    
    # Processing defaults
    default_preset: str = "star_standard"
    cpu_threads: int = 0  # 0 = auto
    gpu_acceleration: bool = True
    keep_working: bool = False
    
    # Quality thresholds
    quality_accept_threshold: int = 80
    quality_review_threshold: int = 60
    
    # Plate solving (optional)
    plate_solve_enabled: bool = False
    astrometry_bin: Optional[Path] = None
    astrometry_index_dir: Optional[Path] = None
    
    # Multi-group stacking
    multi_group: Optional[MultiGroupConfig] = None

    # W9-B (AC-W9-B1/B4, ADR-019): Registrations-Methoden-Wahl.
    # Precedence CLI > Config > Preset > Default (siehe resolve_registration).
    # None = kein Config-Block (Preset/Default gilt).
    registration: Optional[RegistrationConfig] = None

    # GR-B (AC-GR-B1): Gradient-Removal-Config-Block (Config-Ebene).
    # Precedence CLI > Config > Preset > Default (siehe
    # resolve_gradient_removal). None = kein Config-Block (Preset/Default gilt).
    gradient_removal: Optional[GradientRemovalConfig] = None

    # V1.5-9 (AC-SD-5): Star-double detection — optional top-level override.
    # None = use ProcessingParams default (True). When set, overrides the
    # preset value.
    double_detection: Optional[bool] = None
    double_radius_px: Optional[float] = None

    # V1.5-3 (AC-EL-7): Elongation check — optional top-level override.
    # None = use ProcessingParams default (False). When set, overrides the
    # preset value.
    elongation_check: Optional[bool] = None
    elongation_warn_threshold: Optional[float] = None
    elongation_unusable_threshold: Optional[float] = None
    elongation_min_stars: Optional[int] = None

    # V1.5-8 (AC-OR-2): Outlier-rejection — optional top-level override.
    # None = use ProcessingParams default (False). When set, overrides the
    # preset value.
    rejection_enabled: Optional[bool] = None
    rejection_thresholds: Optional[dict[str, tuple[Optional[float], Optional[float]]]] = None
    rejection_elongation: Optional[bool] = None
    # V1.8-8 (DEF-006): Mandatory corr_hp Gate — optional top-level override.
    # None = use ProcessingParams default (0.05). Explicit value (inkl. None
    # zum Deaktivieren) overrides. Analog V1.4-20 min_correlation (0.1), aber
    # intra-group vor Stacking, mandatory für average (stella a+c).
    rejection_min_corr_hp: Optional[float] = None

    # V1.7-2 FSEL-B (AC-FSEL-B1): Frame-Selection — optional top-level override.
    # None = use ProcessingParams default (enabled False, OQ-FSEL-2 A).
    # Precedence Config > Preset > Default (siehe resolve_frame_selection).
    frame_selection: Optional[FrameSelectionConfig] = None

    # Leo-Auftrag 2026-08-10 (Bad-Pixel-Korrektur, Teil A): Cosmetic-
    # Correction-Config-Block. Precedence CLI > Config > Default.
    # CLI-Flag: --cosmetic-correction / --no-cosmetic-correction.
    # None = kein Config-Block (Default gilt: enabled False, n_frames 3,
    # threshold 50.0, dark_tolerance 20.0).
    cosmetic_correction: Optional[CosmeticCorrectionConfig] = None
    
    # PCC Timeouts (Precedence: Config > ProcessingParams Default > Code Default).
    # Top-Level Config-Felder — erlauben Timeout-Konfiguration ueber config.yaml
    # unabhaengig von den ProcessingParams-Defaults in den Presets.
    # Presets mit explizitem Timeout != 30.0 behalten ihren Wert (Precedence-Regel).
    gaia_timeout: float = 30.0
    vizier_apass_timeout: float = 30.0
    vizier_refcat2_timeout: float = 30.0

    # PCC Quality Gate (2026-08-21): config.yaml pcc.quality_gate.*.
    # Default-Factory = rueckwaertskompatibel (kein Config-Eintrag noetig,
    # Gate aktiv mit 0.5–2.0). Siehe PCCQualityGateConfig-Docstring.
    pcc: PCCConfig = Field(default_factory=PCCConfig)

    # V1.6-1 (SSOT-C): Konfigurierbare Filename-Patterns.
    # Precedence: Config-Patterns > hardcoded Defaults (AC-SSOT-C4).
    filename_patterns: Optional[FilenamePatterns] = None

    # V1.8-1 (CFA-Drizzle): Drizzle-Config-Block.
    # Precedence: CLI > Config > Default (enabled false, AC-DRZ-1).
    cfa_drizzle: Optional[CFADrizzleConfig] = None

    # V1.8-0 (MALVAR): Debayer-Config-Block.
    # Precedence: Config > ProcessingParams Default (superpixel).
    # method: "superpixel" (Default, DADR-003), "malvar" (1920x1080 High-Quality)
    # oder "bilinear" (deprecated, Grace v1.8).
    debayer_method: Optional[Literal["superpixel", "bilinear", "malvar"]] = None

    # V1.8-2 (AC-PREV-A1..A5): Preview/Export-Pipeline Einstellungen.
    # None = kein Config-Block -> Preset-Default (Asinh-only, byte-identisch v1.6).
    export: Optional[ExportConfig] = None

    # CR-001 W4 (P4): Flats/Bias Config-Defaults (Teleskop (z.B. Dwarf3): keine Flats, Bias im Dark)
    use_flats: bool = False
    use_bias: bool = False

    # V1.6-1 (SSOT-A4): Mandatory-Fields fuer Light-Frames.
    # Bei Fehlen dieser Felder im FITS-Header wird der Pipeline-Lauf abgebrochen
    # (kein Filename-Fallback fuer Light-Frames). Precedence Config > Default.
    # Default: [exptime, gain, object, ccd_temp] (Beschluss OQ-SSOT-1).
    mandatory_fields: list[str] = Field(
        default=["exptime", "gain", "object", "ccd_temp"]
    )

    # T2: --no-calib: Kalibration ueberspringen fuer vor-kalibrierte Daten
    # (Lights gehen direkt zu Debayer/Processing; keine Darks/Flats/Bias-Anforderung)
    no_calib: bool = False
    
    # CR-001 W5 (P5-C): Darks-Bibliothek
    darks_repository: Optional[Path] = None

    # Leo-Auftrag 2026-08-09 (Dark-Offset-Abgleich, Teil 2): Schwellen der
    # Dark-Sanity-Warnung calibration.dark_scale_mismatch in
    # calibration.py _apply_calibration(). Effektive Schwelle:
    # max(dark_scale_mismatch_abs, dark_scale_mismatch_frac * light_bg).
    # Defaults 5.0 DN / 4 %: fuer C20 (light_bg ~205) ergibt sich 8.2 DN <
    # gemessenes Delta ~9.7 DN -> Warnung + Offset-Abgleich greifen. Der
    # Auftragsvorschlag (10 % bzw. 10 DN) wuerde C20 mit delta 9.7 knapp
    # verfehlen. Precedence Config > Default (kein CLI-Flag).
    dark_scale_mismatch_abs: float = 5.0
    dark_scale_mismatch_frac: float = 0.04

    # Ray-Review M-1 (Low-Side-Check): Schwelle der Dark-Sanity-Warnung
    # calibration.dark_scale_mismatch_low (calibration.py _apply_calibration):
    # dark_bg < dark_scale_mismatch_low_frac * light_bg -> Warnung (C20-
    # Fehlerklasse 2: Lokal-Dark float32 0.003-0.04 vs Light ~205 ->
    # Subtraktion wirkungslos -> Hot Pixels bleiben). Default 0.5 (ray-Vorgabe
    # ~0.5: gesunde Darks liegen immer >= ~90 % von light_bg, also keine
    # Fehlwarnungen). Nur Warnung — kein Abbruch. Precedence Config > Default
    # (kein CLI-Flag).
    dark_scale_mismatch_low_frac: float = 0.5

    # Profiles & presets
    equipment_profiles: list[EquipmentProfile] = Field(default_factory=list)
    pipeline_presets: list[PipelinePreset] = Field(default_factory=list)
    
    @field_validator("working_dir", "output_dir", "config_dir", "data_root", "gimp_path", "darks_repository", "astrometry_bin", "astrometry_index_dir", mode="before")
    @classmethod
    def resolve_paths(cls, v: str | Path | None) -> Path | None:
        if v is None:
            return None
        if isinstance(v, str):
            if v.strip() == "":
                # Root-Drift Guard: leerer String nicht auf CWD resolven
                return Path(v)
            return Path(v).expanduser().resolve()
        return v.expanduser().resolve()
    
    def get_equipment_profile(self, name: str = "default") -> EquipmentProfile:
        """Get equipment profile by name."""
        for profile in self.equipment_profiles:
            if profile.name == name:
                return profile
        # Return default if not found
        return EquipmentProfile(name=name)
    
    def get_preset(self, name: str) -> Optional[PipelinePreset]:
        """Get pipeline preset by name."""
        for preset in self.pipeline_presets:
            if preset.name == name:
                return preset
        return None
    
    def get_preset_for_target(self, target_type: str) -> PipelinePreset:
        """Find best preset for target type."""
        for preset in self.pipeline_presets:
            if target_type.lower() in [t.lower() for t in preset.target_types]:
                return preset
        # Fallback to default
        for preset in self.pipeline_presets:
            if preset.name == self.default_preset:
                return preset
        if self.pipeline_presets:
            return self.pipeline_presets[0]
        return PipelinePreset(name="fallback", target_types=["*"], steps=[])
