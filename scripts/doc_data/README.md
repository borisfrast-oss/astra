# doc_data — Frozen generator inputs

This directory contains curated English markdown fragments that are consumed
by `scripts/generate_docs.py`. They are **deterministic generator inputs**, not
user-facing documentation. The published docs live in `docs/` and are
regenerated from these fragments plus live source extraction.

Do not edit files here expecting end-user docs to change; run the generator
instead:

```bash
python scripts/generate_docs.py all
```
