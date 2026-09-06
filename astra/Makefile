# Astra — Development Automation
#
# Pre-Release Process (AC-DOCS-D1/D2/D3):
#   1. Regenerate docs from source:  make docs
#   2. Verify docs are up-to-date:   make check-docs
#   3. Run full test suite:          make test
# This keeps astra/docs/ in sync with cli.py, config/models.py and config.yaml.
#
# NOTE: This Makefile uses standard POSIX syntax. On Windows without `make`
# installed, run the equivalent commands directly:
#   python scripts/generate_docs.py all
#   python scripts/generate_docs.py check
#   python -m pytest tests -q

.PHONY: docs check-docs test

docs:
	python scripts/generate_docs.py all

check-docs:
	python scripts/generate_docs.py check

test:
	python -m pytest tests -q
