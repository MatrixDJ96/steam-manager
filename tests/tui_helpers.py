"""Shared helpers for the Textual Pilot suites (`test_tui.py`,
`test_tui_journey.py`). Textual imports stay inside the functions so the fast
lane (`pytest -m 'not tui'`) collects these modules without loading Textual.
"""
from __future__ import annotations


def make_app(state=None):
    from steam_manager.cli.tui.app import ConfigApp
    return ConfigApp(state=state)


async def wait_for_screen(pilot, app, screen_type, tries: int = 30):
    """Pump the event loop until a modal of `screen_type` is on top (the @work
    action that pushes it runs in a worker, so it isn't synchronous)."""
    for _ in range(tries):
        await pilot.pause()
        if isinstance(app.screen, screen_type):
            return
    raise AssertionError(f"{screen_type.__name__} never appeared")
