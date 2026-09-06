# Astra Wiki - Home

> **Astra** - Agentic Astrophotography Processing Pipeline for the DWARFLab Dwarf Mini.
> 100% local, Python-native, deterministic. This wiki bundles two references:

> **Project Status (v1.11):** Astra is in active development (Alpha). Core functionality is stable and production-ready for astrophotography workflows, but features and behavior may change before v1.0 release.

## Quickstart

New here? Start with the pipeline quickstart:

- **[Quickstart](01-quickstart)** - install, astra init, first astra process run
- [CLI Reference](03-cli-reference) - all subcommands and flags
- [Configuration](04-configuration) - layered config, presets, env

> **Preview images note:** Example images in the repository and documentation are quick-look previews only—asinh-stretched JPG exports, often from smoke-test runs with limited frames (noisy). Colors may be uncalibrated (e.g., green cast without photometric calibration). These are for demonstration; for publication-quality results, use the canonical linear FITS output with your own post-processing workflow.

## Handbook (Dwarf mini + Siril 1.4.4)

37 chapters covering acquisition, target-specific workflows, and post-processing.
Browse via the sidebar **Handbook** menu:

- **Fundamentals:** [Introduction](01-Introduction) | [Fundamentals](02-Fundamentals) | [Dwarf mini Best Practices](03-Dwarf-mini-Best-Practices) | [Siril Reference](04-Siril-Reference)
- **Target workflows:** [Galaxies](05-Galaxies) | [Emission Nebulae](06-Emission-Nebulae) | [Reflection Nebulae](07-Reflection-Nebulae) | [Planetary Nebulae](08-Planetary-Nebulae) | [Globular Clusters](09-Globular-Clusters) | [Open Clusters](10-Open-Clusters) | [Stars and Star Fields](11-Stars-and-Star-Fields) | [Moon and Planets](12-Moon-and-Planets) and more (05-16)
- **Processing:** [Multiple Exposures and HDR](17-Multiple-Exposures-and-HDR) | [Mosaics and Panoramas](18-Mosaics-and-Panoramas) | [Color Calibration and Final Processing](19-Color-Calibration-and-Final-Processing)
- **Practice & Reference:** [Siril Workflow Decision Tree](22-Siril-Workflow-Decision-Tree) | [Troubleshooting](23-Siril-Troubleshooting) | [Siril Command Quick Reference](37-Siril-Command-Quick-Reference) | all 37 in sidebar

See also: [_Sidebar Handbook section](_Sidebar) for the full 37-chapter list.

## Pipeline Docs (Technical)

12 auto-generated docs from the code (SSOT src/ + scripts/generate_docs.py):

- [Quickstart](01-quickstart) | [Pipeline Architecture](02-pipeline-architecture) | [CLI Reference](03-cli-reference) | [Configuration](04-configuration)
- [Presets](05-presets) | [Multi-Group](06-multi-group) | [Registration](07-registration) | [Gradient Removal](08-gradient-removal)
- [Darks Library](09-darks-library) | [Output Structure](10-output-structure) | [Troubleshooting](11-troubleshooting) | [Migration](12-migration)

Browse via the sidebar **Pipeline Docs** menu or start at [Quickstart](01-quickstart).

## Source vs Wiki

- **Sources (SSOT):** astra/handbook/ (37 EN chapters) + astra/docs/ (12 generated docs)
- **This wiki:** GitHub Wiki at https://github.com/borisfrast-oss/astra/wiki (repo astra.wiki.git)
- **Mermaid diagrams** are preserved as mermaid blocks and render natively on GitHub.
- **GFM** compatible - all pages are plain Markdown with GitHub Flavored Markdown tables, code fences, and links.

## Contributing

Wiki content is generated - edit the sources, not the wiki directly:

```bash
# edit handbook or code, then regenerate docs if needed
python scripts/generate_docs.py all
# sync to local wiki
powershell ./scripts/wiki-publish.ps1
# preview diff
powershell ./scripts/wiki-publish.ps1 --dry-run
# validate
powershell ./scripts/wiki-publish.ps1 --check
```

> **No auto-push** - this script never pushes. After validation, Boris gates push:
> git -C wiki status -> git -C wiki diff -> git -C wiki push (only after Quality-Gate approval).

