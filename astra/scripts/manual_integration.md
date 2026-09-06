# Manual Integration — Multi-Group Stacking (T13)

> **Herkunft:** `tests/test_multi_group_integration.py` (155 Zeilen, keine automatisierten Tests).
> **Verschoben W2.5 SOFORT 4:** 2026-09-01 — aus `tests/` entfernt (grep-Erleichterung W3), nach `scripts/` verschoben (nicht shipped, pyproject wheel `packages = ["src/astro_process"]`).
> **Begründung `scripts/` statt `docs/`:** Keine User-Doku (kein shipped `docs/`) — reine Entwickler-Anleitung für manuelle Verifikation mit Real-Daten auf `C:/Astra/`. `docs/` ist generiert/shipped; `scripts/` ist developer-only und wird nicht ins Wheel gepackt.
> **Alternative geprüft:** `git rm` wäre ebenfalls valide — Inhalt ist nicht vertragsrelevant (kein AC), aber als Runbook für M13/52 Cyg behalten sinnvoll.

**Voraussetzungen:**
- Run from: `C:/Projects/astra` (Repo-Root)
- Requires: Real FITS data in `C:/Astra/` Verzeichnissen

## M13 Multi-Group (76 frames, 4 groups)

```bash
python -m astro_process.cli process "C:\Astra\M13" --preset galaxy_standard --multi-group
```

Verify:
1. Log shows: `multi_group.start`, `group_count=4`
2. Groups discovered: `15s60`, `60s40`, `120s100`, (any 4th group)
3. Output structure under `generated/{timestamp}/`:
   - `group_15s60/03_registered/`, `group_15s60/04_stacked/`
   - `group_60s40/03_registered/`, `group_60s40/04_stacked/`
   - `group_120s100/03_registered/`, `group_120s100/04_stacked/`
   - `group_*/03_registered/`, `group_*/04_stacked/`
4. `merged/` directory created:
   - `merged/M13_merged.fits` (valid FITS, RGB, 32-bit)
   - `merged/M13_merged_preview.jpg` (auto-stretched)
   - `merged/merge_report.json` (4 input stacks)
5. `merge_report.json` contains:
   - `method: "weighted_average"`
   - `weight_by: "frame_count"`
   - `input_stacks`: list of 4 entries with group hash, path, metadata, weight
   - `output.stats`: min, max, mean, median
   - `pcc_fallback_groups: []` (empty if all PCC succeeded)
6. `agent-log.yaml` contains `multi_group.groups` section
7. No `{target}_final.fits` in working dir root — final FITS lives ONLY in `merged/`
8. Preview JPG created in `merged/` (`M13_merged_preview.jpg`); CLI summary shows it
9. Visual inspection: no color shift, good merge quality

## 52 Cyg Duo-Band (29 frames)

```bash
python -m astro_process.cli process "C:\Astra\52 Cyg" --preset galaxy_standard --multi-group
```

Verify:
1. Registration channel logged: `registration.channel_selected` with `channel=R` (for Duo-Band)
2. All groups discovered correctly
3. Merge successful
4. Preview shows good color balance (Duo-Band Ha+OIII)
5. Check `merge_report.json` for per-group metadata

## Single-Group mit --multi-group

```bash
python -m astro_process.cli process "C:\Astra\SingleTarget" --multi-group
```

Expected:
1. Warning: `multi_group.single_group` — only one group found
2. Normal single-group pipeline runs (no merge)
3. No `merged/` directory created
4. No `merge_report.json`

## merge Sub-Command

Precondition: Run the M13 multi-group test first (produces group dirs).

```bash
python -m astro_process.cli merge "C:\Astra\M13" --method weighted_average --weight-by total_exposure
```

Verify:
1. Scans latest `generated/{timestamp}/` for `group_*` directories
2. Lists each group with EXPTIME, GAIN, FILTER, Frames, Total
3. Creates `merged/` in the latest timestamp dir
4. `merged_*.fits` created successfully
5. `merge_report.json` written

Dry-run test:
```bash
python -m astro_process.cli merge "C:\Astra\M13" --dry-run
# -> Shows "DRY RUN - Would merge N groups"
```
