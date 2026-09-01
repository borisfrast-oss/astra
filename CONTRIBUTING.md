# Contributing to Astra

Thank you for your interest in contributing to **Astra**, the agentic
astrophotography processing pipeline. Astra is a free, open-source, community
release. All contributions — code, docs, bug reports, feature ideas — are
welcome.

Please read this guide before opening an issue or pull request.

---

## Code of Conduct

By participating in this project you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md). Please report unacceptable behavior to
[borisfrast@gmail.com](mailto:borisfrast@gmail.com).

## Security

Found a security vulnerability? Do **not** open a public issue. Please follow
the disclosure process described in our [Security Policy](SECURITY.md) —
report privately via GitHub Security Advisories or
[borisfrast@gmail.com](mailto:borisfrast@gmail.com).

---

## Contribution workflow

1. **Fork** the repository on GitHub and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. **Make your changes** — keep them focused and small. One logical change per
   pull request.
3. **Write/update tests** for your change and make sure the existing suite
   still passes.
4. **Commit** with [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat:` — a new feature
   - `fix:` — a bug fix
   - `docs:` — documentation only
   - `perf:` — a performance improvement
   - `refactor:` — code change that neither fixes a bug nor adds a feature
   - `style:` — formatting, missing semicolons, etc.
   - `test:` — adding or correcting tests
   - `chore:` / `ci:` / `build:` — maintenance / CI / build changes
   Example: `feat: add --pcc flag to process command`
5. **Push** your branch and open a **pull request** against `main`.
6. **CI must be green** — required checks run on **Ubuntu + Windows with
   Python 3.11**. Resolve any failures before requesting review.
7. **Review** — a maintainer will review your PR. Address feedback and keep the
   conversation focused. Once approved, it will be merged.

---

## Development setup

Clone the repository and install in editable mode with the development and
optional `astroalign` extras:

```bash
git clone https://github.com/borisfrast/astra.git
cd astra
pip install -e .[dev,astroalign]
```

Copy `.env.example` to `.env` and edit the paths, then initialize:

```bash
cp .env.example .env
astra init --non-interactive
astra doctor
```

### Running tests

```bash
python -m pytest
```

### Regenerating documentation

Docs in `docs/` are generated from source. After changing docs or doc_data,
regenerate and verify they are hash-stable and English-clean:

```bash
python scripts/generate_docs.py all
python scripts/generate_docs.py check   # must report [OK]
```

### Code style

- Python 3.11+.
- Keep changes deterministic and CI-testable (Astra's design goal).
- Do not introduce personal or device-specific paths — see the Privacy policy
  in the [Security Policy](SECURITY.md).

---

## Questions

For questions or help, open a discussion or issue on GitHub, or contact
[borisfrast@gmail.com](mailto:borisfrast@gmail.com).

Thank you for contributing — and clear skies!
