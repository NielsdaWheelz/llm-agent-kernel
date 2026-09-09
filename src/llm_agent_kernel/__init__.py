"""Public API, loaded when requested so generation-only hosts do not load tools."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from ._api import *  # noqa: F403
    from ._api import __all__ as __all__


def __getattr__(name: str) -> object:
    if name.startswith("_") and name != "__all__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    api = _import_module(f"{__name__}._api")
    if name != "__all__" and name not in api.__all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(api, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    api = _import_module(f"{__name__}._api")
    return sorted(set(globals()) | set(api.__all__))
