"""Private helpers shared across io/ VDF modules."""
from __future__ import annotations


def ci_get(d: dict, key: str):
    """Case-insensitive lookup on the first level of a dict.

    Real Steam writes keys with inconsistent capitalization across versions
    (e.g. `Apps` vs `apps`, `CompatToolMapping` vs `compattoolmapping`),
    so every nested-section walk uses this helper instead of `dict.get`.
    """
    if not isinstance(d, dict):
        return None
    target = key.lower()
    for k, v in d.items():
        if k.lower() == target:
            return v
    return None
