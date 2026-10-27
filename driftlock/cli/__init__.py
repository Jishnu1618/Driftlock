"""DriftLock CLI package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from driftlock.cli.main import app, main

__all__ = ["app", "main"]


def __getattr__(name: str) -> Any:
    """Resolve CLI exports lazily.

    Importing ``driftlock.cli.main`` here would load the submodule before
    ``python -m driftlock.cli.main`` runs it, which triggers a runpy
    RuntimeWarning. Resolving on first access keeps the public exports while
    leaving the module untouched at package import time.
    """
    if name in __all__:
        from driftlock.cli.main import app as _app, main as _main

        # Cache both exports so `main` stays the callable (not the submodule
        # that the import machinery binds on the package) as before.
        globals().update(app=_app, main=_main)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
