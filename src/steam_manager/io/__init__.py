"""Filesystem I/O — VDF, TOML, tar.gz checkpoints.

Modules in this package do filesystem reads/writes only. They may import
from `steam_manager.models` for shared dataclasses, but MUST NOT import
from `steam_manager.cli`, `steam_manager.render`, or `steam_manager.policy`.
This keeps the dependency direction one-way: cli/ → io/ → models.
"""
