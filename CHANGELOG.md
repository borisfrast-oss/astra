# Changelog

All notable changes to **Astra** are documented here. Format oriented on
[Keep a Changelog](https://keepachangelog.com/). Release audit details are
maintained separately and are not shipped in this repository.

## [1.12.0] - 2026-09-16

### Highlights

- **Agent-Free Delivery** — Pipeline is now fully self-contained; no external Knowledge Base required. Target cache (`astra/data/target-cache.json`, 35 objects) is baked into the Wheel; `astra suggest` / `astra process` run offline-first with local cache first, SIMBAD only on cache miss.
- **Minimal Baked Cache** — Cache reduced to essentials (`catalog_number`, `type`, `ra`, `dec`, `aliases`); verbose fields (`Handbook`, `Preset`, `Ordner`, `Besonderheit`, `Größe/Helligkeit` → `Size/Brightness`, `Sternbild` → `constellation`) removed. Preset & Handbook derived live via `Typ → Handbook Kap.22 → Preset` (`classify_and_cite`). Historical German field names retained as literals in this entry only (UTF-8).
- **Cache Language** — Cache entries now English (`type: galaxy`, `star`, `dark_nebula`, `open_cluster`, `globular`, `planetary`, `snr`, `moon`); no more German descriptions (`Stern (K0IIIa Riese)` → `star`).
- **M31 Mini-Example (A+B)** —
  - **A:** Synthetic 5-frame M31 (60s Gain 40 Astro, superpixel 32×32, `galaxy_standard` preset) baked into Wheel (<100 KB). Offline `astra process --limit 5` works immediately after `pip install`.
  - **B:** Real 10-frame M31 (90s40 Astro, from C:\Astra reference) as GitHub Release Asset via `astra download-example M31 --n 10`. Real-Gate `astra process --limit 5` validates full pipeline on real data.
- **Ghost Bugs Fixed** — B1: `suggest --header` no longer creates ghost folders (path from `original_target`). B2: `suggest` without `--header` now auto-scans `lights\` for `OBJECT` header → cache hit without SIMBAD. B3: `orion` KB cache removed; only `astra/data/target-cache.json` (baked) remains; user `config.yaml` cache path removed.
- **Offline-First Clarified** — "100% offline" corrected to **offline-first**: pipeline (Calibration → Debayer → Registration → Stacking → PCC → Export) runs fully offline. Only SIMBAD query needs internet (cache miss + online). Baked cache covers common targets.
- **M31 Mini-Example (A+B)** — Wheel-embedded synthetic smoke + optional real-data download.
- **Synthetic Darks/Bias** — 1 Master Dark (60s Gain 40) + 1 Bias frame baked into Wheel for M31 Mini-Example; enables full calibration offline.

### Added

- **M31 Mini-Example (A+B)** —
  - **A:** `astra/data/examples/M31/` (5 synthetic 60s40 Astro 32×32 superpixel + `suggested.yaml` `galaxy_standard`) baked into Wheel (<100 KB); `astra process --limit 5` instant offline smoke.
  - **B:** `astra download-example M31 --n 10` — downloads real M31 (10 frames 90s40 Astro from C:\Astra reference) from GitHub Release Asset; idempotent, SHA256 verified, `--force`, `--output`, EN §17 help, Real-Gate `--limit 5`.
- **`astra download-example`** — New subcommand downloads real M31 example (10 frames 90s40 Astro from C:\Astra reference) from GitHub Release Asset; idempotent, SHA256 verified, `--force`, `--output`, fallback to local `C:\Astra\M31 Andromeda`, EN §17 help, `download.asset_not_found` Exit 2.
- **`astra init --non-interactive`** — New flag for automated config setup (CI, scripts, demo); writes `config.yaml` + `environment.yaml` with defaults.
- **Synthetic Darks/Bias** — 1 Master Dark (60s Gain 40) + 1 Bias frame baked into Wheel for M31 Mini-Example; enables full calibration offline.
- **E2E Onboarding Test Gate** — New automated gate `scripts/e2e_onboarding_gate.ps1` (fresh venv, pip install wheel, `astra init --non-interactive`, `astra demo M31-mini`, `astra process --limit 5`, `astra qc` validation). Integrated in `builds\astra` Phase 2b; 120s timeout; validates fresh venv → wheel install → `astra init --non-interactive` → `astra demo M31-mini` → `astra process --limit 5` → `astra qc` Exit 0.
- **E2E Onboarding Gate CI** — New CI job `e2e-onboarding` (ubuntu + windows) runs same gate in CI.
- **`astra init --non-interactive`** — New flag for automated config setup (CI, scripts, demo); writes `config.yaml` + `environment.yaml` with defaults.
- **Synthetic Darks/Bias** — 1 Master Dark (60s Gain 40) + 1 Bias frame baked into Wheel for M31 Mini-Example; enables full calibration offline.

### Changed

- **Offline-First Messaging** — "100% offline" corrected to **offline-first**: Pipeline (Calibration → Debayer → Registration → Stacking → PCC → Export) runs fully offline. Only SIMBAD query needs internet (cache miss + online). Baked cache covers common targets. Docs updated: README, CLI-Ref, Handbook 22 §17.
- **Target Cache** — Minimal baked cache (`astra/data/target-cache.json`, 35 objects, English keys: `catalog_number`, `simbad_name`, `type`, `ra`, `dec`, `aliases`). Verbose fields (`Handbook`, `Preset`, `Ordner`, `Besonderheit`, `Größe/Helligkeit` → `Size/Brightness`, `Sternbild` → `constellation`) removed; Preset & Handbook derived live via `Typ → Handbook Kap.22 → Preset` (`classify_and_cite`). Historical German literals UTF-8 verified (paige D3-01 fixed, `check-encoding.ps1` 0).
- **Target Cache Language** — Cache now English (`type: galaxy`, `star`, `dark_nebula`, `open_cluster`, `globular`, `planetary`, `snr`, `moon`); no more German descriptions (`Stern (K0IIIa Riese)` → `star`).
- **Ghost Bugs Fixed** — B1: `suggest --header` no longer creates ghost folders (path from `original_target`). B2: `suggest` without `--header` auto-scans `lights\` for `OBJECT` header → cache hit without SIMBAD. B3: `orion` KB cache removed; only `astra/data/target-cache.json` (baked) remains; user `config.yaml` cache path removed.
- **Target Cache Language** — Cache now English (`type: galaxy`, `star`, `dark_nebula`, `open_cluster`, `globular`, `planetary`, `snr`, `moon`); no more German descriptions (`Stern (K0IIIa Riese)` → `star`).
- **E2E Onboarding Test Gate** — New automated gate `scripts/e2e_onboarding_gate.ps1` (fresh venv, pip install wheel, `astra init --non-interactive`, `astra demo M31-mini`, `astra process --limit 5`, `astra qc` validation). Integrated in `builds\astra` Phase 2b; 120s timeout; validates fresh venv → wheel install → `astra init --non-interactive` → `astra demo M31-mini` → `astra process --limit 5` → `astra qc` Exit 0.
- **E2E Onboarding Gate CI** — New CI job `e2e-onboarding` (ubuntu + windows) runs same gate in CI.
- **`astra init --non-interactive`** — New flag for automated config setup (CI, scripts, demo); writes `config.yaml` + `environment.yaml` with defaults.
- **Synthetic Darks/Bias** — 1 Master Dark (60s Gain 40) + 1 Bias frame baked into Wheel for M31 Mini-Example; enables full calibration offline.

### Fixed

- **Offline-First Messaging** — "100% offline" corrected to **offline-first** across README, CLI-Ref, Handbook 22 §17. Pipeline runs offline; SIMBAD only on cache miss + online.
- **Ghost Bugs Fixed** — B1: `suggest --header` no longer creates ghost folders (path from `original_target`). B2: `suggest` without `--header` auto-scans `lights\` for `OBJECT` header → cache hit without SIMBAD. B3: `orion` KB cache removed; only `astra/data/target-cache.json` (baked) remains; user `config.yaml` cache path removed.

### Breaking

- **`astra init --non-interactive`** — New required flag for non-interactive use (scripts, CI, demo); interactive wizard remains default.

---

## [1.11.1] - 2026-09-06
