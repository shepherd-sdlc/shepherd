"""Reach a Shepherd Pro module from free code, or say plainly that Pro is needed.

Shepherd Free ships without the Pro modules. Free code that can do more when Pro is present calls
`pro_module(name, feature)` rather than importing the module. With Pro installed it returns the
module; without it, it raises `ProRequired`, whose message names the feature, so the caller can
report "<feature> needs Shepherd Pro" in its own usual way instead of crashing.

Only the named module being absent counts as "Pro is not installed". A Pro module that is present
but fails to import (a missing dependency, a syntax error) still raises its real error: hiding that
behind "needs Pro" would send a Pro customer looking for a licence they already have.
"""

from __future__ import annotations

import importlib
from types import ModuleType


class ProRequired(Exception):
    """The feature needs a module that only Shepherd Pro ships."""

    def __init__(self, feature: str, module: str):
        super().__init__(f"{feature} needs Shepherd Pro")
        self.feature = feature
        self.module = module


def pro_module(name: str, feature: str) -> ModuleType:
    """The Pro module `name`, or ProRequired naming `feature` when Pro is not installed."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        raise ProRequired(feature, name) from None


def has_pro(name: str) -> bool:
    """Whether the Pro module `name` is installed. A broken Pro module still raises."""
    try:
        pro_module(name, name)
    except ProRequired:
        return False
    return True
