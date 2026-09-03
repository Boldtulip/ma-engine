"""Signals.

A signal looks at one aspect of a company and returns a score between
0 and 1, a confidence between 0 and 1, and one plain sentence a person
can check. The scoring engine combines the enabled signals using the
weights in the scoring config.

Signals are registered by name. The four bundled ones are the China
succession example. To add your own, write a function with the same
shape, decorate it with @signal("your_name"), put the module on the
config's `plugins` list, and give it a weight under `signals`.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ma_engine.adapters.base import Company


@dataclass
class Signal:
    key: str          # machine name, e.g. "founder_age"
    score: float      # 0 (no pressure to sell) to 1 (maximum)
    confidence: float # 0 to 1, how much the reading can be trusted
    reason: str       # one plain sentence a person can check


SignalFn = Callable[[Company, dict], Signal]

REGISTRY: dict[str, SignalFn] = {}


def signal(key: str) -> Callable[[SignalFn], SignalFn]:
    """Register a signal function under a name used in the config."""

    def register(fn: SignalFn) -> SignalFn:
        REGISTRY[key] = fn
        return fn

    return register


def load_builtin() -> None:
    """Import the bundled signal modules so they register themselves."""
    from ma_engine.signals import age, heirs, pressure, tenure  # noqa: F401


def load_plugins(modules: list[str]) -> None:
    """Import user modules listed in the config so their signals register.

    The current working directory is put on the import path first, so a
    plugin next to the config, or under the repository root, is found
    without any packaging.
    """
    if not modules:
        return
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    for name in modules:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                f"Plugin module '{name}' from the scoring config could not be "
                f"imported ({exc}). Run from the directory that contains it, or "
                f"install it as a package."
            ) from exc


def compute(company: Company, config: dict) -> list[Signal]:
    """Run every signal enabled in the config, with its parameters."""
    load_builtin()
    load_plugins(config.get("plugins", []))
    out: list[Signal] = []
    for key, params in (config.get("signals") or {}).items():
        if key not in REGISTRY:
            known = ", ".join(sorted(REGISTRY)) or "none"
            raise KeyError(
                f"Signal '{key}' is enabled in the config but no signal with "
                f"that name is registered. Registered: {known}. If it lives in "
                f"your own module, add the module to `plugins` in the config."
            )
        out.append(REGISTRY[key](company, params or {}))
    return out
