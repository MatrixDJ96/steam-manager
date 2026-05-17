"""Direct unit tests for the pure TOML helpers in `io/policies_toml.py`.

These were previously only exercised indirectly via `config_cmd` and the
wizard. The audit flagged the indirect coverage as a blind spot — bugs
in dotted-key navigation would surface as confusing config-command
failures rather than precise assertion mismatches.
"""
from __future__ import annotations

import tomlkit

from steam_manager.io import policies_toml


# ----- get_dotted -----------------------------------------------------------


def test_get_dotted_returns_leaf_value():
    doc = tomlkit.parse('[games]\ncompat_tool = "Proton-9.0"\n')
    assert policies_toml.get_dotted(doc, "games.compat_tool") == "Proton-9.0"


def test_get_dotted_returns_none_on_missing_leaf():
    doc = tomlkit.parse('[games]\ncompat_tool = "Proton-9.0"\n')
    assert policies_toml.get_dotted(doc, "games.does_not_exist") is None


def test_get_dotted_returns_none_on_missing_branch():
    doc = tomlkit.parse('[games]\n')
    assert policies_toml.get_dotted(doc, "absent.deeply.nested") is None


def test_get_dotted_returns_none_when_traversing_scalar():
    """`games.compat_tool.x` walks into a string — must return None, not raise."""
    doc = tomlkit.parse('[games]\ncompat_tool = "Proton"\n')
    assert policies_toml.get_dotted(doc, "games.compat_tool.x") is None


def test_get_dotted_returns_subtable():
    doc = tomlkit.parse('[games]\ncompat_tool = "Proton"\nlaunch_options = "x"\n')
    result = policies_toml.get_dotted(doc, "games")
    assert isinstance(result, (dict, tomlkit.items.Table))
    assert result["compat_tool"] == "Proton"


# ----- set_dotted -----------------------------------------------------------


def test_set_dotted_creates_intermediate_tables():
    doc = tomlkit.document()
    policies_toml.set_dotted(doc, "overrides.730.ignore", True)
    assert doc["overrides"]["730"]["ignore"] is True


def test_set_dotted_overwrites_existing_value():
    doc = tomlkit.parse('[games]\ncompat_tool = "old"\n')
    policies_toml.set_dotted(doc, "games.compat_tool", "new")
    assert doc["games"]["compat_tool"] == "new"


def test_set_dotted_preserves_sibling_keys():
    doc = tomlkit.parse('[games]\ncompat_tool = "x"\nlaunch_options = "y"\n')
    policies_toml.set_dotted(doc, "games.compat_tool", "new")
    assert doc["games"]["compat_tool"] == "new"
    assert doc["games"]["launch_options"] == "y"


def test_set_dotted_writes_top_level_key():
    doc = tomlkit.document()
    policies_toml.set_dotted(doc, "max_backups", 7)
    assert doc["max_backups"] == 7


# ----- unset_dotted ---------------------------------------------------------


def test_unset_dotted_removes_value_and_returns_true():
    doc = tomlkit.parse('[games]\ncompat_tool = "x"\nlaunch_options = "y"\n')
    assert policies_toml.unset_dotted(doc, "games.compat_tool") is True
    assert "compat_tool" not in doc["games"]
    # Sibling preserved.
    assert doc["games"]["launch_options"] == "y"


def test_unset_dotted_drops_empty_parent_tables():
    doc = tomlkit.parse('[overrides.730]\nignore = true\n')
    policies_toml.unset_dotted(doc, "overrides.730.ignore")
    # Walking up, both `overrides.730` and `overrides` are empty → dropped.
    assert "overrides" not in doc


def test_unset_dotted_returns_false_when_key_missing():
    doc = tomlkit.parse('[games]\ncompat_tool = "x"\n')
    assert policies_toml.unset_dotted(doc, "games.launch_options") is False


def test_unset_dotted_returns_false_when_intermediate_missing():
    doc = tomlkit.document()
    assert policies_toml.unset_dotted(doc, "absent.deeply.nested") is False


def test_unset_dotted_preserves_non_empty_parent():
    doc = tomlkit.parse('[overrides.730]\nignore = true\ncompat_tool = "x"\n')
    policies_toml.unset_dotted(doc, "overrides.730.ignore")
    # `overrides.730` still has compat_tool — keep both.
    assert "overrides" in doc
    assert doc["overrides"]["730"]["compat_tool"] == "x"


# ----- render_effective_doc (smoke) -----------------------------------------


def test_render_effective_doc_emits_general_block():
    """Duck-typed on a minimal engine-shaped object."""
    class _FakeSection:
        compat_tool = "Proton-9.0"
        launch_options = None

    class _FakeEngine:
        max_backups = 7
        target_users = ["active"]
        sections = {"games": _FakeSection()}
        overrides = {"730": {"ignore": True}}

    doc = policies_toml.render_effective_doc(_FakeEngine())
    assert doc["general"]["max_backups"] == 7
    assert list(doc["general"]["target_users"]) == ["active"]
    assert doc["games"]["compat_tool"] == "Proton-9.0"
    assert "launch_options" not in doc["games"]
    assert doc["overrides"]["730"]["ignore"] is True
