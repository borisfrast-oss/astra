"""W9: Registrations-Adapter (Lazy-Import + Fallback + Strategy-Interface).

Verantwortlich (AC-W9-A1/A2, ADR-019, ADR-021, ADR-022):
- `astroalign` ist ein OPTIONALES Extra (`pip install "astra[astroalign]"`).
  Das Paket wird NIE beim Modulimport geladen, sondern erst beim ersten
  tatsaechlichen Wrapper-Aufruf (Lazy-Import).
- Fehlt das Paket: einmalige Warning `registration.astroalign_unavailable`
  (pro Prozess) + Aufrufer nutzt den fft-Fallback. Kein Traceback, kein
  Abbruch, kein stummer Lauf.
- Schlaegt der astroalign-Aufruf fehl (ValueError <3 Sterne, MaxIterError,
  TypeError): Warning `registration.astroalign_fallback` mit reason +
  Aufrufer nutzt den fft-Fallback (AC-W9-C3-Fallback-Kette).

S1-A7 (W9-C) erweitert dieses Modul um das Registration-Strategy-Interface
(ADR-022):
- `RegistrationTransform` (frozen Dataclass, AC-W9-C2-Logfelder).
- `RegistrationStrategy` (Protocol: `available()` / `compute(ref_mono,
  tgt_mono)`).
- `create_registration(method, max_control_points, grid_shift_fn)` als
  Dispatcher.
- `FftGridRegistration` kapselt `_corr_grid_shift` UNVERAENDERT (AC-W9-B3/C5:
  byte-identisches fft — die bestehende Methode wird nicht angefasst, sondern
  als Callable an den Konstruktor gebunden).
- `AstroalignRegistration` = Lazy-Import + `find_transform` auf dem
  W11-Hochpass-Mono (AC-W9-C1: `ref_mono - gaussian_filter(ref_mono, 30.0)`)
  + Mapping auf Pipeline-Konvention (rows, cols, ADR-020-Falle a) +
  Sanity-Guards (|scale-1| > max_scale_dev ODER |rotation| > max_rotation_deg
  -> verwerfen; Defaults 0.02 / 2.0 = bisheriges Verhalten, konfigurierbar
  ueber RegistrationConfig/CLI --max-rotation, M27-AZ-Feldrotation).
- `_apply_registration_transform(data, t, ref_mono, fill_value=0.0)`
  kapselt die Anwendung eines Similarity-Transforms (ADR-020-Falle b/c:
  Transform als Ganzes, pro Kanal bei RGB, Intra-Semantik cval=0.0).

Aufruf-Konvention (Konsistenz mit S1-A6 `find_transform(src, ref)`):
- Signatur: `astroalign_register(ref_mono, tgt_mono, ...)`
- Intern wird `astroalign.find_transform(tgt_mono, ref_mono, ...)` gerufen —
  `tgt_mono` ist der (zu registrierende) Frame, `ref_mono` die Referenz.

V1.4-2 (Cross-Group-Rotationsfaehigkeit, WCS-basiert):
- `RotationFftRegistration` = "rotation_fft"-Strategie fuer AZ-Feldrotation
  (M27 ~7 Grad, M13 bis ~13 Grad): Rotation via FFT-Phasenkorrelation im
  Log-Polar-Raum (`_log_polar`), Winkel-Refinement per Pearson-Korrelation
  (Grid ±3 x 0.25 Grad), anschliessend Translation via der gebundenen
  grid_shift_fn auf dem derotierten Hochpass-Mono.
- `apply_rotation_shift(data, rotation_deg, shift_y, shift_x)` wendet den
  rotation_fft-Transform auf Daten an (ADR-020-Falle c: pro Kanal bei RGB;
  mode='nearest' konsistent zum fft-Pfad, hal AQ5).
- Die WCS-Persistierung (REG_ROT statt CD-Matrix, V1.5-4 / DADR-014)
  erfolgt im Agent (ProcessingAgent._copy_wcs_headers), nicht hier.

Refactor 2026-08-14 (Cluster 3, processing_agent.py entflechten):
- Die Agent-Registrierungs-Methoden liegen seit diesem Refactor hier als
  Modul-Funktionen: `register_frames`, `compute_shift`, `corr_grid_shift`,
  `select_registration_channel`, `compute_shift_star_centroid` sowie die
  Dataclasses `RegistrationResult` (Cross-Group-Ergebnis) und
  `RegisterFramesResult` (Intra-Group-Ergebnis inkl. Registrierungs-
  Zustand). KEINE Verhaltensaenderung — Logik, Logger-Events und Fehler
  sind 1:1 uebernommen; geaendert hat sich nur die Aufruf-Konvention
  (explizite Parameter statt Instanz-Attribute).
- `_corr_pearson` ist der gemeinsame Modul-Helfer (die identische
  Agent-Version wurde entfernt).
- `FftGridRegistration`/`RotationFftRegistration` binden jetzt
  `corr_grid_shift` (Modul-Funktion) statt `ProcessingAgent._corr_grid_shift`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, NamedTuple, Protocol

import numpy as np
import structlog
from astropy.io import fits
from scipy.ndimage import (
    center_of_mass,
    gaussian_filter,
    map_coordinates,
    rotate,
    shift as scipy_shift,
)

from ..core.quality import FrameQuality, compute_frame_quality, flag_outliers

logger = structlog.get_logger(__name__)

# Einmal-Warnung (AC-W9-A2: "einmalige Warning ... pro Prozess")
_astroalign_checked = False
_astroalign_available = False
_astroalign_module: Any | None = None


class AstroalignResult(NamedTuple):
    """Ergebnis des astroalign-Wrappers.

    transform: scipy-Transform (oder None bei Fallback) — Mapping-Semantik
        und Anwendung prueft S1-A7 (shift_y = T.translation[1]).
    n_control_points: Anzahl der RANSAC-Kontrollpunkte (None bei Fallback).
        Entspricht len(source_pos) aus astroaligns Rueckgabe
        (T, (source_pos, target_pos)).
    """

    transform: Any
    n_control_points: int | None


class AstroalignUnavailableError(RuntimeError):
    """astroalign ist nicht importierbar (Extra fehlt).

    Der Aufrufer faengt diesen Fehler und nutzt den fft-Fallback. Die
    einmalige `registration.astroalign_unavailable`-Warning wird dabei vom
    Lazy-Import (get_astroalign) bereits emittiert.
    """


@dataclass(frozen=True)
class RegistrationTransform:
    """Registrations-Transform in Pipeline-Konvention (rows, cols).

    Felder (ADR-022, AC-W9-C2-Log):
        method: tatsaechlich verwendete Methode ("fft" | "astroalign" |
            "rotation_fft" — V1.4-2).
        shift_y/shift_x: Translation in Pixeln (rows, cols) — bei astroalign
            ueber ADR-020-Falle (a): shift_y = T.translation[1],
            shift_x = T.translation[0] (Vertauschung = 90-Grad-Fehlshift).
        rotation_deg: Rotation in Grad (fft: 0.0).
        scale: Skalierung (fft: 1.0).
        n_control_points: RANSAC-Kontrollpunkte (fft/rotation_fft: None).
        status: "ok" | "warning" | "fallback" (Diagnose).
        reason: Optionaler Grund (z.B. Sanity-Guard-Verletzung).
        transform: astroalign-SimilarityTransform (fft/rotation_fft: None —
            fft wird als Shift-Vektor angewendet, rotation_fft als
            Rotation+Shift via apply_rotation_shift, nicht als
            Transform-Objekt).
    """

    method: str
    shift_y: float = 0.0
    shift_x: float = 0.0
    rotation_deg: float = 0.0
    scale: float = 1.0
    n_control_points: int | None = None
    status: str = "ok"
    reason: str | None = None
    transform: Any | None = None


class RegistrationSanityError(RuntimeError):
    """Transform verletzt die Sanity-Guards (S1-A7, ADR-019-Ergaenzung).

    |scale - 1| > max_scale_dev ODER |rotation| > max_rotation_deg sind fuer
    Einzel-Stack-Daten nicht plausibel (Dither klein) — der Transform wird
    verworfen und der Aufrufer nutzt den fft-Fallback (Discard-Regel).
    Die Schwellen sind konfigurierbar (RegistrationConfig.max_scale_dev /
    max_rotation_deg, Defaults 0.02 / 2.0 Grad); AZ-Aufnahmen mit echter
    Feldrotation (M27: bis ~7 Grad) erfordern eine erhoehte Rotation-Schwelle.
    """


class RegistrationStrategy(Protocol):
    """Strategy-Interface fuer Registrations-Methoden (ADR-022).

    `compute` erwartet das W11-Hochpass-Mono (ref_mono/tgt_mono wurden bereits
    hochpassgefiltert: mono - gaussian_filter(mono, 30.0)) und liefert einen
    Transform in Pipeline-Konvention (rows, cols).
    """

    def available(self) -> bool: ...

    def compute(self, ref_mono: Any, tgt_mono: Any) -> RegistrationTransform: ...


class FftGridRegistration:
    """fft-Strategie: kapselt `corr_grid_shift` UNVERAENDERT (Modul-Funktion).

    Die grid_shift_fn (der Aufrufer bindet corr_grid_shift, seit Refactor
    2026-08-14 statt ProcessingAgent._corr_grid_shift) liefert
    (beste_corr_hp, shift_y, shift_x) — exakt die v1.1-Signatur. Dadurch
    bleibt der fft-Pfad byte-identisch (AC-W9-C5, AC-W9-B3): diese Klasse
    fuegt KEINE eigene Bildverarbeitung hinzu.

    Der max_control_points-Parameter ist fuer fft ohne Wirkung (nur
    Interface-Konsistenz mit ADR-022).
    """

    def __init__(
        self,
        grid_shift_fn: Callable[[Any, Any], tuple[float, float, float]] | None = None,
        max_control_points: int | None = None,
    ) -> None:
        self._grid_shift_fn = grid_shift_fn
        self._max_control_points = max_control_points

    def available(self) -> bool:
        return True

    def compute(self, ref_mono: Any, tgt_mono: Any) -> RegistrationTransform:
        corr, shift_y, shift_x = self._grid_shift_fn(ref_mono, tgt_mono)
        return RegistrationTransform(
            method="fft",
            shift_y=float(shift_y),
            shift_x=float(shift_x),
            rotation_deg=0.0,
            scale=1.0,
            n_control_points=None,
            status="ok",
            reason=None,
            transform=None,
        )


class AstroalignRegistration:
    """astroalign-Strategie (AC-W9-C1/C3, ADR-022).

    - `available()`: Lazy-Import-Check (get_astroalign); fehlendes Extra ->
      False + einmalige `registration.astroalign_unavailable`-Warning.
    - `compute()`: `astroalign_register` auf dem W11-Hochpass-Mono (der
      Aufrufer hat bereits hochpassgefiltert — AC-W9-C1: astroalign wird
      NICHT mit dem Roh-Mono gefuettert, hal-Review 2026-08-03 /
      15s60-Root-Cause: Vignettierung ohne Flats).
      Mapping auf Pipeline-Konvention (rows, cols):
        shift_y = T.translation[1], shift_x = T.translation[0]
        (ADR-020-Falle a; Vertauschung = 90-Grad-Fehlshift).
        rotation_deg = math.degrees(T.rotation), scale = T.scale.
    - Sanity-Guards (S1-A7): |scale - 1| > max_scale_dev ODER
      |rotation| > max_rotation_deg ->
      `registration.astroalign_sanity_rejected`-Warning +
      RegistrationSanityError (Aufrufer: fft-Fallback). Schwellen sind
      konfigurierbar (Default 0.02 / 2.0 = bisheriges Verhalten).
    """

    def __init__(
        self,
        max_control_points: int | None = None,
        max_rotation_deg: float = 2.0,
        max_scale_dev: float = 0.02,
    ) -> None:
        self._max_control_points = max_control_points
        self._max_rotation_deg = max_rotation_deg
        self._max_scale_dev = max_scale_dev

    def available(self) -> bool:
        try:
            get_astroalign()
            return True
        except AstroalignUnavailableError:
            return False

    def compute(self, ref_mono: Any, tgt_mono: Any) -> RegistrationTransform:
        result = astroalign_register(
            ref_mono, tgt_mono,
            max_control_points=self._max_control_points,
        )
        t = result.transform
        rotation_deg = math.degrees(float(t.rotation))
        scale = float(t.scale)
        if (
            abs(scale - 1.0) > self._max_scale_dev
            or abs(rotation_deg) > self._max_rotation_deg
        ):
            logger.warning(
                "registration.astroalign_sanity_rejected",
                method="astroalign",
                reason=(
                    f"SanityGuard: scale={scale:.4f}, rotation={rotation_deg:.3f}deg "
                    f"(Schwellen: max_scale_dev={self._max_scale_dev}, "
                    f"max_rotation_deg={self._max_rotation_deg}deg)"
                ),
            )
            raise RegistrationSanityError(
                f"astroalign-Transform verletzt Sanity-Guard: "
                f"scale={scale:.4f}, rotation={rotation_deg:.3f}deg "
                f"(Schwellen: max_scale_dev={self._max_scale_dev}, "
                f"max_rotation_deg={self._max_rotation_deg}deg)"
            )
        return RegistrationTransform(
            method="astroalign",
            shift_y=float(t.translation[1]),
            shift_x=float(t.translation[0]),
            rotation_deg=rotation_deg,
            scale=scale,
            n_control_points=result.n_control_points,
            status="ok",
            reason=None,
            transform=t,
        )


# ── Rotation-FFT (V1.4-2) ─────────────────────────────────────────────
# Parameter empirisch validiert (Scratch 2026-08-13):
#   n_angles=1440 -> Winkelaufloesung 360/1440 = 0.25 Grad (coarse).
#   n_radii=512   -> logarithmisches Radius-Sampling (r_min=1.0 bis
#                    diagonale/2); scale-Abschaetzung aus col_shift
#                    (nur Metrik/Guard, wird NICHT angewendet).
_LOG_POLAR_N_ANGLES = 1440
_LOG_POLAR_N_RADII = 512
_LOG_POLAR_R_MIN = 1.0
_ROTATION_REFINE_RADIUS = 3
_ROTATION_REFINE_STEP_DEG = 0.25


def _corr_pearson(a: Any, b: Any) -> float:
    """Pearson-Korrelation mit nan-Normalisierung (konstante Eingaben -> 0.0).

    Gemeinsamer Modul-Helfer fuer das Winkel-Refinement der rotation_fft-
    Strategie, die Grid-Shift-Suche (`corr_grid_shift`) und die
    QC-Messungen in `register_frames`. Seit Refactor 2026-08-14 (Cluster 3)
    ist diese Version die einzige Quelle — die identische Agent-Methode
    (ProcessingAgent._corr_pearson) wurde entfernt.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        c = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
    return c if c == c else 0.0


def _log_polar(
    img: Any,
    n_angles: int = _LOG_POLAR_N_ANGLES,
    n_radii: int = _LOG_POLAR_N_RADII,
) -> Any:
    """Log-Polar-Repraesentation (V1.4-2: Rotation+Scale -> Shift).

    scipy 1.18 stellt KEIN `warp_polar` bereit -> manuell via
    `scipy.ndimage.map_coordinates` (order=1, mode="nearest" — konsistent
    zur Grid-Shift-Suche der Pipeline). Zentrum = Bildmitte
    ((H-1)/2, (W-1)/2); Winkelachse 0..2pi (n_angles, endpoint=False,
    erste Zeile = +x-Achse); Radiusachse log-skaliert von r_min=1.0 bis
    r_max = diagonale/2. Eine Rotation des Bildes um r Grad verschiebt
    die Winkelachse um r/360*n_angles Zeilen; eine Skalierung verschiebt
    die Radiusachse.
    """
    H, W = img.shape
    cy, cx = (H - 1) / 2.0, (W - 1) / 2.0
    r_max = math.hypot(max(cy, H - 1 - cy), max(cx, W - 1 - cx))
    theta = np.linspace(0.0, 2 * np.pi, n_angles, endpoint=False)[:, None]
    r = np.exp(
        np.linspace(math.log(_LOG_POLAR_R_MIN), math.log(r_max), n_radii)
    )[None, :]
    yy = cy + r * np.sin(theta)
    xx = cx + r * np.cos(theta)
    return map_coordinates(img, (yy, xx), order=1, mode="nearest", prefilter=False)


def _phase_corr(a: Any, b: Any) -> tuple[float, float]:
    """Phasenkorrelation (row_shift, col_shift) mit Wraparound (V1.4-2).

    Cross-power-Spectrum f1*conj(f2)/|..|; Peak der ifft2-Korrelation.
    Verschiebungen > shape/2 werden negativ aufgeloest (Ringverschiebung
    in der zyklischen Log-Polar-Ebene).
    """
    f1 = np.fft.fft2(a)
    f2 = np.fft.fft2(b)
    cross = f1 * np.conj(f2)
    cross /= np.abs(cross) + 1e-10
    corr = np.fft.ifft2(cross).real
    peak = np.unravel_index(int(np.argmax(corr)), corr.shape)
    rs, cs = float(peak[0]), float(peak[1])
    if rs > corr.shape[0] / 2:
        rs -= corr.shape[0]
    if cs > corr.shape[1] / 2:
        cs -= corr.shape[1]
    return rs, cs


class RotationFftRegistration:
    """rotation_fft-Strategie (V1.4-2): Log-Polar-FFT-Rotation.

    - `available()`: immer True (nur numpy/scipy, keine Optional-
      Abhaengigkeit).
    - `compute()`: Rotation via FFT-Phasenkorrelation im Log-Polar-Raum,
      Winkel-Refinement (Pearson-Grid ±3 x 0.25 Grad um den coarse-Wert),
      Translation via der gebundenen grid_shift_fn auf dem derotierten
      Hochpass-Mono (dieselbe korrelationsbasierte Grob-zu-Fein-Suche wie
      der fft-Pfad).
    - Konvention (empirisch verifiziert, Scratch 2026-08-13):
        rotation_deg = +row_shift * (360 / n_angles) — der gemessene Winkel
            ist die Rotation des Targets relativ zur Referenz; die Anwendung
            dreht um -rotation_deg zurueck (apply_rotation_shift).
        scale = exp(col_shift * dlog) — nur Metrik/Guard, die Skala wird
            NICHT auf die Daten angewendet (nur Rotation + Translation).
    - Sanity-Guards analog AstroalignRegistration: |scale - 1| >
      max_scale_dev ODER |rotation| > max_rotation_deg -> verworfen
      (RegistrationSanityError; Aufrufer: fft-Fallback).
    """

    def __init__(
        self,
        grid_shift_fn: Callable[[Any, Any], tuple[float, float, float]] | None = None,
        max_rotation_deg: float = 2.0,
        max_scale_dev: float = 0.02,
        n_angles: int = _LOG_POLAR_N_ANGLES,
        n_radii: int = _LOG_POLAR_N_RADII,
        refine_radius: int = _ROTATION_REFINE_RADIUS,
        refine_step_deg: float = _ROTATION_REFINE_STEP_DEG,
    ) -> None:
        self._grid_shift_fn = grid_shift_fn
        self._max_rotation_deg = max_rotation_deg
        self._max_scale_dev = max_scale_dev
        self._n_angles = n_angles
        self._n_radii = n_radii
        self._refine_radius = refine_radius
        self._refine_step_deg = refine_step_deg

    def available(self) -> bool:
        return True

    def compute(self, ref_mono: Any, tgt_mono: Any) -> RegistrationTransform:
        if self._grid_shift_fn is None:
            raise ValueError(
                "rotation_fft benoetigt grid_shift_fn (der Aufrufer bindet "
                "corr_grid_shift) fuer die Translationssuche"
            )
        # Phase 1: Rotation (Log-Polar-Phasenkorrelation).
        ref_lp = _log_polar(ref_mono, self._n_angles, self._n_radii)
        tgt_lp = _log_polar(tgt_mono, self._n_angles, self._n_radii)
        rs, cs = _phase_corr(ref_lp, tgt_lp)
        coarse = rs * 360.0 / self._n_angles
        # scale-Abschaetzung (nur Metrik/Guard; NICHT angewendet).
        H, W = ref_mono.shape
        cy, cx = (H - 1) / 2.0, (W - 1) / 2.0
        r_max = math.hypot(max(cy, H - 1 - cy), max(cx, W - 1 - cx))
        dlog = (math.log(r_max) - math.log(_LOG_POLAR_R_MIN)) / (self._n_radii - 1)
        scale = float(math.exp(cs * dlog))
        # Phase 2: Winkel-Refinement (Pearson-Grid um den coarse-Wert).
        grid = [
            coarse + i * self._refine_step_deg
            for i in range(-self._refine_radius, self._refine_radius + 1)
        ]
        best_a, best_c = coarse, -1e9
        for a in grid:
            rot = rotate(tgt_mono, -a, reshape=False, order=3, mode="nearest")
            c = _corr_pearson(rot, ref_mono)
            if c > best_c:
                best_c, best_a = c, float(a)
        # Phase 3: Sanity-Guard auf dem Ergebnis (refined angle + scale).
        if (
            abs(scale - 1.0) > self._max_scale_dev
            or abs(best_a) > self._max_rotation_deg
        ):
            logger.warning(
                "registration.rotation_fft_sanity_rejected",
                method="rotation_fft",
                reason=(
                    f"SanityGuard: scale={scale:.4f}, rotation={best_a:.3f}deg "
                    f"(Schwellen: max_scale_dev={self._max_scale_dev}, "
                    f"max_rotation_deg={self._max_rotation_deg}deg)"
                ),
            )
            raise RegistrationSanityError(
                f"rotation_fft-Transform verletzt Sanity-Guard: "
                f"scale={scale:.4f}, rotation={best_a:.3f}deg "
                f"(Schwellen: max_scale_dev={self._max_scale_dev}, "
                f"max_rotation_deg={self._max_rotation_deg}deg)"
            )
        # Phase 4: Translation auf dem derotierten Hochpass-Mono.
        rotated = rotate(tgt_mono, -best_a, reshape=False, order=3, mode="nearest")
        _corr, shift_y, shift_x = self._grid_shift_fn(ref_mono, rotated)
        return RegistrationTransform(
            method="rotation_fft",
            shift_y=float(shift_y),
            shift_x=float(shift_x),
            rotation_deg=best_a,
            scale=scale,
            n_control_points=None,
            status="ok",
            reason=None,
            transform=None,
        )


def get_astroalign(force: bool = False) -> Any:
    """Lazy-Import von astroalign (AC-W9-A2).

    - Erfolgt NUR beim ersten Aufruf (Prozess-Cache).
    - Fehlt das Paket: einmalige Warning `registration.astroalign_unavailable`
      (per structlog, inkl. Installations-Hinweis) und kein Wiederholen in
      diesem Prozess — das Fehlen wird gecacht (identisches Verhalten zu
      v1.1, nur eben mit der einmaligen Diagnose-Warning).
    - Wirft AstroalignUnavailableError, damit der Aufrufer den fft-Fallback
      aktivieren kann.

    `force` wird von Tests genutzt (Cache zuruecksetzen).
    """
    global _astroalign_checked, _astroalign_available, _astroalign_module
    if force:
        _astroalign_checked = False
        _astroalign_available = False
        _astroalign_module = None

    if _astroalign_checked:
        if _astroalign_available:
            return _astroalign_module
        raise AstroalignUnavailableError(
            "astroalign nicht verfuegbar (Extra fehlt)")

    try:
        # Lazy-Import gewollt (AC-W9-A2); astroalign hat keine py.typed-Marker
        import astroalign  # type: ignore[import-untyped]
        _astroalign_module = astroalign
        _astroalign_available = True
    except ImportError:
        _astroalign_available = False
        logger.warning(
            "registration.astroalign_unavailable",
            detail=(
                "astroalign ist nicht installiert. W9-Registration nutzt "
                'den fft-Fallback. Installation: pip install "astra[astroalign]"'
            ),
        )
    finally:
        _astroalign_checked = True

    if _astroalign_available:
        return _astroalign_module
    raise AstroalignUnavailableError(
        "astroalign nicht verfuegbar (Extra fehlt)")


def _astroalign_fallback_errors(aa: Any) -> tuple[type[BaseException], ...]:
    """Fehlerklassen der Fallback-Kette (AC-W9-C3, ADR-019).

    Die Klasse MaxIterError existiert erst ab astroalign 2.x als Modul-
    Attribut; fuer aeitere/abweichende Versionen greift der Type-Error-
    Fallback (keyboardinterrupt/opcode-Ruhe; der Aufrufer faengt zusaetzlich
    generische Exception, siehe astroalign_register).
    """
    max_iter_error = getattr(aa, "MaxIterError", None)
    errors: list[type[BaseException]] = [ValueError]
    if max_iter_error is not None:
        errors.append(max_iter_error)
    errors.append(TypeError)
    return tuple(errors)


def _reset_astroalign_cache() -> None:
    """Setzt den Lazy-Import-Cache zurueck (nur fuer Tests)."""
    global _astroalign_checked, _astroalign_available, _astroalign_module
    _astroalign_checked = False
    _astroalign_available = False
    _astroalign_module = None


def astroalign_register(
    ref_mono: Any,
    tgt_mono: Any,
    max_control_points: int | None = None,
) -> AstroalignResult:
    """Registriert tgt_mono gegen ref_mono via astroalign (fehlertolerant).

    Parameter:
        ref_mono: Referenz-Mono-Frame (2D, float). Konsistenz mit S1-A7:
            W11-Hochpass-Input (ref_mono - gaussian_filter(ref_mono, 30.0)).
        tgt_mono: Zu registrierender Mono-Frame (2D, float).
        max_control_points: RANSAC-Limit (flux-sortiert, hellste zuerst).
            **Spike-Befund 1 (AC-W9-B4):** `None` wird hier EXPLIZIT in den
            astroalign-Default 50 uebersetzt — `max_control_points=None` an
            die API durchreichen wuerde als `array[:None]` = ALLE Punkte
            interpretiert (M13-Fehl-Asterismen-Risiko, OQ-W9-4). `null` wird
            also NIEMALS an die API durchgereicht.

    Rueckgabe:
        AstroalignResult(transform, n_control_points).

    Fehlerverhalten (AC-W9-A2/C3):
        - astroalign fehlt (ImportError) -> AstroalignUnavailableError
          (Warning wurde vom Lazy-Import emittiert; Aufrufer: fft-Fallback).
        - <3 Sterne (ValueError), MaxIterError, TypeError oder sonstige
          Fehler -> Warning `registration.astroalign_fallback` (reason) +
          erneutes Werfen; Aufrufer: fft-Fallback.
    """
    try:
        aa = get_astroalign()
    except AstroalignUnavailableError:
        raise
    effective_max_control_points = max_control_points or 50
    try:
        transform, (source_pos, _) = aa.find_transform(
            tgt_mono, ref_mono,
            max_control_points=effective_max_control_points,
        )
    except _astroalign_fallback_errors(aa) as exc:  # noqa: PERF203 - tuple ok
        logger.warning(
            "registration.astroalign_fallback",
            method="astroalign",
            reason=f"{type(exc).__name__}: {exc}",
        )
        raise
    except Exception as exc:  # noqa: BLE001 - unbekannte astroalign-Fehler
        logger.warning(
            "registration.astroalign_fallback",
            method="astroalign",
            reason=f"{type(exc).__name__}: {exc}",
        )
        raise
    return AstroalignResult(transform=transform, n_control_points=len(source_pos))


def create_registration(
    method: str,
    max_control_points: int | None = None,
    grid_shift_fn: Callable[[Any, Any], tuple[float, float, float]] | None = None,
    max_rotation_deg: float = 2.0,
    max_scale_dev: float = 0.02,
) -> RegistrationStrategy:
    """Dispatcher (ADR-022): erzeugt die Registrations-Strategie.

    `grid_shift_fn` wird vom Aufrufer gebunden (corr_grid_shift, seit
    Refactor 2026-08-14 Modul-Funktion in diesem Modul statt
    ProcessingAgent._corr_grid_shift), damit der fft-Pfad byte-identisch
    bleibt (AC-W9-C5, AC-W9-B3). Fuer astroalign hat sie keine Bedeutung;
    fuer rotation_fft (V1.4-2) wird sie fuer die Translationssuche nach der
    Derotation gebunden.
    `max_rotation_deg`/`max_scale_dev` sind die SanityGuard-Schwellen
    (Defaults 2.0 / 0.02 = bisheriges Verhalten); fuer fft ohne Wirkung.
    """
    if method == "fft":
        return FftGridRegistration(
            grid_shift_fn=grid_shift_fn,
            max_control_points=max_control_points,
        )
    if method == "astroalign":
        return AstroalignRegistration(
            max_control_points=max_control_points,
            max_rotation_deg=max_rotation_deg,
            max_scale_dev=max_scale_dev,
        )
    if method == "rotation_fft":
        # V1.4-2: Log-Polar-FFT-Rotation (AZ-Feldrotation). grid_shift_fn
        # wird fuer die Translationssuche nach der Derotation gebunden.
        return RotationFftRegistration(
            grid_shift_fn=grid_shift_fn,
            max_rotation_deg=max_rotation_deg,
            max_scale_dev=max_scale_dev,
        )
    raise ValueError(f"Unbekannte Registrations-Methode: {method!r}")


def _apply_registration_transform(
    data: Any,
    transform: Any,
    ref_mono: Any,
    fill_value: float = 0.0,
) -> Any:
    """Wendet einen astroalign-SimilarityTransform auf Daten an (ADR-020).

    - Falle (b): Transform als GANZES anwenden (Rotation um den Ursprung) —
      nie dekomponieren/neu komponieren. `apply_transform` liefert ein Tuple
      (aligned, footprint) — footprint wird destructuret (Spike-Befund 3).
    - Falle (c): bei RGB pro Kanal anwenden (find_transform lief auf Mono).
    - Edge-Semantik Intra: fill_value=0.0 (cval) — Pixel ausserhalb des Bilds
      werden schwarz (konsistent mit dem fft-Pfad scipy_shift(...,
      mode='constant', cval=0.0)). Cross (S1-A8, AC-W9-D1) nutzt denselben
      Helper ebenfalls mit fill_value=0.0: astroalign.apply_transform kennt
      nur konstanten Rand (kein mode='nearest' wie beim Cross-fft-Pfad);
      Randeruhe ist fuer die korr_hp-Arbitration unkritisch (Sterne liegen
      im Bildzentrum, QF-C-Szenen).
    - transform=None -> unveraenderte Daten (kein astroalign-Transform).
    """
    if transform is None:
        return data
    aa = get_astroalign()
    if data.ndim == 3:
        channels = []
        for c in range(data.shape[-1]):
            aligned, _footprint = aa.apply_transform(
                transform, data[..., c], ref_mono, fill_value=fill_value,
            )
            channels.append(aligned)
        return np.stack(channels, axis=-1)
    aligned, _footprint = aa.apply_transform(
        transform, data, ref_mono, fill_value=fill_value,
    )
    return aligned


def apply_rotation_shift(
    data: Any,
    rotation_deg: float,
    shift_y: float,
    shift_x: float,
) -> Any:
    """Wendet einen rotation_fft-Transform (Rotation + Shift) auf Daten an.

    - Rotation: `scipy.ndimage.rotate` um `-rotation_deg` (Rueckdrehung des
      Targets in die Referenz-Orientierung; Vorzeichen empirisch verifiziert,
      Scratch 2026-08-13), reshape=False, order=3, mode="nearest"
      (konsistent zum fft-Pfad, hal AQ5 — keine scharfen Kanten durch
      negative kalibrierte Pixel).
    - Shift: `scipy.ndimage.shift`, order=3, mode="nearest" (identische
      Semantik zum fft-Anwendungszweig im Agent).
    - ADR-020-Falle (c): bei RGB pro Kanal anwenden (die Strategie rechnete
      auf Mono).
    """
    if data.ndim == 3:
        channels = []
        for c in range(data.shape[-1]):
            rotated = rotate(
                data[..., c], -rotation_deg, reshape=False, order=3,
                mode="nearest",
            )
            channels.append(
                scipy_shift(rotated, (shift_y, shift_x), order=3, mode="nearest")
            )
        return np.stack(channels, axis=-1)
    rotated = rotate(data, -rotation_deg, reshape=False, order=3, mode="nearest")
    return scipy_shift(rotated, (shift_y, shift_x), order=3, mode="nearest")


# ── Refactor 2026-08-14 (Cluster 3): Agent-Registrierungs-Methoden ──
# moved from processing_agent.py — KEINE Verhaltensaenderung; nur
# Aufruf-Konvention (explizite Parameter statt Instanz-Attribute).


class RegisterFramesResult(NamedTuple):
    """Ergebnis von `register_frames` inkl. Registrierungs-Zustand.

    Der Agent haelt die `_last_*`-Zustandsattribute (`_last_frame_qualities`,
    `_last_frame_rejected`, `_last_registration_metrics`); als Modul-Funktion
    (core/ importiert nie agents/) gibt `register_frames` die Metriken mit
    zurueck, der Aufrufer schreibt sie danach in seine Attribute. Die
    V1.3-3-Reset-Semantik (Reset VOR dem Early-Return-Guard) steckt im
    Rueckgabe-Zustand: leere Frames -> leerer Zustand, nie stale Werte.
    """

    registered: List[Path]
    last_frame_qualities: List[FrameQuality]
    last_frame_rejected: int
    last_registration_metrics: dict


@dataclass
class RegistrationResult:
    """Ergebnis einer Cross-Group-Registration (Pass 2, CR-001 P3 + W1/W2).

    Attributes:
        path: Pfad zum aligned FITS (04_stacked/aligned.fits).
        shift_y: Angewendeter y-Shift in Pixeln (Hochpass+Grid, W1).
        shift_x: Angewendeter x-Shift in Pixeln (Hochpass+Grid, W1).
        correlation: Post-shift Korrelation auf Roh-Mono (np.corrcoef,
                     Diagnosefeld corr_roh — W2).
        corr_hp: Post-shift Korrelation auf Hochpass-Mono (sigma=30) —
                 Hauptmetrik (W2), Basis für status und Zero-Shift-Fallback (W1).
        status: "ok" wenn corr_hp >= 0.3, sonst "warning" (warn_only,
                kein Abbruch — AC-P3-3, W1/W2).
        status_reasons: Diagnose-Gruende (V1.4-20, additiv): Liste von
                  {"low_corr_roh", "few_control_points",
                  "unexpected_rotation"} — corr_hp allein kann eine
                  falsche Transformation durchlassen (LDN-935-Fall:
                  corr_hp 0.538, aber corr_roh 0.005, n_CP 23,
                  Rotation 2.26° bei EQ). Der status bleibt
                  rueckwaertskompatibel corr_hp-basiert; die Gruende
                  dokumentieren die Qualitaet zusaetzlich und werden
                  im W3-Gate (apply_cross_group_skip_filter) fuer die
                  Ausschluss-Entscheidung herangezogen.
        method: Tatsaechlich verwendete Registrations-Methode ("fft" |
                "astroalign" | "rotation_fft" — V1.4-2) — W9-D2
                (AC-W9-D2, OQ-W9-5). Bei Zero-Shift-Fallback und
                Fehler-Guards bleibt "fft".
        rotation_deg: Rotation in Grad (fft: 0.0; astroalign:
                      math.degrees(T.rotation), ADR-020-Falle a;
                      rotation_fft: Log-Polar-FFT-Winkel).
        scale: Skalierung (fft: 1.0; astroalign: T.scale;
               rotation_fft: aus Log-Polar-col_shift, nur Metrik).
        n_control_points: RANSAC-Kontrollpunkte (fft/rotation_fft: None).
    """
    path: Path
    shift_y: float = 0.0
    shift_x: float = 0.0
    correlation: float = 0.0
    corr_hp: float = 0.0
    status: str = "ok"
    status_reasons: list[str] = field(default_factory=list)
    method: str = "fft"
    rotation_deg: float = 0.0
    scale: float = 1.0
    n_control_points: int | None = None


# Refactor: moved from processing_agent.py
def register_frames(
    frames: List[Path],
    params: dict,
    is_3d: bool = False,
    registered_dir: Path | None = None,
    load_frame: Callable | None = None,
    save_frame: Callable | None = None,
) -> RegisterFramesResult:
    """Register frames with adaptive channel selection.

    Refactor 2026-08-14 (Cluster 3): als Modul-Funktion aus
    ProcessingAgent._register_frames verschoben. `registered_dir`,
    `load_frame` und `save_frame` werden explizit durchgereicht (der Agent
    bindet self.registered_dir / self._load_frame / self._save_frame). Der
    Registrierungs-Zustand (Frame-Qualitaeten, rejected-Zaehler, Metriken)
    wird als `RegisterFramesResult` zurueckgegeben — der Aufrufer schreibt
    die Werte danach in seine `_last_*`-Attribute.
    """
    # V1.3-3 (ray-Review): Reset VOR dem Early-Return-Guard — ein Aufruf
    # mit leeren frames darf NICHT die Metriken des vorherigen Aufrufs
    # stehen lassen (stale _last_*-Attribute; M13-diagnostisch kritisch).
    last_frame_qualities: List[FrameQuality] = []
    last_frame_rejected = 0
    last_registration_metrics: dict = {}
    if not frames:
        return RegisterFramesResult(
            registered=[],
            last_frame_qualities=last_frame_qualities,
            last_frame_rejected=last_frame_rejected,
            last_registration_metrics=last_registration_metrics,
        )

    registered = []
    # V1.3-3 (stella-Befund 4): lokale Zaehler der Registrierungs-
    # Metriken dieses Aufrufs. Wird bei registration.complete
    # zusammengebaut und in das Rueckgabe-Ergebnis geschrieben.
    method_counts: dict[str, int] = {"fft": 0, "astroalign": 0}
    zero_shift_count: int = 0
    corr_hp_values: list[float] = []
    n_control_points_values: list[int] = []
    qualities: List[FrameQuality] = []
    logger.info("registration.start", frames=len(frames), is_3d=is_3d)

    # Reference frame
    ref_data = load_frame(frames[0])

    # Read FILTER from first frame's header for channel selection
    filter_name = ""
    channel_name = "G"
    try:
        with fits.open(frames[0]) as hdul:
            filter_name = hdul[0].header.get("FILTER", "")
    except Exception as e:
        # T5 (E1): kein stiller Fehler — Header lesbar, aber ohne FILTER
        logger.warning("processing.frame_header_read_failed",
                       path=str(frames[0]), error=str(e))

    if is_3d:
        # Select best channel for registration (W11: force G-channel for consistency with W12/W14)
        ref_mono, channel_name = select_registration_channel(ref_data, filter_name, force_g_channel=True)
        logger.info("registration.channel_selected", filter=filter_name, channel=channel_name)
    else:
        ref_mono = ref_data

    # W9-C (AC-W9-C1/C3, ADR-022): Registrations-Strategie. Bei
    # method="fft" (Default) bleibt das v1.1-Verhalten byte-identisch
    # (AC-W9-C5): der fft-Zweig wird nur in die Strategy gekapselt, ohne
    # eigene Bildverarbeitung (corr_grid_shift wird unverändert gerufen).
    reg_cfg = params.get("registration", {}) or {}
    # Test-Kompatibilitaet: falls params selbst die reg_cfg ist (method direkt)
    if not reg_cfg and isinstance(params, dict) and "method" in params:
        reg_cfg = params
    reg_method = reg_cfg.get("method", "fft") or "fft"
    # V19-REG-SMART E4: Warning bei fft auf AZ mit langer Belichtung (>=45s)
    try:
        _mt = params.get("mount_type", "eq") if isinstance(params, dict) else "eq"
        if _mt == "eq" and isinstance(params.get("equipment"), dict):
            _mt = params["equipment"].get("mount_type", _mt)  # type: ignore
        if _mt == "eq" and reg_cfg.get("mount_type"):
            _mt = reg_cfg.get("mount_type", _mt)  # type: ignore
        _mexp = params.get("max_exptime", 0) if isinstance(params, dict) else 0
        if _mexp == 0 and reg_cfg.get("max_exptime") is not None:
            _mexp = reg_cfg.get("max_exptime", 0)  # type: ignore
        _thr = reg_cfg.get("max_exptime_fft_warn", 45)  # type: ignore
        try:
            _thr_f = float(_thr)
            _mexp_f = float(_mexp) if _mexp is not None else 0.0
        except Exception:
            _thr_f = 45.0
            _mexp_f = 0.0
        if reg_method == "fft" and _mt == "az" and _mexp_f >= _thr_f:  # type: ignore
            logger.warning(
                "registration.fft_on_az_mount",
                method=reg_method,
                mount_type=_mt,
                exptime=_mexp_f,
                threshold=_thr_f,
                detail=(
                    f"FFT-Registrierung auf AZ-Mount mit {_mexp_f}s Belichtung — "
                    f"Feldrotation nicht korrigierbar (Threshold: {_thr_f}s). "
                    f"Erwartet: Ghosting an Bildraendern, Stern-Doppelkonturen (rotation_deg 0.0 ist FFT-Artefakt). "
                    f"Loesung: --registration-method astroalign --max-rotation 15 "
                    f"oder Equipment-Profil mit preferred_registration: astroalign"
                ),
            )
    except Exception:
        pass
    strategy = create_registration(
        reg_method,
        reg_cfg.get("max_control_points"),
        grid_shift_fn=corr_grid_shift,
        max_rotation_deg=reg_cfg.get("max_rotation_deg", 2.0),
        max_scale_dev=reg_cfg.get("max_scale_dev", 0.02),
    )
    # available() emittiert die einmalige astroalign_unavailable-Warning,
    # wenn das Extra fehlt (nur wenn method == "astroalign" geprüft wird).
    use_astroalign = reg_method == "astroalign" and strategy.available()

    # RE-F (V1.3-24, AC-RE-F3): W1-Guard-Parameter aus der effektiven
    # Registrations-Config (Default 0.0 = Guard praktisch deaktiviert:
    # Fallback/Reject greift nur bei corr_hp < 0.0, d.h. praktisch nie;
    # Werte > 0 bewusst setzen, um den W1-Guard (RE-F, V1.3-24) zu
    # aktivieren).
    zero_shift_threshold = float(reg_cfg.get("zero_shift_threshold", 0.0))
    zero_shift_fallback_enabled = bool(reg_cfg.get("zero_shift_fallback", True))

    # Save reference
    ref_out = registered_dir / "reg_0000.fits"
    save_frame(ref_data, ref_out)
    registered.append(ref_out)

    # W11 (CR-001, AC-W11-1): Referenz-Hochpass einmal berechnen
    # (unverändert über alle Frames). Shift pro Frame auf demselben
    # Hochpass-Mono via corr_grid_shift (W1-Methode: korrelationsbasierte
    # Grob-zu-Fein-Suche, Kriterium corr_hp). Ersetzt
    # compute_shift_star_centroid (CoM Top-0.1%), dessen Jitter die
    # Einzel-Stacks verschmierte (F.6: Rest-Shift median (5,−5), p95 bis
    # 14.8 px → Ghosting in 60s40/15s60).
    ref_hp = ref_mono - gaussian_filter(ref_mono, 30.0)

    # W12 (AC-W12-1): QC-Referenz auf G-Kanal (höchste QE bei OSC;
    # Luminance verwässert durch schwächere R/B-Kanäle). Die
    # Shift-Berechnung bleibt auf dem Registrations-Mono (Luminance für
    # broadband) — nur die QC-Messung (corr_hp, Fallback-Entscheidung)
    # nutzt G. Für 2D (kein Debayer) ist Mono das G-Äquivalent.
    if is_3d and ref_data.shape[-1] == 3:
        g_ref = ref_data[:, :, 1]
        g_ref_hp = g_ref - gaussian_filter(g_ref, 30.0)
    else:
        g_ref = ref_mono
        g_ref_hp = ref_hp

    # QF-B (AC-QF-B1): Qualitaets-Metriken des Referenz-Frames auf dem
    # Registrations-Kanal. correlation bleibt None (keine Shift-Metrik
    # fuer die Referenz). Fehler -> leere Metrik + Warning, nie Abbruch.
    try:
        ref_quality = compute_frame_quality(ref_mono)
        ref_quality.frame = str(frames[0])
    except Exception as e:  # noqa: BLE001 - QF darf die Registration nie stoppen
        logger.warning("quality.compute_failed", path=str(frames[0]),
                       frame=0, error=str(e))
        ref_quality = FrameQuality(frame=str(frames[0]))
    qualities.append(ref_quality)

    # Register each subsequent frame
    for i, frame_path in enumerate(frames[1:], 1):
        try:
            target_data = load_frame(frame_path)
        except Exception as e:
            # T5 (E1): Einzelframe unlesbar -> skip + warning (analog debayer)
            logger.warning("processing.frame_failed", path=str(frame_path),
                           frame=i, error=str(e), reason="load_failed")
            continue
        target_mono = select_registration_channel(target_data, filter_name, force_g_channel=True)[0] if is_3d else target_data

        # QF-B (AC-QF-B1): Frame-Metriken auf dem Registrations-Kanal
        # (nach Kalibration — Frames sind hier bereits kalibriert).
        # correlation wird nach der finalen corr_hp-Messung gefuellt.
        try:
            target_quality = compute_frame_quality(target_mono)
            target_quality.frame = str(frame_path)
        except Exception as e:  # noqa: BLE001 - QF darf die Registration nie stoppen
            logger.warning("quality.compute_failed", path=str(frame_path),
                           frame=i, error=str(e))
            target_quality = FrameQuality(frame=str(frame_path))
        qualities.append(target_quality)

        # W11: Shift auf hochpassgefiltertem Mono (Grid, corr_hp-Kriterium)
        tgt_hp = target_mono - gaussian_filter(target_mono, 30.0)
        _search_corr, shift_y, shift_x = corr_grid_shift(ref_hp, tgt_hp)

        # W12: corr_hp auf G-Kanal beim ANGEHANDTEN Shift messen (post-shift)
        if is_3d and target_data.shape[-1] == 3:
            g_tgt = target_data[:, :, 1]
        else:
            g_tgt = target_mono
        g_aligned = scipy_shift(g_tgt, (shift_y, shift_x), order=3, mode="nearest")
        corr_hp = _corr_pearson(
            g_aligned - gaussian_filter(g_aligned, 30.0), g_ref_hp,
        )

        # W9-C (AC-W9-C3): Compute-both-Arbitration — bei method="astroalign"
        # wird der astroalign-Transform berechnet und gegen den fft-Transform
        # auf dem G-Kanal-Hochpass verglichen (beide Transforms anwenden,
        # corr_hp messen): astroalign gewinnt nur bei
        # corr_hp_aa >= corr_hp_fft - 0.05 (Toleranz RANSAC-Jitter), sonst
        # fft + Warning registration.astroalign_downgraded.
        # Fallback-Warnings kommen aus der Strategie (astroalign_fallback /
        # astroalign_sanity_rejected / astroalign_unavailable einmalig).
        winner = "fft"
        aa_transform: RegistrationTransform | None = None
        if use_astroalign:
            corr_hp_aa = -1e9
            try:
                aa_transform = strategy.compute(ref_hp, tgt_hp)
                g_aligned_aa = _apply_registration_transform(
                    g_tgt, aa_transform.transform, g_ref,
                )
                corr_hp_aa = _corr_pearson(
                    g_aligned_aa - gaussian_filter(g_aligned_aa, 30.0),
                    g_ref_hp,
                )
            except (AstroalignUnavailableError, RegistrationSanityError):
                # Warnings kamen bereits aus der Strategie; fft gewinnt.
                aa_transform = None
            except Exception:  # noqa: BLE001 - unbekannte astroalign-Fehler -> fft
                aa_transform = None
            if aa_transform is not None and corr_hp_aa >= corr_hp - 0.05:
                winner = "astroalign"
                shift_y, shift_x = aa_transform.shift_y, aa_transform.shift_x
                corr_hp = corr_hp_aa
            elif aa_transform is not None:
                logger.warning(
                    "registration.astroalign_downgraded",
                    frame=i,
                    corr_hp_aa=round(corr_hp_aa, 3),
                    corr_hp_fft=round(corr_hp, 3),
                    tolerance=0.05,
                )

        # W11/W12 Zero-Shift-Guard (AC-W11-2) — RE-F (V1.3-24,
        # AC-RE-F1/F2): methodenbewusst. corr_hp < Schwelle (Default 0.0):
        #   fft-Zweig           -> Shift (0,0) + zero_shift_fallback (v1.2)
        #   astroalign-Gewinner -> Frame VERWERFEN statt zeroshift-stapeln
        #       (kein (0,0)-Transform, kein fälschliches
        #       zero_shift_fallback-Signal; Rejection-Ereignis ist
        #       unterscheidbar — UGC-10822-Beleg: Frames 1-23 hatten
        #       corr_hp_aa 0.14-0.29 trotz gültigem astroalign-Transform).
        # AC-RE-F3: --zero-shift-threshold konfiguriert die Schwelle;
        # --no-zero-shift-fallback deaktiviert den Guard komplett (weder
        # Zero-Shift noch astroalign-Reject — R2-Interpretation).
        if zero_shift_fallback_enabled and corr_hp < zero_shift_threshold:
            if winner == "fft":
                logger.warning("registration.zero_shift_fallback",
                               frame=i, corr_hp=round(corr_hp, 3),
                               threshold=zero_shift_threshold,
                               reason="low_hp_correlation")
                # V1.3-3: Zero-Shift-Fallback-Ereignisse zaehlen
                # (Registrierungs-Metrik — nur im fft-Zweig).
                zero_shift_count += 1
                shift_y, shift_x = 0.0, 0.0
                winner = "fft"
                # QC bei (0,0) neu messen (konsistent: corr_hp = post-shift-Wert)
                g_aligned = g_tgt
                corr_hp = _corr_pearson(
                    g_aligned - gaussian_filter(g_aligned, 30.0), g_ref_hp,
                )
            else:
                # astroalign-Gewinner (AC-RE-F1): Frame verwerfen. Die
                # QF-Metrik bleibt sichtbar (correlation = corr_hp_aa) —
                # der Frame wird nicht registriert (kein aligned.fits).
                logger.warning(
                    "registration.frame_rejected",
                    frame=i,
                    corr_hp=round(corr_hp, 3),
                    threshold=zero_shift_threshold,
                    reason=(
                        "astroalign winner below zero-shift threshold "
                        "(RE-F): low corr_hp on G-channel — transform "
                        "discarded, frame rejected"
                    ),
                )
                qualities[-1].correlation = (
                    round(corr_hp, 4) if corr_hp is not None else None
                )
                last_frame_rejected += 1
                continue

        # QF-B (AC-QF-B1): der Aufrufer fuellt `correlation` (finaler
        # corr_hp, post-shift inkl. Zero-Shift-Fallback) ins FrameQuality.
        qualities[-1].correlation = round(corr_hp, 4) if corr_hp is not None else None
        # V1.3-3: corr_hp je registriertem Frame NACH finaler Messung
        # (Verteilungs-Metrik min/max/median). Nur registrierte Frames
        # erreichen diese Zeile (rejected -> continue oben).
        corr_hp_values.append(round(corr_hp, 4))

        # V1.3-3: gewaehlte Registrations-Methode je registriertem Frame
        # zaehlen (nach W9-C-Arbitration + Zero-Shift-Handling; Zero-Shift
        # setzt winner="fft"; rejected Frames zaehlen nicht).
        method_counts[winner] += 1

        # Apply: astroalign-Transform als Ganzes (ADR-020-Falle b/c,
        # pro Kanal via Helper), sonst fft-Shift (unverändert).
        if winner == "astroalign":
            aligned = _apply_registration_transform(
                target_data, aa_transform.transform, g_ref,
            )
            # V1.3-3: RANSAC-Kontrollpunkte des astroalign-Siegs
            # (n_control_points-Median der Gruppe).
            n_control_points_values.append(aa_transform.n_control_points)
        else:
            # Apply shift to all channels (scipy needs shift per dimension)
            shift_vec = (shift_y, shift_x) + (0,) * (target_data.ndim - 2)
            # mode='nearest' statt 'constant', cval=0.0: verhindert schwarze Ränder
            # bei Subpixel-Shifts, die sich im Average-Stack zu Grid-Artefakten summieren
            aligned = scipy_shift(target_data, shift_vec, order=3, mode='nearest')

        # AC-W9-C2: Transform-Metadaten pro Frame (tatsächlich verwendete
        # Methode — im Mixed-Run diagnostizierbar).
        if winner == "astroalign":
            logger.info(
                "registration.transform",
                frame=i,
                method=winner,
                rotation_deg=round(aa_transform.rotation_deg, 4),
                scale=round(aa_transform.scale, 5),
                shift_y=round(shift_y, 3),
                shift_x=round(shift_x, 3),
                n_control_points=aa_transform.n_control_points,
            )
        else:
            logger.info(
                "registration.transform",
                frame=i,
                method="fft",
                rotation_deg=0.0,
                scale=1.0,
                shift_y=round(shift_y, 3),
                shift_x=round(shift_x, 3),
                n_control_points=None,
            )

        # Save
        out_path = registered_dir / f"reg_{i:04d}.fits"
        save_frame(aligned, out_path)
        registered.append(out_path)

        if i % 5 == 0:
            logger.info("registration.progress", completed=i, total=len(frames),
                        last_corr_hp=round(corr_hp, 3))

    # QF-B (AC-QF-B1/B3): Outlier-Flagging gegen die Gruppen-Statistik
    # (flaggen, nicht verwerfen — Rejection = v1.3+, kein Quality-Gate).
    last_frame_qualities = flag_outliers(qualities) if qualities else []

    # V1.3-3 (stella-Befund 4): Registrierungs-Metriken zusammenbauen.
    # rejected_count uebernimmt den bestehenden inkrementellen Zaehler
    # (last_frame_rejected — Fehlerpfad-identisch, NICHT doppelt zaehlen).
    # `frames_registered` = len(registered) inkl. Referenz; corr_hp-
    # Verteilung nur ueber registrierte Nicht-Referenz-Frames.
    rejected_count = last_frame_rejected
    last_registration_metrics = {
        "method_counts": method_counts,
        "zero_shift_count": zero_shift_count,
        "rejected_count": rejected_count,
        "frames_total": len(frames),
        "frames_registered": len(registered),
        "corr_hp": {
            "count": len(corr_hp_values),
            "min": round(min(corr_hp_values), 4) if corr_hp_values else None,
            "max": round(max(corr_hp_values), 4) if corr_hp_values else None,
            "median": round(float(np.median(corr_hp_values)), 4) if corr_hp_values else None,
        },
        "n_control_points": {
            "count": len(n_control_points_values),
            "median": round(float(np.median(n_control_points_values)), 1) if n_control_points_values else None,
        },
    }

    logger.info("registration.complete", count=len(registered), total=len(frames),
                filter=filter_name, channel=channel_name,
                # V1.3-3: Registrierungs-Metriken additiv (method_counts,
                # zero_shift/rejected-Zaehler, corr_hp-Verteilung,
                # n_control_points-Median — structlog serialisiert dicts).
                registration_metrics=last_registration_metrics)
    return RegisterFramesResult(
        registered=registered,
        last_frame_qualities=last_frame_qualities,
        last_frame_rejected=last_frame_rejected,
        last_registration_metrics=last_registration_metrics,
    )


# Refactor: moved from processing_agent.py
def compute_shift(ref: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    """Sub-pixel shift via phase correlation with Hanning window."""
    h, w = ref.shape

    hanning = np.outer(np.hanning(h), np.hanning(w))
    ref_w = ref * hanning
    tgt_w = target * hanning

    fft_ref = np.fft.fft2(ref_w)
    fft_tgt = np.fft.fft2(tgt_w)

    cross = (fft_ref * fft_tgt.conj()) / (np.abs(fft_ref * fft_tgt.conj()) + 1e-10)
    corr = np.fft.ifft2(cross).real

    # Integer peak
    peak_y = int(np.argmax(corr) // w)
    peak_x = int(np.argmax(corr) % w)

    if peak_y > h // 2: peak_y -= h
    if peak_x > w // 2: peak_x -= w

    shift_y, shift_x = float(peak_y), float(peak_x)

    # 3-point centroid refinement
    iy, ix = int(peak_y) % h, int(peak_x) % w

    if 1 < iy < h - 2:
        denom = corr[iy-1, ix] + corr[iy, ix] + corr[iy+1, ix]
        if abs(denom) > 1e-10:
            shift_y += (corr[iy-1, ix] - corr[iy+1, ix]) / (2*denom - 2*corr[iy, ix])
    if 1 < ix < w - 2:
        denom = corr[iy, ix-1] + corr[iy, ix] + corr[iy, ix+1]
        if abs(denom) > 1e-10:
            shift_x += (corr[iy, ix-1] - corr[iy, ix+1]) / (2*denom - 2*corr[iy, ix])

    return (shift_y, shift_x)


# Refactor: moved from processing_agent.py
def corr_grid_shift(ref_hp: np.ndarray, tgt_hp: np.ndarray) -> tuple[float, int, int]:
    """Korrelationsbasierte Grob-zu-Fein-Suche auf Hochpass (W1, Methode B).

    Mehrstufige (hierarchische) Suche über dieselbe Pearson-Metrik auf
    dem Hochpass-Mono (corr_hp). Referenz-Implementierung ist
    `_work/stella/diag-m13-real-stacks.py` (coarse_grid) — sie liefert die
    bewiesene M13-Ground-Truth ((−2,−12)/0.7504 für 60s40, (2,4)/0.1319 für
    180s60 auf Lauf 074119). Diese Implementierung liefert auf den
    M13-Real-Stacks dieselben Shifts/Korrelationen (verifiziert 2026-08-01).

    Stufen (CR-001 W11, Effizienz-Optimierung):
      L1: 4x-Downsampling, step 5 → 20 px full-res, deckt ±125 px ab.
      L2: 2x-Downsampling, step 2 → 4 px full-res, Fenster ±20 px.
      L3: full-res step 1, Fenster ±2 px.
    Kriterium/Suchbereich identisch zur Vorgänger-Variante (Pearson auf
    Hochpass, ±125 full-res); Laufzeit ~13x geringer (M13-Real-Frames
    540×960: ~1.2 s statt ~15.4 s pro Paar → 43-Frame-Gruppe ~1 min statt
    ~11 min, wiederholbar unter 2–3 min pro Gruppe).

    Hinweis Bereich: ±125 full-res — die Task-Formulierung "+-250 px"
    bezog sich auf den doppelten Pixelmaßstab der half-res-Diagnose;
    ±125 ist die mit den Ground-Truth-Stacks verifizierte Reichweite.

    Args:
        ref_hp: Hochpass-gefiltertes Referenz-Mono (H, W).
        tgt_hp: Hochpass-gefiltertes Target-Mono (H, W).

    Returns:
        (beste_corr_hp, shift_y, shift_x) — Shift in full-res Pixeln,
        angewandt auf das Target.
    """
    def _best_in(level_ref: np.ndarray, level_tgt: np.ndarray,
                 y_range: range, x_range: range,
                 scale: float, order: int = 1) -> tuple[float, int, int]:
        """Brute-Force Pearson über ein Shift-Grid in level-Pixeln.

        Returns (corr, full_res_shift_y, full_res_shift_x). Die
        Korrelationswerte der Stufen sind NICHT untereinander vergleichbar
        (verschiedene Auflösungen) — der best-Wert wird nur innerhalb einer
        Stufe verglichen; das Ergebnis jeder Stufe wird in full-res
        Pixeln zurückgegeben.
        """
        best_c = (-1e9, (0, 0))
        for dy in y_range:
            for dx in x_range:
                a = scipy_shift(level_tgt, (dy / scale, dx / scale),
                                order=order, mode="nearest")
                c = _corr_pearson(a, level_ref)
                if c > best_c[0]:
                    best_c = (c, (dy, dx))
        return best_c[0], best_c[1][0], best_c[1][1]

    # L1: 4x-Downsampling, 20 px full-res-Schritt, deckt ±120 full-res ab
    # (Refine-Fenster ±20 deckt die Rest-5 px bis ±125 mit ab).
    ref4 = ref_hp[::4, ::4]
    tgt4 = tgt_hp[::4, ::4]
    _, by, bx = _best_in(ref4, tgt4, range(-30, 31, 5), range(-30, 31, 5), scale=4)

    # L2: 2x-Downsampling, 4 px full-res-Schritt, Fenster ±20 px um L1-Best
    ref2 = ref_hp[::2, ::2]
    tgt2 = tgt_hp[::2, ::2]
    # y_range/x_range in 2x-Pixeln: 2*by ± 10, step 2 → full-res by*2 ± 20
    _, by2, bx2 = _best_in(
        ref2, tgt2,
        range(2 * by - 10, 2 * by + 11, 2),
        range(2 * bx - 10, 2 * bx + 11, 2),
        scale=2,
    )

    # L3: full-res step 1, Fenster ±2 px um L2-Best
    # -1e9-Start: NICHT den 2x-Grid-Wert übernehmen — die 2x- und
    # full-res-Korrelationen sind nicht vergleichbar skaliert.
    best_f = (-1e9, (by2, bx2))
    for dy in range(by2 - 2, by2 + 3):
        for dx in range(bx2 - 2, bx2 + 3):
            a = scipy_shift(tgt_hp, (dy, dx), order=1, mode="nearest")
            c = _corr_pearson(a, ref_hp)
            if c > best_f[0]:
                best_f = (c, (dy, dx))
    return best_f[0], best_f[1][0], best_f[1][1]


# Refactor: moved from processing_agent.py
def select_registration_channel(
    data: np.ndarray,
    filter_name: str = "",
    force_g_channel: bool = False,
) -> tuple[np.ndarray, str]:
    """Select the best monochrome channel for registration.

    Uses the filter name for known filters (Ha, OIII, Duo-Band, etc.)
    and falls back to signal-based selection for unknown filters.
    Default fallback is G-channel for single-group backward compatibility.

    Args:
        data: (H, W, 3) RGB float32 array
        filter_name: FITS header FILTER value
        force_g_channel: If True, force G-channel selection (used for
            intra-group registration W11 to be consistent with cross-group
            W12 and reference selection W14 which use G-channel QC)

    Returns:
        Tuple of (mono_array, channel_name) where channel_name is one of
        "R", "G", "B", or "Luminance"
    """
    filter_lower = filter_name.strip().lower()

    # Force G-channel if requested (W11 intra-group registration)
    if force_g_channel:
        return (data[:, :, 1], "G")

    # Luminance = robust default for broadband
    luminance = 0.299 * data[:, :, 0] + 0.587 * data[:, :, 1] + 0.114 * data[:, :, 2]

    # Known filter → specific channel selection
    if "duo" in filter_lower or "dual" in filter_lower:
        r_med = float(np.median(data[:, :, 0]))
        g_med = float(np.median(data[:, :, 1]))
        b_med = float(np.median(data[:, :, 2]))
        if r_med >= g_med and r_med >= b_med:
            return (data[:, :, 0], "R")
        return (luminance, "Luminance")

    if "ha" in filter_lower or "h-alpha" in filter_lower:
        return (data[:, :, 0], "R")

    if "oiii" in filter_lower or "o-iii" in filter_lower:
        return ((data[:, :, 1] + data[:, :, 2]) / 2, "Luminance")  # G+B average

    if "sii" in filter_lower or "s-ii" in filter_lower:
        return (data[:, :, 0], "R")

    if filter_lower in ("clear", "l", "luminance", "", "astro"):
        return (luminance, "Luminance")

    # Unknown filter: choose channel with highest median signal
    r_med = float(np.median(data[:, :, 0]))
    g_med = float(np.median(data[:, :, 1]))
    b_med = float(np.median(data[:, :, 2]))

    medians = {"R": r_med, "G": g_med, "B": b_med}
    best_channel = max(medians, key=medians.get)

    if best_channel == "R":
        return (data[:, :, 0], "R")
    elif best_channel == "B":
        return (data[:, :, 2], "B")
    else:
        # Default fallback: G-channel (backward compatibility for single-group)
        return (data[:, :, 1], "G")


# Refactor: moved from processing_agent.py
def compute_shift_star_centroid(
    ref: np.ndarray,
    target: np.ndarray,
) -> tuple[float, float]:
    """Compute shift using star centroiding, with phase correlation fallback.

    Thresholds on top 0.1% brightest pixels and computes center of mass.
    Falls back to phase correlation (compute_shift) if fewer than 10
    pixels pass the threshold in either frame.

    Args:
        ref: Reference monochrome frame (H, W)
        target: Target monochrome frame to align (H, W)

    Returns:
        (shift_y, shift_x) in pixels
    """
    thresh_ref = float(np.percentile(ref, 99.9))
    thresh_tgt = float(np.percentile(target, 99.9))

    mask_ref = ref > thresh_ref
    mask_tgt = target > thresh_tgt

    n_ref = int(np.sum(mask_ref))
    n_tgt = int(np.sum(mask_tgt))

    if n_ref >= 10 and n_tgt >= 10:
        cy_ref, cx_ref = center_of_mass(mask_ref)
        cy_tgt, cx_tgt = center_of_mass(mask_tgt)
        shift_y = float(cy_tgt - cy_ref)
        shift_x = float(cx_tgt - cx_ref)
        logger.info("registration.centroid_shift", shift_y=round(shift_y, 3),
                    shift_x=round(shift_x, 3), ref_pixels=n_ref, target_pixels=n_tgt)
        return (shift_y, shift_x)

    # Fallback to phase correlation
    logger.info("registration.centroid_fallback", reason="too_few_bright_pixels",
                ref_pixels=n_ref, target_pixels=n_tgt)
    return compute_shift(ref, target)
