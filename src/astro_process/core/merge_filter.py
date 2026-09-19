"""Zentralisierte Filter-Helfer (V1.7-9, ray M5).

Beherbergt normalize/is_match aus config/loader.py + check_filter_typos
fuer einheitliche Tippfehler-Warnung `merge.filter_typo` (case-insensitive,
getrimmt). A1-Normierung: Gruppen-Filter klein-normiert ('astro','duo-band')
— Matching trim+lower faengt alte Config 'Duo-Band' ab.
"""

from __future__ import annotations


def normalize_merge_filters(filters: list[str] | None) -> list[str] | None:
    """V1.7-1 FSM-A (AC-FSM-A2, OQ-FSM-2 A): Filter-Liste normalisieren.

    Normalisierung: strip + lower (case-insensitive, getrimmt) je Eintrag.
    Leere Strings nach dem Trimmen werden verworfen (best effort). Duplikate
    bleiben erhalten (keine Deduplizierung noetig, Matching nutzt Set).

    Args:
        filters: Rohliste aus Config oder CLI (None = alle mergen).

    Returns:
        Normalisierte Liste (lower, getrimmt) oder None wenn Input None.
        Leere Eingabe -> [] (kein Match -> Merge-Skip, AC-FSM-A5) — NICHT None.
    """
    if filters is None:
        return None
    normalized: list[str] = []
    for raw in filters:
        if not isinstance(raw, str):
            raw = str(raw)
        trimmed = raw.strip()
        if not trimmed:
            continue
        normalized.append(trimmed.lower())
    return normalized


def is_merge_filter_match(
    filter_value: str | None,
    normalized_filters: list[str] | None,
) -> bool:
    """V1.7-1 FSM-A: Prueft ob ein Gruppen-FILTER zur Auswahl passt.

    Args:
        filter_value: FILTER-Wert der Gruppe (aus group_metadata["filter"]
                      oder FITS HEADER FILTER; None/"" -> "none"/leer).
        normalized_filters: Normalisierte Auswahl via normalize_merge_filters.
                            None = alle mergen (AC-FSM-A1), [] = keine passt.

    Returns:
        True wenn Gruppe Merge-Kandidat ist, False wenn filter_excluded.
    """
    if normalized_filters is None:
        return True
    if not normalized_filters:
        return False
    # Gruppen-FILTER normalisieren: None/"" -> "" (nach trim/lower)
    if filter_value is None:
        candidate = ""
    else:
        candidate = str(filter_value).strip().lower()
    return candidate in normalized_filters


def check_filter_typos(
    filters: list[str] | None,
    group_filters: list[str] | None,
) -> list[str]:
    """V1.7-9: Tippfehler-Check — welche Filter matchen keine Gruppe.

    Case-insensitive, getrimmt (trim+lower) auf beiden Seiten. Gibt die
    Teilmenge von `filters` zurueck, die zu keiner Gruppe passt — Aufrufer
    loggt einheitlich `merge.filter_typo` (Warning, kein Hard-Error).

    A1-Normierung: Gruppen-Filter sind seit v1.12 klein-normiert
    ('astro','duo-band'); lower+trim faengt alte Config 'Duo-Band' ab.

    Args:
        filters: Effektive Filter-Liste (bereits normalisiert via
                 normalize_merge_filters, aber auch roh erlaubt).
        group_filters: Gruppen-Filter-Werte (z.B. aus group_metadata["filter"]
                       oder Discovery Keys; None/"" -> "" ).

    Returns:
        Liste der Tippfehler-Filter (normalisiert lower, dedupliziert,
        reihenfolge-erhaltend nach erstem Auftreten). Leer wenn alles matcht
        oder filters leer/None.
    """
    if not filters:
        return []
    if group_filters is None:
        group_filters = []
    # Normalisierte Gruppen-Menge (trim+lower)
    group_norm: set[str] = set()
    for gf in group_filters:
        if gf is None:
            cand = ""
        else:
            cand = str(gf).strip().lower()
        group_norm.add(cand)

    typos: list[str] = []
    seen: set[str] = set()
    for flt in filters:
        if flt is None:
            norm = ""
        else:
            norm = str(flt).strip().lower()
        if norm in seen:
            continue
        seen.add(norm)
        if norm not in group_norm:
            typos.append(norm)
    return typos
