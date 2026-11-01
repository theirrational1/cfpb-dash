"""Schema drift check: fail loudly, naming what changed, when a source's fields differ.

Used on the bulk CSV header and on every API day export (same header; ordered: columns are
read by position). `ordered=False` compares field sets (e.g. JSON keys). Fields are never
silently dropped or renamed.
"""

import logging
from collections import Counter

logger = logging.getLogger(__name__)


class SchemaDriftError(ValueError):
    pass


def check_fields(actual: list[str], expected: list[str], source: str, ordered: bool = True) -> None:
    """Raise SchemaDriftError describing added / removed / likely renamed / duplicated fields,
    or (when `ordered`) a changed order."""
    if actual == expected or (not ordered and Counter(actual) == Counter(expected)):
        return
    added = [f for f in actual if f not in expected]
    removed = [f for f in expected if f not in actual]
    duplicated = sorted(f for f, n in Counter(actual).items() if n > 1)
    renames = [
        (r, a)
        for r in removed
        for a in added
        if ordered and len(actual) == len(expected) and actual.index(a) == expected.index(r)
    ]
    parts = []
    if renames:
        parts.append("likely renamed [" + ", ".join(f"{r!r} -> {a!r}" for r, a in renames) + "]")
    if added:
        parts.append(f"added {added}")
    if removed:
        parts.append(f"removed {removed}")
    if duplicated:
        parts.append(f"duplicated {duplicated}")
    if not parts:
        parts.append(f"order changed: {actual}")
    message = f"{source}: schema drift in header/fields: " + "; ".join(parts)
    logger.error(message)
    raise SchemaDriftError(message)
