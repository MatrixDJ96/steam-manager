"""Pytest fixtures comuni per la suite di test."""
import json
from pathlib import Path
import shutil

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _disable_update_notifier(monkeypatch):
    """Belt-and-suspenders: forbid the notifier in every test.

    The notifier already self-skips when not frozen (CliRunner is unfrozen),
    but if any test ever sets sys.frozen=True without overriding this env var,
    we'd accidentally try a real HTTP call. This env var blocks it explicitly.
    """
    monkeypatch.setenv("STEAM_MANAGER_NO_UPDATE_NOTIFIER", "1")


@pytest.fixture(autouse=True)
def _isolate_system_compat_dirs(monkeypatch):
    """Keep real system compat-tool dirs out of the suite.

    `io.compat_tools` scans `/usr/share/steam/compatibilitytools.d/` (and the
    `/usr/local` sibling) by default — on a dev machine those hold real Proton
    builds that would leak into discovery assertions. An empty override means
    no system dirs; tests that exercise system discovery set it explicitly.
    """
    monkeypatch.setenv("STEAM_MANAGER_COMPAT_DIRS", "")


@pytest.fixture
def fake_urlopen(monkeypatch):
    """Intercept urllib.request.urlopen with a configurable URL→response map.

    Tests register expected URLs via `fake_urlopen.add(...)`. Unmatched URLs
    raise AssertionError so a missing registration becomes a loud test
    failure instead of silently hitting the real network.

    Example:
        def test_x(fake_urlopen):
            fake_urlopen.add(
                "https://api.github.com/repos/X/Y/releases/latest",
                json_body={"tag_name": "v0.0.3", "html_url": "...", "body": "..."},
            )
            ...
    """
    class _Resp:
        def __init__(self, body: bytes, status: int = 200):
            self._body, self.status = body, status

        def read(self, n: int = -1) -> bytes:
            if n < 0:
                out, self._body = self._body, b""
                return out
            out, self._body = self._body[:n], self._body[n:]
            return out

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            pass

    class _Registry:
        def __init__(self):
            self._map: dict[str, tuple[bytes, int]] = {}
            self.calls: list[str] = []

        def add(self, url: str, *, body: bytes | None = None,
                json_body: dict | None = None, status: int = 200) -> None:
            if json_body is not None:
                body = json.dumps(json_body).encode("utf-8")
            self._map[url] = (body or b"", status)

        def add_error(self, url: str, *, status: int = 404) -> None:
            self._map[url] = (b"", status)

        def __call__(self, req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else req
            self.calls.append(url)
            if url not in self._map:
                raise AssertionError(f"unmocked URL: {url}")
            body, status = self._map[url]
            if status >= 400:
                from urllib.error import HTTPError
                raise HTTPError(url, status, "mocked", {}, None)
            return _Resp(body, status)

    reg = _Registry()
    monkeypatch.setattr("urllib.request.urlopen", reg)
    return reg


@pytest.fixture
def fake_steam(tmp_path: Path) -> Path:
    root = tmp_path / ".local" / "share" / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "userdata" / "72021823" / "config").mkdir(parents=True)

    lib2 = tmp_path / "disk2" / "Steam" / "steamapps"
    lib2.mkdir(parents=True)

    # libraryfolders.vdf reale (con path che esistono in tmp_path)
    libfolders = f"""\
"libraryfolders"
{{
    "0"
    {{
        "path"  "{root}"
        "label" "TestLinux"
        "apps"
        {{
            "111"  "1000"
        }}
    }}
    "1"
    {{
        "path"  "{tmp_path}/disk2/Steam"
        "label" "TestDisk2"
        "apps"
        {{
            "222"  "2000"
        }}
    }}
}}
"""
    (root / "steamapps" / "libraryfolders.vdf").write_text(libfolders)

    shutil.copy(FIXTURES / "appmanifest_111.acf", root / "steamapps" / "appmanifest_111.acf")
    shutil.copy(FIXTURES / "appmanifest_222b.acf", lib2 / "appmanifest_222.acf")
    shutil.copy(FIXTURES / "config.vdf", root / "config" / "config.vdf")
    shutil.copy(FIXTURES / "loginusers.vdf", root / "config" / "loginusers.vdf")
    shutil.copy(FIXTURES / "localconfig.vdf",
                root / "userdata" / "72021823" / "config" / "localconfig.vdf")

    return root


@pytest.fixture
def env(fake_steam: Path, tmp_path: Path, monkeypatch) -> Path:
    """Point steam_root at fake_steam and the user policy at a tmp file
    (factory still merged underneath). Returns the user-policy path."""
    monkeypatch.setenv("STEAM_MANAGER_STEAM_ROOT", str(fake_steam))
    user = tmp_path / "user.toml"
    monkeypatch.setenv("STEAM_MANAGER_USER_POLICY", str(user))
    monkeypatch.delenv("STEAM_MANAGER_POLICY_PATHS", raising=False)
    return user
