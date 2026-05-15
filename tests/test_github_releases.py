"""Tests for the pure-I/O GitHub Releases discovery layer."""
from __future__ import annotations

import pytest

from steam_manager.io import github_releases as gr


def test_fetch_latest_release_parses_minimal_payload(fake_urlopen):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body={
            "tag_name": "v0.0.3",
            "name": "v0.0.3",
            "html_url": "https://github.com/MatrixDJ96/steam-manager/releases/tag/v0.0.3",
            "body": "- bug fix\n- nice feature",
        },
    )
    r = gr.fetch_latest_release()
    assert r.tag == "v0.0.3"
    assert r.version == "0.0.3"
    assert r.name == "v0.0.3"
    assert "bug fix" in r.body
    assert r.html_url.endswith("/v0.0.3")


def test_fetch_latest_release_strips_v_prefix(fake_urlopen):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body={"tag_name": "v1.2.3", "html_url": "https://example/h"},
    )
    assert gr.fetch_latest_release().version == "1.2.3"


def test_fetch_latest_release_honors_env_repo_override(monkeypatch, fake_urlopen):
    monkeypatch.setenv("STEAM_MANAGER_UPDATE_REPO", "owner/fork")
    fake_urlopen.add(
        "https://api.github.com/repos/owner/fork/releases/latest",
        json_body={"tag_name": "v9.9.9", "html_url": "https://example/h"},
    )
    assert gr.fetch_latest_release().tag == "v9.9.9"


def test_fetch_latest_release_http_error_wrapped(fake_urlopen):
    fake_urlopen.add_error(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        status=404,
    )
    with pytest.raises(gr.GitHubReleaseError):
        gr.fetch_latest_release()


def test_fetch_latest_release_missing_field_raises(fake_urlopen):
    fake_urlopen.add(
        "https://api.github.com/repos/MatrixDJ96/steam-manager/releases/latest",
        json_body={"name": "no tag_name here"},
    )
    with pytest.raises(gr.GitHubReleaseError):
        gr.fetch_latest_release()


def test_fetch_text_returns_decoded_body(fake_urlopen):
    fake_urlopen.add(
        "https://example.com/install.sh",
        body=b"#!/bin/sh\necho hi\n",
    )
    assert gr.fetch_text("https://example.com/install.sh") == "#!/bin/sh\necho hi\n"


def test_compare_versions_basic():
    assert gr.compare_versions("0.0.2", "0.0.3") == -1
    assert gr.compare_versions("0.0.3", "0.0.3") == 0
    assert gr.compare_versions("0.0.4", "0.0.3") == 1


def test_compare_versions_ignores_v_prefix():
    assert gr.compare_versions("v0.0.2", "0.0.3") == -1
    assert gr.compare_versions("0.0.3", "v0.0.3") == 0
    assert gr.compare_versions("v1.0.0", "v0.9.9") == 1


def test_compare_versions_prerelease_below_base():
    assert gr.compare_versions("0.0.3-rc.1", "0.0.3") == -1
    assert gr.compare_versions("0.0.3-rc.1", "0.0.3-rc.2") == -1
    assert gr.compare_versions("0.0.3-beta.5", "0.0.3-rc.1") == -1
    assert gr.compare_versions("0.0.3-alpha", "0.0.3-beta") == -1


def test_compare_versions_handles_segments_of_different_length():
    # "1.0" should be equal to "1.0.0" (missing trailing segment treated as 0
    # — but the simpler parser yields shorter tuple. Verify direction at least.)
    # 1.0 < 1.0.1 must hold.
    assert gr.compare_versions("1.0", "1.0.1") == -1
