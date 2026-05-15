"""Editor selection shared by `config edit` and `shortcuts edit`."""
from __future__ import annotations

import os
import shutil

import typer


def choose_editor() -> list[str]:
    """Pick the user's preferred editor, with sensible fallbacks.

    Order: $EDITOR (split on whitespace so `EDITOR='code -w'` works), then
    vi/nano/nvim on PATH. Raises typer.BadParameter if nothing is found.
    """
    env = os.environ.get("EDITOR")
    if env:
        return env.split()
    for candidate in ("vi", "nano", "nvim"):
        if shutil.which(candidate):
            return [candidate]
    raise typer.BadParameter(
        "no editor found. Set $EDITOR or install vi/nano/nvim."
    )
