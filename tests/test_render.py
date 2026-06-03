import os
import shutil

from steam_manager import render


def test_effective_max_width_uses_full_terminal(monkeypatch):
    monkeypatch.setattr(shutil, "get_terminal_size",
                        lambda fallback=(0, 0): os.terminal_size((240, 50)))
    assert render.effective_max_width() == 240


def test_effective_max_width_falls_back_without_terminal(monkeypatch):
    monkeypatch.setattr(shutil, "get_terminal_size",
                        lambda fallback=(0, 0): os.terminal_size((0, 0)))
    assert render.effective_max_width() == render.TABLE_WIDTH


def test_audit_table_renders_rows():
    rows = [
        ("111", "Game One", "Proton-CachyOS Latest", "scopebuddy -- %command%", True, True),
        ("222", "Game Two", "Proton-CachyOS Latest", "", True, False),
    ]
    output = render.audit_table_str(rows)
    assert "Game One" in output
    assert "Game Two" in output
    assert "111" in output
    assert "222" in output


def test_diff_table_renders_changes():
    changes = [
        {"appid": "222", "name": "Game Two", "field": "launch_options",
         "old": None, "new": "scopebuddy -- %command%", "user": "alice"},
    ]
    output = render.diff_table_str(changes)
    assert "Game Two" in output
    assert "Launch options" in output    # section title
    assert "scopebuddy" in output
    # Con un solo utente non c'e split, ne colonna User
    assert "User" not in output


def test_diff_table_groups_by_field(tmp_path):
    changes = [
        {"appid": "111", "name": "Game One", "field": "compat_tool",
         "old": None, "new": "Proton-CachyOS Latest", "user": None},
        {"appid": "222", "name": "Game Two", "field": "launch_options",
         "old": None, "new": "scopebuddy -- %command%", "user": "alice"},
    ]
    output = render.diff_table_str(changes)
    assert "Compat tool" in output
    assert "Launch options" in output
    # Compat tool table appears before Launch options
    assert output.index("Compat tool") < output.index("Launch options")


def test_diff_table_skips_empty_section():
    """Se solo launch_options drifta, non rendere la tabella Compat tool."""
    changes = [
        {"appid": "222", "name": "Game Two", "field": "launch_options",
         "old": None, "new": "scopebuddy -- %command%", "user": "alice"},
    ]
    output = render.diff_table_str(changes)
    assert "Compat tool" not in output
    assert "Launch options" in output


def test_diff_table_groups_by_section_games_first():
    """Mixed games + applications: each panel gets a label prefix, games first."""
    changes = [
        {"appid": "111", "name": "Game One", "field": "compat_tool",
         "old": None, "new": "proton_9", "user": None, "section": "games"},
        {"appid": "999", "name": "OBS", "field": "compat_tool",
         "old": None, "new": "proton_experimental", "user": None,
         "section": "applications"},
    ]
    output = render.diff_table_str(changes)
    assert "Games" in output
    assert "Applications" in output
    assert output.index("Games") < output.index("Applications")


def test_diff_table_single_section_has_no_prefix():
    """All changes in one section: no Games/Applications label prefix."""
    changes = [
        {"appid": "111", "name": "Game One", "field": "compat_tool",
         "old": None, "new": "proton_9", "user": None, "section": "games"},
    ]
    output = render.diff_table_str(changes)
    assert "Compat tool" in output
    assert "Games" not in output


def test_diff_table_without_section_key_renders_plain():
    """The restore preview emits changes with no 'section' key — render must
    fall back to the unlabelled, ungrouped layout (no qualifier separator)."""
    changes = [
        {"appid": "111", "name": "Game One", "field": "compat_tool",
         "old": "proton_8", "new": "proton_9", "user": None},
    ]
    output = render.diff_table_str(changes)
    assert "Compat tool" in output
    assert "·" not in output


def test_simple_table_str_with_simple_columns():
    output = render.simple_table_str(
        "My Table",
        ["AppID", "Name"],
        [("111", "Game One"), ("222", "Game Two")],
    )
    assert "My Table" in output
    assert "AppID" in output
    assert "Name" in output
    assert "Game One" in output


def test_simple_table_str_with_justify():
    output = render.simple_table_str(
        "Test",
        [("AppID", "right"), "Name"],
        [("111", "G")],
    )
    assert "Test" in output
    assert "AppID" in output


def test_select_one_interactive_ignores_unknown_default(monkeypatch):
    """A default matching no choice must be dropped, not passed to questionary
    (which raises ValueError) — e.g. a compat_tool no longer installed."""
    import questionary
    captured = {}

    class _Q:
        def ask(self):
            return None

    def _fake_select(prompt, choices, default=None):
        captured["default"] = default
        return _Q()

    monkeypatch.setattr(questionary, "select", _fake_select)
    render.select_one_interactive("Select:", [("A", "a"), ("B", "b")],
                                  default="not-a-choice")
    assert captured["default"] is None


def test_select_one_interactive_keeps_valid_default(monkeypatch):
    import questionary
    captured = {}

    class _Q:
        def ask(self):
            return None

    def _fake_select(prompt, choices, default=None):
        captured["default"] = default
        return _Q()

    monkeypatch.setattr(questionary, "select", _fake_select)
    render.select_one_interactive("Select:", [("A", "a"), ("B", "b")], default="b")
    assert captured["default"] == "b"


class _FakeQuestion:
    """Stand-in for a questionary Question: exposes the mutable key_bindings
    menu() pokes for its Esc binding, and a fixed `.ask()` result."""

    def __init__(self, answer):
        self._answer = answer

        class _KB:
            def add(self, *a, **k):
                return lambda fn: fn

        class _App:
            key_bindings = _KB()

        self.application = _App()

    def ask(self):
        return self._answer


def test_menu_appends_back_entry_and_returns_value(monkeypatch):
    import questionary
    captured = {}

    def _fake_select(title, choices, default=None, **kw):
        captured["choices"] = choices
        captured["default"] = default
        return _FakeQuestion("chosen")

    monkeypatch.setattr(questionary, "select", _fake_select)
    result = render.menu("t", [("A", "a"), ("B", "b")], default="a")
    assert result == "chosen"
    backs = [c for c in captured["choices"]
             if isinstance(c, questionary.Choice) and c.value is render.BACK]
    assert len(backs) == 1
    assert captured["default"] == "a"


def test_menu_returns_back_on_ctrl_c(monkeypatch):
    import questionary
    monkeypatch.setattr(questionary, "select",
                        lambda *a, **k: _FakeQuestion(None))  # None = Ctrl-C
    assert render.menu("t", [("A", "a")]) is render.BACK


def test_menu_drops_unknown_default(monkeypatch):
    import questionary
    captured = {}

    def _fake_select(title, choices, default=None, **kw):
        captured["default"] = default
        return _FakeQuestion(render.BACK)

    monkeypatch.setattr(questionary, "select", _fake_select)
    render.menu("t", [("A", "a")], default="not-a-choice")
    assert captured["default"] is None


def test_multiselect_returns_selection(monkeypatch):
    import questionary
    monkeypatch.setattr(questionary, "checkbox",
                        lambda *a, **k: _FakeQuestion(["x", "y"]))
    assert render.multiselect("t", [("X", "x"), ("Y", "y")]) == ["x", "y"]


def test_multiselect_returns_back_on_cancel(monkeypatch):
    import questionary
    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeQuestion(None))
    assert render.multiselect("t", [("X", "x")]) is render.BACK


def test_multiselect_empty_confirm_is_not_back(monkeypatch):
    # Confirming with nothing ticked is a real (empty) selection, not a cancel.
    import questionary
    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeQuestion([]))
    assert render.multiselect("t", [("X", "x")]) == []


def test_select_items_interactive_exists():
    """Smoke: function is importable and accepts the expected signature."""
    # Just check it's callable with the expected types. We don't invoke it
    # in non-interactive context because questionary requires a tty.
    assert callable(render.select_items_interactive)


def test_tables_use_rounded_box():
    """Verifica che le tabelle usino il box rounded (corners curvati)."""
    output = render.simple_table_str("Test", ["A"], [("x",)])
    # Rounded box uses ╭ ╮ ╰ ╯ corners (vs HEAVY_HEAD which uses ┏ ┓ ┗ ┛)
    assert "╭" in output or "╰" in output, f"Expected rounded corners in: {output!r}"


def test_nome_column_does_not_wrap_long_name(monkeypatch):
    """Il nome del gioco non deve essere spezzato su piu righe."""
    # Allarghiamo la Console di test cosi il nome lungo non viene troncato
    # dalla width=100 del buffer di test: stiamo verificando il non-wrap,
    # non i limiti di ampiezza del terminale.
    monkeypatch.setattr(render, "TABLE_WIDTH", 300)
    changes = [
        {"appid": "1810920", "name": "Operation Lovecraft: Fallen Doll Closed Beta",
         "field": "launch_options", "old": None, "new": "scopebuddy -- %command%",
         "user": "matrixdj96"},
    ]
    output = render.diff_table_str(changes)
    # Il nome completo deve apparire su una sola riga di output
    lines = output.split("\n")
    name_lines = [l for l in lines if "Operation Lovecraft" in l]
    assert len(name_lines) == 1, (
        f"Atteso 1 riga con il nome, trovate {len(name_lines)}: {name_lines!r}"
    )
    # E quella riga deve contenere il nome ENTIRE
    assert "Fallen Doll Closed Beta" in name_lines[0], (
        f"Il nome e stato troncato: {name_lines[0]!r}"
    )


def test_compat_table_has_no_user_column():
    """La tabella Compat tool NON ha la colonna User (compat e system-wide)."""
    changes = [
        {"appid": "111", "name": "G1", "field": "compat_tool",
         "old": None, "new": "Proton-X", "user": None},
    ]
    output = render.diff_table_str(changes)
    assert "Compat tool" in output
    assert "AppID" in output
    assert "Name" in output
    assert "From" in output
    assert "To" in output
    assert "User" not in output    # esplicitamente assente


def test_diff_launch_options_split_per_user():
    """Se ci sono drift su piu utenti, una tabella per utente."""
    changes = [
        {"appid": "111", "name": "G1", "field": "launch_options",
         "old": None, "new": "scopebuddy -- %command%", "user": "alice"},
        {"appid": "222", "name": "G2", "field": "launch_options",
         "old": None, "new": "scopebuddy -- %command%", "user": "bob"},
    ]
    output = render.diff_table_str(changes)
    assert "user:alice" in output
    assert "user:bob" in output


def test_diff_launch_options_single_user_no_split():
    """Con un solo utente, niente split, titolo plain."""
    changes = [
        {"appid": "111", "name": "G1", "field": "launch_options",
         "old": None, "new": "scopebuddy -- %command%", "user": "alice"},
    ]
    output = render.diff_table_str(changes)
    assert "Launch options" in output
    assert "user:" not in output    # nessuna suddivisione


def test_tables_use_panel_with_title_on_border():
    """Title should sit on the panel border, not on a separate line above."""
    output = render.simple_table_str("My Title", ["AppID", "Name"], [("111", "Foo")])
    # Panel border line should contain the title surrounded by box characters
    lines = output.splitlines()
    title_lines = [l for l in lines if "My Title" in l]
    assert len(title_lines) >= 1
    # The title should be on a line that starts with ╭ (rounded corner)
    assert any(l.lstrip().startswith("╭") and "My Title" in l for l in lines), (
        f"Title not found on top border. Lines: {lines!r}"
    )
