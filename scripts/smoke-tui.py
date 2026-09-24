#!/usr/bin/env python3
# steam-manager frozen-binary TUI smoke.
#
# Usage:
#   ./scripts/smoke-tui.py                          # checks dist/steam-manager
#   ./scripts/smoke-tui.py path/to/steam-manager
#
# Opens the `config` editor and the `scopebuddy` dashboard of a built binary in
# a pseudo-terminal, waits for each header, sends `q`, and exits 1 on a missing
# header, a traceback, a non-zero exit or a timeout. Every path the binary could
# write points into a throwaway Steam tree, so the live install is never read or
# touched. Python, not shell: bash has no PTY without script(1) or expect.
import fcntl
import os
import pty
import re
import select
import signal
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path

TIMEOUT = 20.0
CHECKS = [
    ("config", "steam-manager · config"),
    ("scopebuddy", "steam-manager · scopebuddy"),
]


def fake_steam(tmp: Path) -> Path:
    """A Steam root with one active account and no games."""
    root = tmp / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t"{root}"\n\t}}\n}}\n'
    )
    (root / "config" / "loginusers.vdf").write_text(
        '"users"\n{\n\t"76561198000000000"\n\t{\n'
        '\t\t"AccountName"\t"smoke"\n\t\t"MostRecent"\t"1"\n\t}\n}\n'
    )
    return root


def run_tui(binary: str, command: str, header: str, env: dict) -> str | None:
    """Run one TUI in a PTY; return a failure reason, or None when it passed."""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            os.execve(binary, [binary, command], env)
        finally:
            os._exit(127)

    out = b""
    quit_sent = False
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:  # EIO: the child closed the terminal
                chunk = b""
            if not chunk:
                break
            out += chunk
        if not quit_sent and header.encode() in out:
            time.sleep(0.5)  # let the app bind its keys before `q` arrives
            os.write(fd, b"q")
            quit_sent = True
    else:
        os.kill(pid, signal.SIGKILL)
    os.close(fd)
    _, status = os.waitpid(pid, 0)

    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.decode("utf-8", "replace"))
    if "Traceback" in text:
        return "traceback:\n" + text[text.index("Traceback"):]
    if not quit_sent:
        return f"header {header!r} never drew"
    if os.WIFSIGNALED(status):
        return f"no exit within {TIMEOUT:.0f}s of start"
    if os.WEXITSTATUS(status) != 0:
        return f"exit status {os.WEXITSTATUS(status)}"
    return None


def main() -> int:
    binary = sys.argv[1] if len(sys.argv) > 1 else "dist/steam-manager"
    failed = False
    with tempfile.TemporaryDirectory(prefix="steam-manager-smoke-") as tmp_dir:
        tmp = Path(tmp_dir)
        env = dict(
            os.environ,
            TERM=os.environ.get("TERM", "xterm-256color"),
            STEAM_MANAGER_STEAM_ROOT=str(fake_steam(tmp)),
            STEAM_MANAGER_BACKUP_ROOT=str(tmp / "backups"),
            STEAM_MANAGER_SCB_DIR=str(tmp / "scopebuddy"),
            STEAM_MANAGER_USER_POLICY=str(tmp / "policies.toml"),
            STEAM_MANAGER_CONFIG_UI="tui",
            STEAM_MANAGER_SCB_UI="tui",
            STEAM_MANAGER_NO_UPDATE_NOTIFIER="1",
        )
        env.pop("STEAM_MANAGER_POLICY_PATHS", None)
        for command, header in CHECKS:
            reason = run_tui(binary, command, header, env)
            print(f"{'ok' if reason is None else 'FAIL'}  {command}"
                  + ("" if reason is None else f": {reason}"))
            failed = failed or reason is not None
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
