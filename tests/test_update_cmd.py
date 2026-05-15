"""End-to-end tests for the `steam-manager update` command."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from steam_manager import __version__, cli
from steam_manager.cli import update_cmd as upd

runner = CliRunner()


@pytest.fixture
def frozen_binary(tmp_path, monkeypatch):
    """Pretend we're a PyInstaller binary at tmp_path/steam-manager.

    Sets sys.frozen=True, points sys.executable at a writable scratch path,
    and ensures os.path.dirname of that path is also writable.
    """
    fake_bin = tmp_path / "steam-manager"
    fake_bin.write_text("#!/bin/sh\necho 'placeholder'\n")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_bin))
    return fake_bin


@pytest.fixture
def latest_payload():
    """Default minimal GitHub Releases JSON body for a newer release."""
    return {
        "tag_name": "v999.0.0",
        "name": "v999.0.0",
        "html_url": "https://github.com/MatrixDJ96/steam-manager/releases/tag/v999.0.0",
        "body": "- one\n- two\n- three",
    }


@pytest.fixture
def mock_subprocess(monkeypatch):
    """Replace subprocess.run with a controllable mock.

    The default behavior: every call returns CompletedProcess(returncode=0,
    stdout="steam-manager 999.0.0\n"). Tests can mutate `mock.return_value`
    or `mock.side_effect`.
    """
    mock = MagicMock(spec=subprocess.run)
    mock.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=f"steam-manager 999.0.0\n", stderr=""
    )
    monkeypatch.setattr("steam_manager.cli.update_cmd.subprocess.run", mock)
    return mock


# --- PyInstaller gate -----------------------------------------------------


def test_refuses_if_not_frozen(monkeypatch, fake_urlopen):
    # Default: sys.frozen unset in dev mode.
    monkeypatch.delattr(sys, "frozen", raising=False)
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code != 0
    assert "PyInstaller binary" in result.stdout
    # No HTTP call made — bail before any network.
    assert fake_urlopen.calls == []


def test_refuses_if_dir_unwritable(
    frozen_binary, monkeypatch, fake_urlopen, latest_payload
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body=latest_payload,
    )
    monkeypatch.setattr("os.access", lambda *a, **k: False)
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code != 0
    assert "Cannot write" in result.stdout


# --- --check flag --------------------------------------------------------


def test_check_when_newer_available(
    frozen_binary, fake_urlopen, latest_payload, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body=latest_payload,
    )
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0
    assert "Update available" in result.stdout
    assert "999.0.0" in result.stdout
    # --check must NOT invoke install.sh / subprocess.
    mock_subprocess.assert_not_called()


def test_check_when_on_latest(
    frozen_binary, fake_urlopen, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body={
            "tag_name": f"v{__version__}",
            "html_url": "https://example/h",
            "body": "",
        },
    )
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0
    assert "Up to date" in result.stdout
    mock_subprocess.assert_not_called()


# --- Default flow (without --force) -----------------------------------------


def test_already_on_latest_is_noop(
    frozen_binary, fake_urlopen, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body={
            "tag_name": f"v{__version__}",
            "html_url": "https://example/h",
            "body": "",
        },
    )
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 0
    assert "Already on latest" in result.stdout
    mock_subprocess.assert_not_called()


def test_update_available_with_yes_runs_installer(
    frozen_binary, fake_urlopen, latest_payload, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body=latest_payload,
    )
    fake_urlopen.add(
        "https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh",
        body=b"#!/usr/bin/env bash\necho fake install\n",
    )
    result = runner.invoke(cli.app, ["update", "--yes"])
    assert result.exit_code == 0, result.stdout
    # subprocess.run was called at least twice: once for the installer,
    # once for the post-install --version verification.
    assert mock_subprocess.call_count >= 2
    # First call: bash <tmpfile> with the right env.
    first = mock_subprocess.call_args_list[0]
    assert first.args[0][0] == "bash"
    env = first.kwargs["env"]
    assert env["STEAM_MANAGER_VERSION"] == "v999.0.0"
    assert env["STEAM_MANAGER_INSTALL_DIR"] == str(frozen_binary.parent)
    assert env["STEAM_MANAGER_QUIET"] == "1"


def test_force_runs_install_even_when_on_latest(
    frozen_binary, fake_urlopen, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body={
            "tag_name": f"v{__version__}",
            "html_url": "https://example/h",
            "body": "no notes",
        },
    )
    fake_urlopen.add(
        "https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh",
        body=b"#!/usr/bin/env bash\n",
    )
    # The post-install --version subprocess must return the *current* version
    # for the verification to pass on a forced re-install.
    mock_subprocess.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=f"steam-manager {__version__}\n", stderr=""
    )
    result = runner.invoke(cli.app, ["update", "--force", "--yes"])
    assert result.exit_code == 0, result.stdout
    assert mock_subprocess.call_count >= 2


# --- Failure modes --------------------------------------------------------


def test_installer_nonzero_exit_propagates_write_error(
    frozen_binary, fake_urlopen, latest_payload, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body=latest_payload,
    )
    fake_urlopen.add(
        "https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh",
        body=b"#!/usr/bin/env bash\n",
    )
    # First subprocess call (bash) returns non-zero.
    mock_subprocess.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=42, stdout="", stderr="boom"),
    ]
    result = runner.invoke(cli.app, ["update", "--yes"])
    assert result.exit_code != 0
    assert "code" in result.stdout and "42" in result.stdout


def test_post_install_version_mismatch_errors(
    frozen_binary, fake_urlopen, latest_payload, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body=latest_payload,
    )
    fake_urlopen.add(
        "https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh",
        body=b"#!/usr/bin/env bash\n",
    )
    # First call (installer) succeeds. Second call (--version) returns the OLD version.
    mock_subprocess.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"steam-manager {__version__}\n", stderr=""
        ),
    ]
    result = runner.invoke(cli.app, ["update", "--yes"])
    assert result.exit_code != 0
    assert "did not advance" in result.stdout


def test_api_error_renders_friendly_message(
    frozen_binary, fake_urlopen, mock_subprocess
):
    fake_urlopen.add_error(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        status=500,
    )
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code != 0
    assert "Could not check for updates" in result.stdout
    mock_subprocess.assert_not_called()


# --- Release notes --------------------------------------------------------


def test_release_notes_rendered_before_installer(
    frozen_binary, fake_urlopen, latest_payload, mock_subprocess
):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body=latest_payload,
    )
    fake_urlopen.add(
        "https://raw.githubusercontent.com/MatrixDJ96/steam-manager/main/scripts/install.sh",
        body=b"#!/usr/bin/env bash\n",
    )
    result = runner.invoke(cli.app, ["update", "--yes"])
    assert result.exit_code == 0, result.stdout
    # The body items appear before the "Running installer" line.
    body_pos = result.stdout.find("one")  # release body item
    install_pos = result.stdout.find("Running installer")
    assert 0 <= body_pos < install_pos, (
        f"body at {body_pos}, installer at {install_pos}, stdout:\n{result.stdout}"
    )


def test_truncate_body_caps_long_release_notes():
    long_body = "\n".join(f"line {i}" for i in range(200))
    out = upd._truncate_body(long_body, "https://example/h")
    assert "truncated" in out
    assert "https://example/h" in out
    assert len(out.splitlines()) < 50  # max ~40 + tail


def test_truncate_body_empty_is_empty():
    assert upd._truncate_body("", "https://example/h") == ""
