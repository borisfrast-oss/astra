"""Tests fuer V1.7-4: Equipment Auto-Detection aus FITS-Headern.

Spec: knowledge-base/projects/astra/specs/v17-equipment-auto-detection.md
(decided; OQ-EQPT-1..4 durch Boris resolved 2026-08-21).

Deckt ab:
- EQPT-A: resolve_equipment Header-Majority > Config-Profil > None+Warning;
  Majority ueber alle Lights; Config-Fallback; unknown_field; FOCALLEN-
  Kette; numerische Aequivalenz (AC-A1..A6).
- OQ-EQPT-1: Profil-Matching exakt vor Substring, laengster Match gewinnt,
  Fallback 'default'.
- OQ-EQPT-4: header_config_mismatch (99-Frames-Datenanhang: XPIXSZ 2.9 vs.
  Profil 3.76 -> Header gewinnt).
- EQPT-B: width_px/height_px dokumentarisch aus dem ersten Light (AC-B1).
- EQPT-C: datengetriebener Debayer-Faktor (AC-C1..C5), Bayer-Pattern best
  effort.
- EQPT-D: agent-log equipment-Block (AC-D1), inspect JSON (AC-D2),
  doctor Equipment-Versorgung (AC-D3).

Teststrategie: Unit-Tests bauen ObservationContext in-memory (schnell,
99-Frames-Szenario ohne FITS-IO); CLI-Tests (inspect/doctor) nutzen echte
Miniatur-FITS in tmp_path (Muster test_inspect_eqmode_shotsinfo.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from astropy.io import fits
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.agents.archive import ArchiveAgent  # noqa: E402
from astro_process.agents.discovery import DiscoveryAgent  # noqa: E402
from astro_process.cli import cli  # noqa: E402
from astro_process.config.models import AppConfig, EquipmentProfile  # noqa: E402
from astro_process.core.equipment import (  # noqa: E402
    detect_bayer_pattern,
    detect_input_is_rgb,
    match_equipment_profile,
    resolve_debayer_factor,
    resolve_equipment,
)
from astro_process.core.fits_parser import build_observation_context  # noqa: E402
from astro_process.core.pcc import compute_pixel_scale  # noqa: E402
from astro_process.models.core import (  # noqa: E402
    FitsHeader,
    FrameInfo,
    FrameSet,
    FrameType,
    ObservationContext,
    ObservationTarget,
)


# ═══════════════════════════════════════════════════════════════════
# Helpers (in-memory Contexts — kein FITS-IO noetig)
# ═══════════════════════════════════════════════════════════════════


def _header(**kwargs) -> FitsHeader:
    """FitsHeader mit Mandatory-Grundlage + optionalen Raw-Cards."""
    raw_cards = kwargs.pop("raw_cards", {}) or {}
    defaults = dict(
        object="TestTarget", exptime=60.0, gain=40, ccd_temp=20.0,
    )
    defaults.update(kwargs)
    return FitsHeader(raw_cards=dict(raw_cards), **defaults)


def _context(headers: list[FitsHeader], width: int = 1920,
             height: int = 1080) -> ObservationContext:
    frames = [
        FrameInfo(
            path=Path(f"light_{i:04d}.fits"), frame_type=FrameType.LIGHT,
            header=h, index=i, width=width, height=height,
        )
        for i, h in enumerate(headers)
    ]
    return ObservationContext(
        target=ObservationTarget(name="TestTarget"),
        frames={FrameType.LIGHT: FrameSet(frame_type=FrameType.LIGHT,
                                          frames=frames)},
        source_path=Path("."),
    )


def _dwarf_profiles() -> list[EquipmentProfile]:
    """OQ-EQPT-1-Beispielkonstellation: DWARF mini vs. DWARF 3 vs. default."""
    return [
        EquipmentProfile(name="DWARF mini", telescope="DWARF mini",
                         camera="DWARF mini camera", focal_length_mm=150,
                         aperture_mm=24, pixel_size_um=3.76),
        EquipmentProfile(name="DWARF 3", telescope="DWARF 3",
                         camera="DWARF 3 camera", focal_length_mm=150,
                         aperture_mm=35, pixel_size_um=2.9),
        EquipmentProfile(name="default", telescope="Unknown",
                         camera="Unknown", pixel_size_um=3.76),
    ]


# ═══════════════════════════════════════════════════════════════════
# EQPT-A — zentrale Equipment-Aufloesung (AC-EQPT-A1..A6)
# ═══════════════════════════════════════════════════════════════════


def test_ac_a1_pixel_size_from_header_majority():
    """AC-A1/A2: konsistentes XPIXSZ ueber ALLE Lights wird uebernommen."""
    ctx = _context([
        _header(pixel_size_x=2.9, instrument="DWARF mini") for _ in range(5)
    ])
    report = resolve_equipment(ctx, None)

    assert ctx.equipment.pixel_size_um == 2.9
    assert report["fields"]["pixel_size_um"] == {
        "value": 2.9, "source": "fits_header",
    }
    assert ctx.equipment.sources["pixel_size_um"] == "fits_header"


def test_ac_a2_inconsistent_header_majority_wins_and_warns():
    """AC-A2: abweichende Werte — Majority gewinnt, Inkonsistenz geloggt."""
    ctx = _context([
        _header(pixel_size_x=2.9),
        _header(pixel_size_x=2.9),
        _header(pixel_size_x=3.76),  # Ausreisser
    ])
    report = resolve_equipment(ctx, None)

    assert ctx.equipment.pixel_size_um == 2.9
    joined = " | ".join(report["warnings"])
    assert "inkonsistente" in joined and "pixel_size_um" in joined


def test_ac_a2_majority_tie_break_first_occurrence():
    """Majority-Tie (2 vs. 2) -> deterministisch erster Wert (Frame-Order)."""
    ctx = _context([_header(telescope="Scope A"), _header(telescope="Scope B")])
    resolve_equipment(ctx, None)
    assert ctx.equipment.telescope == "Scope A"


def test_ac_a3_config_fallback_when_header_missing():
    """AC-A3: fehlt XPIXSZ im Header UND Profil passt -> Config + Warning."""
    cfg = AppConfig(equipment_profiles=_dwarf_profiles())
    ctx = _context([
        _header(instrument="DWARF mini") for _ in range(3)  # kein XPIXSZ
    ])
    report = resolve_equipment(ctx, cfg)

    assert ctx.equipment.pixel_size_um == 3.76
    assert ctx.equipment.sources["pixel_size_um"] == "config"
    assert report["profile"] == "DWARF mini"
    joined = " | ".join(report["warnings"])
    assert "Config-Profil" in joined and "pixel_size_um" in joined


def test_ac_a4_unknown_field_none_and_pipeline_continues():
    """AC-A4: weder Header noch Config -> None + Warning, kein Crash."""
    ctx = _context([_header()])  # keine Equipment-Felder, keine Profile
    report = resolve_equipment(ctx, AppConfig())

    assert ctx.equipment.pixel_size_um is None
    assert ctx.equipment.sources["pixel_size_um"] == "none"
    joined = " | ".join(report["warnings"])
    assert "unbekannt" in joined and "pixel_size_um" in joined


def test_ac_a5_focal_length_chain_focallen_over_config():
    """AC-A5a: FOCALLEN-Header gewinnt gegen Profil-Wert (Mismatch geloggt)."""
    profiles = [EquipmentProfile(name="default", focal_length_mm=250)]
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header(focal_length=150)])  # kein Profil-Match noetig

    report = resolve_equipment(ctx, cfg)

    assert ctx.equipment.focal_length_mm == 150
    assert ctx.equipment.sources["focal_length_mm"] == "fits_header"
    joined = " | ".join(report["warnings"])
    assert "Widerspruch" in joined and "focal_length_mm" in joined


def test_ac_a5_focal_length_config_fallback_int_cast():
    """AC-A5b: fehlt FOCALLEN -> Config-Profil liefert den Wert (int-Cast)."""
    profiles = [EquipmentProfile(name="default", focal_length_mm=250)]
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header()])

    report = resolve_equipment(ctx, cfg)

    assert ctx.equipment.focal_length_mm == 250
    assert isinstance(ctx.equipment.focal_length_mm, int)
    assert ctx.equipment.sources["focal_length_mm"] == "config"


def test_ac_a6_pixel_scale_numeric_equivalence():
    """AC-A6: aufgeloeste Werte liefern identische Pixel-Skala wie manuell."""
    ctx = _context([_header(pixel_size_x=2.9, focal_length=150)])
    resolve_equipment(ctx, AppConfig())

    resolved_scale = compute_pixel_scale(
        ctx.equipment.focal_length_mm,
        ctx.equipment.pixel_size_um,
        binning=2.0,
    )
    manual_scale = compute_pixel_scale(150, 2.9, binning=2.0)
    assert resolved_scale == pytest.approx(manual_scale)
    # Gegenprobe Formel: 206.265 * 2.9 * 2 / 150
    assert resolved_scale == pytest.approx(206.265 * 2.9 * 2.0 / 150)


# ═══════════════════════════════════════════════════════════════════
# OQ-EQPT-1 — Config-Profil-Matching
# ═══════════════════════════════════════════════════════════════════


def test_oq1_exact_match_beats_substring():
    """Exakter Match vor Substring: 'DWARF 3' exakt schlaegt 'DWARF'-Prefix."""
    profiles = [
        EquipmentProfile(name="DWARF", telescope="Unknown",
                         camera="Unknown", pixel_size_um=4.2),
        EquipmentProfile(name="DWARF 3", telescope="Unknown",
                         camera="Unknown", pixel_size_um=2.9),
    ]
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header(instrument="DWARF 3")])

    profile, pattern = match_equipment_profile(ctx, cfg)

    assert profile is not None and profile.name == "DWARF 3"
    assert pattern == "DWARF 3"


def test_oq1_longest_substring_wins():
    """Laengster Match gewinnt: 'DWARF mini' vor 'DWARF' bei Substring."""
    profiles = [
        EquipmentProfile(name="DWARF", telescope="Unknown",
                         camera="Unknown", pixel_size_um=4.2),
        EquipmentProfile(name="DWARF mini", telescope="Unknown",
                         camera="Unknown", pixel_size_um=3.76),
    ]
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header(instrument="DWARF mini camera")])  # Substring nur

    profile, pattern = match_equipment_profile(ctx, cfg)

    assert profile is not None and profile.name == "DWARF mini"
    assert pattern == "DWARF mini"


def test_oq1_telescope_fallback_matching():
    """Kein INSTRUME-Match -> TELESCOP gegen name/camera/telescope geprueft."""
    profiles = [EquipmentProfile(name="Askar FRA400")]
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header(instrument=None, telescope="Askar FRA400")])

    profile, pattern = match_equipment_profile(ctx, cfg)

    assert profile is not None and profile.name == "Askar FRA400"


def test_oq1_default_profile_fallback():
    """Kein Match -> Profil 'default'; ohne default-Profil -> None."""
    profiles = [EquipmentProfile(name="default", pixel_size_um=3.76),
                EquipmentProfile(name="Other Scope", pixel_size_um=5.0)]
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header(instrument="Something Else",
                            telescope="Unknown Telescope")])

    profile, pattern = match_equipment_profile(ctx, cfg)

    assert profile is not None and profile.name == "default"
    assert pattern is None

    cfg_no_default = AppConfig(equipment_profiles=[
        EquipmentProfile(name="Other Scope", pixel_size_um=5.0)
    ])
    profile2, _ = match_equipment_profile(ctx, cfg_no_default)
    assert profile2 is None


def test_oq1_placeholder_defaults_not_used_as_source():
    """Profil-Platzhalter ('Unknown'/0) gelten NICHT als Config-Quelle.

    Ein gematchtes Profil mit ungepflegten Feldern darf telescope nicht
    auf "Unknown" setzen oder aperture_mm auf 0 — diese Felder bleiben
    None (source=none).
    """
    profiles = [EquipmentProfile(name="default")]  # reine Defaults
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header(instrument=None, telescope=None)])

    report = resolve_equipment(ctx, cfg)

    assert ctx.equipment.telescope is None
    assert ctx.equipment.camera is None
    assert ctx.equipment.aperture_mm is None
    assert ctx.equipment.sources["telescope"] == "none"
    # pixel_size_um hat einen echten Default (3.76) und gilt als gepflegt.
    assert ctx.equipment.pixel_size_um == 3.76
    assert ctx.equipment.sources["pixel_size_um"] == "config"
    assert report["profile"] == "default"


# ═══════════════════════════════════════════════════════════════════
# OQ-EQPT-4 — Header/Config-Widerspruch (Datenanhang: 99 Frames)
# ═══════════════════════════════════════════════════════════════════


def test_oq4_mismatch_ninetynine_frames_header_wins():
    """99 Frames XPIXSZ 2.9 vs. Profil 3.76 -> Header gewinnt + Mismatch."""
    cfg = AppConfig(equipment_profiles=_dwarf_profiles())
    # INSTRUME matcht 'DWARF mini' (Profil pixel_size_um=3.76), reale
    # XPIXSZ = 2.9 — der Boris-Datenanhang zur OQ-EQPT-4-Entscheidung.
    ctx = _context([
        _header(pixel_size_x=2.9, instrument="DWARF mini")
        for _ in range(99)
    ])

    report = resolve_equipment(ctx, cfg)

    assert ctx.equipment.pixel_size_um == 2.9  # NICHT 3.76 aus dem Profil
    assert ctx.equipment.sources["pixel_size_um"] == "fits_header"
    joined = " | ".join(report["warnings"])
    assert "Widerspruch" in joined and "pixel_size_um" in joined
    assert report["profile"] == "DWARF mini"


def test_oq4_no_mismatch_warning_when_values_agree():
    """Identische Werte (Header == Config) -> keine Mismatch-Warning."""
    profiles = [EquipmentProfile(name="default", focal_length_mm=150)]
    cfg = AppConfig(equipment_profiles=profiles)
    ctx = _context([_header(focal_length=150)])

    report = resolve_equipment(ctx, cfg)

    joined = " | ".join(report["warnings"])
    assert "focal_length_mm" not in joined or "Widerspruch" not in joined


# ═══════════════════════════════════════════════════════════════════
# EQPT-B — Resolution dokumentarisch (AC-EQPT-B1, B3)
# ═══════════════════════════════════════════════════════════════════


def test_ac_b1_resolution_from_first_light_frame():
    """AC-B1: width_px/height_px aus dem ERSTEN Light-Frame (NAXIS1/2)."""
    frames = [
        FrameInfo(path=Path("light_0000.fits"), frame_type=FrameType.LIGHT,
                  header=_header(), index=0, width=1920, height=1080),
        FrameInfo(path=Path("light_0001.fits"), frame_type=FrameType.LIGHT,
                  header=_header(), index=1, width=960, height=540),
    ]
    ctx = ObservationContext(
        target=ObservationTarget(name="TestTarget"),
        frames={FrameType.LIGHT: FrameSet(frame_type=FrameType.LIGHT,
                                          frames=frames)},
        source_path=Path("."),
    )

    report = resolve_equipment(ctx, None)

    assert ctx.equipment.width_px == 1920
    assert ctx.equipment.height_px == 1080
    assert report["resolution"] == {"width_px": 1920, "height_px": 1080}


def test_ac_b3_resolution_is_documentary_only():
    """AC-B3: Aufloesung veraendert kein Verhalten — nur Felder gesetzt.

    Fix B5 (ray-Review 2026-08-23): Der fruehere Assert gegen ein
    loose reg_cfg-Dict war vakuum — resolve_equipment sah das Dict nie.
    Jetzt: echte RegistrationConfig am AppConfig vor resolve_equipment
    snapshoten (model_copy) und danach vergleichen. Eine abweichende
    Header-Lage (hier: XPIXSZ 2.9 vs. Profil-frei) darf die Registrations-
    Config incl. stack_scale_factor NICHT anfassen.
    """
    from astro_process.config.models import RegistrationConfig

    ctx = _context([_header(pixel_size_x=2.9)])
    cfg = AppConfig(registration=RegistrationConfig(
        method="astroalign",
        stack_scale_factor=2.0,
        zero_shift_threshold=1.5,
    ))
    reg_before = cfg.registration.model_copy()

    resolve_equipment(ctx, cfg)

    assert ctx.equipment.width_px == 1920
    # Registrations-Config unangetastet (kein Verhaltens-Feld veraendert):
    assert cfg.registration == reg_before
    assert cfg.registration.stack_scale_factor == 2.0
    assert not hasattr(ctx, "stack_scale_factor")


# ═══════════════════════════════════════════════════════════════════
# EQPT-C — Debayer-Faktor + Bayer-Pattern (AC-EQPT-C1..C5)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "debayer_method,input_is_rgb,explicit,factor,source",
    [
        # AC-C1: 2D-CFA folgt V1.6-2-Methoden-Semantik.
        ("superpixel", False, None, 2.0, "auto_data"),
        ("bilinear", False, None, 1.0, "auto_data"),
        # AC-C2: 3D-RGB -> 1.0 unabhaengig von der Methode.
        ("superpixel", True, None, 1.0, "auto_data"),
        ("bilinear", True, None, 1.0, "auto_data"),
        # AC-C3: expliziter Override gewinnt IMMER (auch bei 3D).
        ("superpixel", False, 1.5, 1.5, "explicit"),
        ("bilinear", True, 3.0, 3.0, "explicit"),
    ],
)
def test_ac_c1_c3_debayer_factor_matrix(
    debayer_method, input_is_rgb, explicit, factor, source,
):
    """OQ-EQPT-3 Precedence: explicit > datengetrieben > Default."""
    got_factor, got_source = resolve_debayer_factor(
        debayer_method=debayer_method,
        explicit_value=explicit,
        input_is_rgb=input_is_rgb,
    )
    assert got_factor == factor
    assert got_source == source


def test_ac_c5_resolve_stack_scale_factor_v16_compat():
    """V1.6-Eingaben liefern identische Ergebnisse wie vor V1.7-4."""
    from astro_process.config.loader import resolve_stack_scale_factor

    assert resolve_stack_scale_factor("superpixel") == 2.0
    assert resolve_stack_scale_factor("bilinear") == 1.0
    assert resolve_stack_scale_factor("superpixel", explicit_value=1.25) == 1.25
    # Neu (EQPT-C): 3D-Input -> 1.0.
    assert resolve_stack_scale_factor("superpixel", input_is_rgb=True) == 1.0


def test_ac_c3_preset_level_in_precedence_chain():
    """Fix B2 (ray-Review 2026-08-23, OQ-EQPT-3-Kette):

    expliziter Override > PRESET > datengetrieben > Default.
    Der Preset-Wert schlaegt die datengetriebene Erkennung (bilinear wuerde
    ohne Preset 1.0/auto_data liefern), verliert aber gegen explicit.
    Quelle-Vokabular laut AC-EQPT-C5: explicit | preset | auto_data.
    """
    # Preset schlaegt datengetrieben — mit korrekter Quellen-Ableitung:
    assert resolve_debayer_factor(
        "bilinear", preset_value=2.0,
    ) == (2.0, "preset")
    assert resolve_debayer_factor(
        "superpixel", preset_value=1.0, input_is_rgb=True,
    ) == (1.0, "preset")
    # Explicit gewinnt IMMER (AC-C3), auch ueber Preset:
    assert resolve_debayer_factor(
        "superpixel", explicit_value=3.0, preset_value=1.0,
    ) == (3.0, "explicit")
    # Ohne explicit/preset unverändert (datengetrieben/default):
    assert resolve_debayer_factor("bilinear") == (1.0, "auto_data")
    assert resolve_debayer_factor("rotation_fft") == (2.0, "default")


def test_ac_c3_preset_via_resolve_stack_scale_factor():
    """Fix B2: Thin-Delegation resolve_stack_scale_factor reicht den
    Preset-Wert durch (cli.py Stufe-1-Aufruf)."""
    from astro_process.config.loader import resolve_stack_scale_factor

    # Preset schlaegt Methoden-Auto (bilinear -> sonst 1.0):
    assert resolve_stack_scale_factor(
        "bilinear", preset_value=2.0,
    ) == 2.0
    # Explicit schlaegt Preset:
    assert resolve_stack_scale_factor(
        "bilinear", explicit_value=3.0, preset_value=2.0,
    ) == 3.0


def test_ac_c4_bayer_pattern_from_header_and_assumed():
    """AC-C4: BAYERPAT-Rohkarte wird gelesen; fehlt sie -> RGGB-Annahme."""
    ctx_header = _context([_header(raw_cards={"BAYERPAT": "BGGR"})])
    pattern, source = detect_bayer_pattern(ctx_header)
    assert pattern == "BGGR"
    assert source == "fits_header"

    ctx_missing = _context([_header()])
    report = resolve_equipment(ctx_missing, None)
    assert ctx_missing.equipment.bayer_pattern is None
    assert report["bayer_pattern_source"] == "assumed"


def test_detect_input_is_rgb_via_naxis():
    """NAXIS=3 in den Rohkarten -> RGB-Input erkannt (2D -> False)."""
    rgb_ctx = _context([_header(raw_cards={"NAXIS": 3, "NAXIS3": 3})])
    assert detect_input_is_rgb(rgb_ctx) is True

    cfa_ctx = _context([_header(raw_cards={"NAXIS": 2})])
    assert detect_input_is_rgb(cfa_ctx) is False


# ═══════════════════════════════════════════════════════════════════
# EQPT-D — Transparenz: agent-log / inspect / doctor (AC-D1..D3)
# ═══════════════════════════════════════════════════════════════════


def test_ac_d1_agent_log_equipment_block(tmp_path):
    """AC-D1: agent-log.yaml enthaelt equipment-Block mit Wert+Quelle je Feld."""
    cfg = AppConfig(equipment_profiles=_dwarf_profiles())
    ctx = _context([_header(pixel_size_x=2.9, instrument="DWARF mini")])
    resolve_equipment(ctx, cfg)

    proc_stub = SimpleNamespace(
        registered_frames=[], stacked=None, exports=[],
        frame_qualities=[], stack_quality={}, gradient_removal={},
        registration_metrics={}, pcc_status=None,
    )
    calib_stub = SimpleNamespace(master_dark=None, calibrated_lights=[])
    agent = ArchiveAgent(output_root=tmp_path, config=cfg)
    log_path = agent._create_agent_log(
        tmp_path, ctx, proc_stub, calib_stub,
        debayer_result=None, discovery_result=None,
        multi_group_metadata=None,
    )

    log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
    eq_block = log["equipment"]

    assert eq_block["pixel_size_um"] == {"value": 2.9,
                                         "source": "fits_header"}
    assert eq_block["camera"]["source"] == "fits_header"
    assert eq_block["resolution"]["width_px"] == 1920
    # Kein BAYERPAT im Header -> RGGB-Annahme dokumentiert (AC-C4).
    assert eq_block["bayer_pattern"] == "assumed: RGGB"
    assert eq_block["profile_name"] == "DWARF mini"
    # Alle EQPT-A-Felder haben eine Quelle.
    for field in ("telescope", "camera", "pixel_size_um",
                  "focal_length_mm", "aperture_mm"):
        assert eq_block[field]["source"] in ("fits_header", "config", "none")


def test_ac_d1_agent_log_bayer_pattern_header_value(tmp_path):
    """AC-C4/D1: BAYERPAT aus dem Header landet im agent-log."""
    ctx = _context([_header(raw_cards={"BAYERPAT": "GBRG"})])
    resolve_equipment(ctx, None)

    proc_stub = SimpleNamespace(
        registered_frames=[], stacked=None, exports=[],
        frame_qualities=[], stack_quality={}, gradient_removal={},
        registration_metrics={}, pcc_status=None,
    )
    calib_stub = SimpleNamespace(master_dark=None, calibrated_lights=[])
    agent = ArchiveAgent(output_root=tmp_path, config=AppConfig())
    log_path = agent._create_agent_log(
        tmp_path, ctx, proc_stub, calib_stub,
    )
    log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
    assert log["equipment"]["bayer_pattern"] == "GBRG"


def test_ac_c5_agent_log_carries_ssf_factor_and_source(tmp_path):
    """Fix B1 (ray-Review 2026-08-23, AC-EQPT-C5): agent-log.yaml weist den
    aufgeloesten stack_scale_factor MIT Quelle strukturell im debayer-Block
    aus (analog AC-BIL-E4) — das Konsolen-Event allein genuegt nicht.

    Flip-faehig: ohne archive.py-Fix fehlen die Keys im Log (rot), mit Fix
    stehen Faktor + Quelle drin (gruen).
    """
    ctx = _context([_header(pixel_size_x=2.9)])
    resolve_equipment(ctx, AppConfig())

    proc_stub = SimpleNamespace(
        registered_frames=[], stacked=None, exports=[],
        frame_qualities=[], stack_quality={}, gradient_removal={},
        registration_metrics={}, pcc_status=None,
    )
    calib_stub = SimpleNamespace(master_dark=None, calibrated_lights=[])
    # Debayer-Ergebnis wie es die CLI nach der finalen SSF-Aufloesung
    # uebergibt (Fix-B1-Felder befuellt):
    deb_stub = SimpleNamespace(
        debayered_frames=[Path("deb_0000.fits")], method="superpixel",
        stack_scale_factor=2.0, stack_scale_factor_source="auto_data",
    )
    agent = ArchiveAgent(output_root=tmp_path, config=AppConfig())
    log_path = agent._create_agent_log(
        tmp_path, ctx, proc_stub, calib_stub,
        debayer_result=deb_stub,
    )

    log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
    assert log["debayer"]["stack_scale_factor"] == 2.0
    assert log["debayer"]["stack_scale_factor_source"] == "auto_data"


def test_ac_c5_agent_log_ssf_preset_source_and_legacy_safe(tmp_path):
    """Fix B1: Preset-Quelle wird sauber ausgewiesen; Legacy-Debayer-
    Ergebnisse ohne Fix-B1-Felder bleiben valide (None statt Crash)."""
    ctx = _context([_header()])
    resolve_equipment(ctx, None)

    proc_stub = SimpleNamespace(
        registered_frames=[], stacked=None, exports=[],
        frame_qualities=[], stack_quality={}, gradient_removal={},
        registration_metrics={}, pcc_status=None,
    )
    calib_stub = SimpleNamespace(master_dark=None, calibrated_lights=[])

    # Preset-Fall (Fix B2 macht diese Quelle erreichbar):
    deb_preset = SimpleNamespace(
        debayered_frames=[Path("deb_0000.fits")], method="bilinear",
        stack_scale_factor=2.0, stack_scale_factor_source="preset",
    )
    out_preset = tmp_path / "preset"
    out_preset.mkdir(parents=True)
    agent = ArchiveAgent(output_root=out_preset, config=None)
    log_path = agent._create_agent_log(
        out_preset, ctx, proc_stub, calib_stub,
        debayer_result=deb_preset,
    )
    log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
    assert log["debayer"]["stack_scale_factor"] == 2.0
    assert log["debayer"]["stack_scale_factor_source"] == "preset"

    # Legacy-Fall (keine Fix-B1-Felder am Ergebnis — alter Aufrufer):
    deb_legacy = SimpleNamespace(
        debayered_frames=[Path("deb_0000.fits")], method="bilinear",
    )
    out_legacy = tmp_path / "legacy"
    out_legacy.mkdir(parents=True)
    agent2 = ArchiveAgent(output_root=out_legacy, config=None)
    log_path2 = agent2._create_agent_log(
        out_legacy, ctx, proc_stub, calib_stub,
        debayer_result=deb_legacy,
    )
    log2 = yaml.safe_load(log_path2.read_text(encoding="utf-8"))
    assert log2["debayer"]["stack_scale_factor"] is None
    assert log2["debayer"]["stack_scale_factor_source"] is None


# ── CLI-Helfer (echte Miniatur-FITS) ─────────────────────────────────


def _write_light_fits(path: Path, **hdr_kwargs) -> Path:
    """Minimaler Light-FITS (16x16, 2D) mit Equipment-Headern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdr = fits.Header()
    hdr["EXPTIME"] = hdr_kwargs.pop("exptime", 30.0)
    hdr["GAIN"] = hdr_kwargs.pop("gain", 40)
    hdr["OBJECT"] = "M 27"
    hdr["CCD-TEMP"] = -10
    for key, value in hdr_kwargs.items():
        if value is not None:
            hdr[key] = value
    data = np.zeros((16, 16), dtype=np.float32)
    fits.PrimaryHDU(data=data, header=hdr).writeto(path, overwrite=True)
    return path


def _extract_json_from_output(output: str) -> dict:
    """JSON aus CliRunner-Output filtern (structlog-Zeilen entfernen)."""
    json_lines = [
        line.strip() for line in output.strip().splitlines()
        if line.strip()
        and not ('"timestamp"' in line and '"level"' in line)
    ]
    return json.loads("\n".join(json_lines))


def test_ac_d2_inspect_json_shows_sources_and_resolution(tmp_path):
    """AC-D2/B2: inspect --json zeigt Quelle je Feld + Aufloesung."""
    for i in range(3):
        _write_light_fits(
            tmp_path / "lights" / f"light_{i:03d}.fits",
            XPIXSZ=2.9, FOCALLEN=150, TELESCOP="DWARF mini",
            INSTRUME="DWARF mini",
        )

    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "--json", str(tmp_path)])
    assert result.exit_code == 0, result.output

    data = _extract_json_from_output(result.output)
    eq = data["equipment"]
    assert eq["pixel_size_um"] == 2.9
    assert eq["sources"]["pixel_size_um"] == "fits_header"
    assert eq["sources"]["focal_length_mm"] == "fits_header"
    assert eq["width_px"] == 16 and eq["height_px"] == 16
    assert eq["bayer_pattern"] == "assumed: RGGB"


def test_ac_d2_inspect_text_shows_source_labels(tmp_path):
    """AC-D2: Text-Ausgabe nennt Wert + Quelle pro Feld."""
    _write_light_fits(tmp_path / "lights" / "light_000.fits", XPIXSZ=2.9)

    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", str(tmp_path)])
    assert result.exit_code == 0, result.output

    assert "pixel_size_um: 2.9 [fits_header]" in result.output
    assert "Resolution: 16x16 px" in result.output
    assert "Bayer-Pattern: assumed: RGGB" in result.output


def test_discovery_run_resolves_equipment(tmp_path):
    """EQPT-A: DiscoveryAgent.run fuellt context.equipment (Header-Kette)."""
    for i in range(2):
        _write_light_fits(
            tmp_path / f"light_{i:03d}.fits",
            XPIXSZ=2.9, FOCALLEN=150, INSTRUME="DWARF mini",
        )

    agent = DiscoveryAgent(None)  # ohne Config -> reine Header-Erkennung
    result = agent.run(tmp_path)

    eq = result.context.equipment
    assert eq.pixel_size_um == 2.9
    assert eq.sources["pixel_size_um"] == "fits_header"
    assert eq.width_px == 16
    # Ohne Config bleiben die restlichen Felder unbekannt (Warnings).
    assert any("unbekannt" in w for w in result.warnings)


def _default_config_yaml(data_root: str = ".") -> str:
    """DEFAULT_CONFIG mit ueberschriebenem data_root (fuer doctor-Tests)."""
    from astro_process.config.loader import DEFAULT_CONFIG
    data = yaml.safe_load(DEFAULT_CONFIG)
    data["data_root"] = data_root
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def test_ac_d3_doctor_with_target_full_headers_ok(tmp_path):
    """AC-D3: volle Header-Versorgung -> '[OK] Equipment vollstaendig'."""
    for i in range(2):
        _write_light_fits(
            tmp_path / "lights" / f"light_{i:03d}.fits",
            XPIXSZ=2.9, FOCALLEN=150, APERTURE=24,
            TELESCOP="DWARF mini", INSTRUME="DWARF mini",
        )

    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("config.yaml").write_text(_default_config_yaml("."), encoding="utf-8")
        from unittest.mock import patch, MagicMock
        with patch("astro_process.cli._run_with_timeout",
                   return_value=MagicMock()):
            result = runner.invoke(
                cli, ["-c", "config.yaml", "doctor", str(tmp_path)],
            )

    # Exit-Code bewusst nicht fixiert (optionale Deps wie astroquery
    # erzeugen eigene WARNs); ausschlaggebend ist die Equipment-Zeile.
    assert "[OK] Equipment vollstaendig aus Headern" in result.output


def test_ac_d3_doctor_with_target_lists_missing_fields(tmp_path):
    """AC-D3: fehlende Felder komplett -> WARN mit Feldliste."""
    _write_light_fits(tmp_path / "lights" / "light_000.fits")  # kein Equipment

    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("config.yaml").write_text(_default_config_yaml("."), encoding="utf-8")
        from unittest.mock import patch, MagicMock
        with patch("astro_process.cli._run_with_timeout",
                   return_value=MagicMock()):
            result = runner.invoke(
                cli, ["-c", "config.yaml", "doctor", str(tmp_path)],
            )

    # Default-Profil liefert pixel_size_um (Config-Fallback) — telescope/
    # camera/aperture/focal fehlen komplett -> WARN mit Feldliste.
    assert result.exit_code == 1, result.output
    assert "Equipment-Felder komplett ohne Quelle" in result.output
    assert "focal_length_mm" in result.output


def test_doctor_without_target_still_works(tmp_path):
    """Backward-Compat: doctor ohne TARGET_PATH laeuft (kein Equipment-Target-Check)."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("config.yaml").write_text(_default_config_yaml("."), encoding="utf-8")
        from unittest.mock import patch, MagicMock
        with patch("astro_process.cli._run_with_timeout",
                   return_value=MagicMock()):
            result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])

    assert result.exit_code in (0, 1), result.output
    assert "Doctor:" in result.output
