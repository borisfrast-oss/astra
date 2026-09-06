"""Plugin interface for optional pipeline steps (v1.2, PL-A).

Astra 1.2 fuehrt einen minimalen, stabilen Erweiterungspunkt fuer optionale
Pipeline-Steps ein (v12-plugin-interface.md): Ein Plugin ist ein
deterministischer Step-Handler mit eindeutigem Namen, der ueber Python-
Entry-Points der Gruppe ``astra.plugins`` oder direkt (Test-Hook,
AC-PL-A3) registriert wird.

Scope (OQ-PL-1-A, verbindlich):
- Nur Step-Handler-Plugins. Kein Hook-System, keine CLI-Erweiterung.
- Registry-Load ist lazy (nur bei Bedarf) — kein Startup-Overhead
  (Annahme 2).
- Plugin-Fehler sind Fehler des Aufrufers: Warning + Skip, nie Abbruch
  (OQ-PL-4, E1). Plugins werfen nicht; Fehler werden als
  ``PluginResult(ok=False)`` gemeldet.

Stdlib-only (AC-PL-A1): importlib.metadata, abc, dataclasses.
"""

from __future__ import annotations

import importlib.metadata
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from astro_process.config.models import ProcessingParams

logger = structlog.get_logger(__name__)

# Entry-Point-Gruppe fuer Pipeline-Step-Plugins (OQ-PL-2, verbindlich).
PLUGIN_ENTRY_POINT_GROUP = "astra.plugins"


@dataclass
class PluginResult:
    """Ergebnis eines Plugin-Laufs (bewusst klein, einmal eingefroren).

    ok:         True = Schritt erfolgreich; False = Fehler (der Aufrufer
                warnt und ueberspringt — OQ-PL-4, E1).
    step:       Der verarbeitete Step-Name (Validierung gegen handles()).
    artifact:   Optionaler Pfad zum erzeugten Artefakt (z.B. Marker-FITS).
    log_fields: Zusaetzliche strukturierte Log-Felder fuer den Aufrufer.
    """

    ok: bool
    step: str
    artifact: Path | None = None
    log_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginContext:
    """Schlanker, dokumentierter Kontext fuer Plugin-Laeufe (AC-PL-A1).

    Bewusst KEIN zweites Pipeline-Framework: nur Pfade, Parameter und ein
    Logger. Der Kern entscheidet weiterhin ueber Verzeichnisse, Lifecycle
    und Fehlerbehandlung.
    """

    working_dir: Path
    output_dir: Path
    processing_params: ProcessingParams | None = None
    target_name: str = ""
    # Additives, optionales Feld (PluginContext-Amendment 2026-08-05,
    # v12-plugin-interface.md / SE-B): Step-Konfiguration des aktuellen
    # Preset-Steps (PipelineStep.params, models.py). Default {} =
    # rueckwaertskompatibel; bestehende Plugin-Tests unveraendert.
    # F-SE-1.2 liest hier radius/amount (SE-C).
    step_params: dict[str, Any] = field(default_factory=dict)
    logger: Any = field(
        default_factory=lambda: structlog.get_logger("astra.plugin")
    )


class Plugin(ABC):
    """ABC fuer Pipeline-Step-Plugins (AC-PL-A1).

    Implementierungen sind deterministische Step-Handler: ``handles()``
    deklariert den Step, ``run()`` fuehrt ihn aus. Fehler werden NICHT
    geworfen, sondern als ``PluginResult(ok=False)`` gemeldet (OQ-PL-4:
    Warning + Skip, nie Abbruch).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Eindeutiger Plugin-Name (Dedup-Schluessel der Registry)."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin-Version (z.B. fuer ``astra plugin list``)."""

    @abstractmethod
    def handles(self, step_name: str) -> bool:
        """True, wenn dieses Plugin den Step ``step_name`` verarbeitet."""

    @abstractmethod
    def run(self, context: PluginContext) -> PluginResult:
        """Fuehrt den Schritt aus. Wirft nicht — Fehler via ok=False."""


class PluginRegistry:
    """Registry fuer Pipeline-Step-Plugins (AC-PL-A2/A3).

    - Laedt Entry-Points der Gruppe ``astra.plugins`` LAZY (nur wenn
      ``plugins``/``resolve_step`` erstmals angefragt werden).
    - Dedupliziert nach ``name``: erste Registrierung gewinnt, spaetere
      werden mit Warning verworfen (AC-PL-A2).
    - Erlaubt injizierte Instanzen (Test-Hook, AC-PL-A3) — injizierte
      Instanzen werden VOR Entry-Points registriert und gewinnen daher.
    """

    def __init__(self, injected: Iterable[Plugin] | None = None) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._loaded = False
        for plugin in injected or ():
            self.register(plugin)

    def register(self, plugin: Plugin) -> None:
        """Registriert ``plugin``; Duplikat-Namen -> erste gewinnt (AC-PL-A2)."""
        if plugin.name in self._plugins:
            logger.warning(
                "plugins.duplicate_name",
                name=plugin.name,
                version=plugin.version,
                msg="Plugin name already registered — first registration wins",
            )
            return
        self._plugins[plugin.name] = plugin

    def _ensure_loaded(self) -> None:
        """Laedt Builtin-Plugins + Entry-Points einmalig (lazy). Fehler -> Warning.

        Reihenfolge (AC-PL-A2, DEF-013):
        1. ``_register_builtin_plugins`` — direkt registrierte Produktiv-Plugins
           (structure_enhancement); lazy Import vermeidet zirkulaere Abhaengigkeit.
        2. Entry-Points der Gruppe ``astra.plugins`` — werden nach den Builtins
           registriert; Duplikate (gleicher Name) -> erste gewinnt + Warning.
        """
        if self._loaded:
            return
        self._loaded = True
        # Schritt 1: Builtin-Plugins (lazy, DEF-013 Zirkular-Import-Fix)
        _register_builtin_plugins(self)
        # Schritt 2: Entry-Points (Duplikate nach Builtins werden verworfen)
        try:
            entry_points = importlib.metadata.entry_points(
                group=PLUGIN_ENTRY_POINT_GROUP
            )
        except Exception as e:  # noqa: BLE001 - Discovery-Fehler sind Warnungen (E1)
            logger.warning("plugins.entry_points_discovery_failed", error=str(e))
            return
        for ep in entry_points:
            plugin = self._load_entry_point(ep)
            if plugin is not None:
                self.register(plugin)

    def _load_entry_point(
        self, ep: importlib.metadata.EntryPoint
    ) -> Plugin | None:
        """Laedt einen Entry-Point zu einer Plugin-Instanz (oder None)."""
        try:
            loaded = ep.load()
        except Exception as e:  # noqa: BLE001 - defektes Plugin stoppt den Kern nicht
            logger.warning(
                "plugins.entry_point_load_failed", name=ep.name, error=str(e)
            )
            return None
        if isinstance(loaded, type) and issubclass(loaded, Plugin):
            try:
                return loaded()
            except Exception as e:  # noqa: BLE001 - defekte Factory stoppt den Kern nicht
                logger.warning(
                    "plugins.entry_point_instantiation_failed",
                    name=ep.name,
                    error=str(e),
                )
                return None
        if isinstance(loaded, Plugin):
            return loaded
        logger.warning(
            "plugins.entry_point_invalid",
            name=ep.name,
            msg="Entry point must provide a Plugin instance or Plugin subclass",
        )
        return None

    @property
    def plugins(self) -> list[Plugin]:
        """Alle registrierten Plugins (laedt Entry-Points bei Bedarf)."""
        self._ensure_loaded()
        return sorted(self._plugins.values(), key=lambda p: p.name)

    def resolve_step(self, step_name: str) -> Plugin | None:
        """Findet das erste Plugin, das ``step_name`` handelt (AC-PL-A2).

        Wirft nie: Discovery-/Ladefehler sind Warnungen (E1). None, wenn
        kein Plugin den Step kennt.
        """
        self._ensure_loaded()
        for plugin in self._plugins.values():
            try:
                if plugin.handles(step_name):
                    return plugin
            except Exception as e:  # noqa: BLE001 - defektes handles() ueberspringen
                logger.warning(
                    "plugins.handles_failed", plugin=plugin.name, error=str(e)
                )
        return None


def _register_builtin_plugins(registry: "PluginRegistry") -> None:
    """Registriert Produktiv-Plugins direkt in der Registry (AC-PL-A3, DEF-013).

    LAZY-Variante: wird erst beim ERSTEN ``resolve_step``-/``plugins``-Zugriff
    aufgerufen (via ``_ensure_loaded``), NICHT beim Modul-Import — vermeidet
    den zirkularen Import (``structure_enhancement`` importiert ``core.plugins``
    zurueck; ein Top-Level-Import von ``structure_enhancement`` wuerde den
    Modul-Init von ``core.plugins`` unterbrechen).

    Das StructureEnhancementPlugin wird VOR Entry-Points registriert und
    gewinnt damit bei Duplikaten (AC-PL-A2: erste Registrierung gewinnt).
    Fehler werden als ``plugins.builtin_registration_failed``-Warning
    geloggt — kein Abbruch (E1).
    """
    try:
        # Lokaler Import hier (nicht Top-Level) — bricht den zirkularen
        # Import-Pfad (core.plugins -> plugins.structure_enhancement ->
        # core.plugins). Bei diesem Aufruf ist core.plugins vollstaendig
        # initialisiert, daher kein Zirkel mehr.
        from astro_process.plugins.structure_enhancement import (  # noqa: PLC0415
            StructureEnhancementPlugin,
        )
        registry.register(StructureEnhancementPlugin())
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "plugins.builtin_registration_failed",
            name="structure_enhancement",
            error=str(e),
        )


_default_registry = PluginRegistry()


def default_registry() -> PluginRegistry:
    """Liefert die Default-Registry (fuer CLI/Verarbeitung).

    Injizierte Test-Plugins werden hier registriert (AC-PL-A3) — dadurch
    erscheinen sie auch in ``astra plugin list`` (AC-PL-C2) ohne echte
    Installation.

    Builtin-Plugins (structure_enhancement) werden lazy beim ersten Zugriff
    registriert (DEF-013: lazy Import vermeidet zirkulaere Abhaengigkeit).
    """
    return _default_registry


def resolve_step(
    step_name: str,
    registry: PluginRegistry | None = None,
) -> Plugin | None:
    """Modul-Fassade: konsultiert die Default-Registry (bzw. ``registry``).

    Fuer die Step-Validierung in processing_agent (PL-B): unbekannter
    Kern-Step -> Plugin gefunden? sonst ``pipeline.step_unhandled``-Warning
    (Verhalten aus E1-Close, AC-GR-B4).
    """
    if registry is not None:
        return registry.resolve_step(step_name)
    return _default_registry.resolve_step(step_name)
