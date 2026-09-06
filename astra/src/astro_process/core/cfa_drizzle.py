"""V19-CFA-GATE core: CFA_DEFAULTS + resolver re-export.

Shim module so both `astro_process.core.cfa_drizzle` and
`astro_process.agents.cfa_drizzle_agent` expose the same resolver.
"""

from astro_process.agents.cfa_drizzle_agent import (
    CFA_DEFAULTS,
    DEBAYERED_DEFAULTS,
    _warn_if_overly_strict,
    resolve_cfa_drizzle_quality_gate,
)

__all__ = ["CFA_DEFAULTS", "DEBAYERED_DEFAULTS", "resolve_cfa_drizzle_quality_gate", "_warn_if_overly_strict"]
