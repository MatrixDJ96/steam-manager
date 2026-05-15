"""Tests for the atomic .tar.gz checkpoint API in io/backups.py."""
import tarfile

from steam_manager.io import backups


def test_create_checkpoint_writes_archive(tmp_path):
    src = tmp_path / "config.vdf"
    src.write_text("hello")
    archive = backups.create_checkpoint(
        tmp_path / "backups", "2026-05-13T10-00-00",
        {"config.vdf": src},
        {"trigger": "manual", "files": ["config.vdf"]},
    )
    assert archive.is_file()
    assert archive.suffix == ".gz"
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        assert "config.vdf" in names
        assert "manifest.json" in names


def test_list_checkpoints_finds_archives(tmp_path):
    src = tmp_path / "config.vdf"
    src.write_text("hello")
    backups.create_checkpoint(tmp_path / "bk", "2026-05-13T10-00-00",
                              {"config.vdf": src}, {"trigger": "manual"})
    backups.create_checkpoint(tmp_path / "bk", "2026-05-13T11-00-00",
                              {"config.vdf": src}, {"trigger": "apply"})
    cps = backups.list_checkpoints(tmp_path / "bk")
    assert len(cps) == 2
    assert cps[0]["timestamp"] == "2026-05-13T10-00-00"
    assert cps[1]["timestamp"] == "2026-05-13T11-00-00"
    assert cps[0]["manifest"]["trigger"] == "manual"
    assert "config.vdf" in cps[0]["files"]


def test_list_checkpoints_missing_dir_returns_empty(tmp_path):
    assert backups.list_checkpoints(tmp_path / "nope") == []


def test_extract_checkpoint_roundtrip(tmp_path):
    src = tmp_path / "config.vdf"
    src.write_text("original")
    archive = backups.create_checkpoint(tmp_path / "bk", "ts",
                                        {"config.vdf": src}, {})
    dest = tmp_path / "restored.vdf"
    extracted = backups.extract_checkpoint(archive, {"config.vdf": dest})
    assert extracted == ["config.vdf"]
    assert dest.read_text() == "original"


def test_extract_checkpoint_skips_missing_member(tmp_path):
    src = tmp_path / "config.vdf"
    src.write_text("x")
    archive = backups.create_checkpoint(tmp_path / "bk", "ts",
                                        {"config.vdf": src}, {})
    dest_known = tmp_path / "a.vdf"
    dest_missing = tmp_path / "b.vdf"
    extracted = backups.extract_checkpoint(
        archive,
        {"config.vdf": dest_known, "users/x/localconfig.vdf": dest_missing},
    )
    assert extracted == ["config.vdf"]
    assert dest_known.read_text() == "x"
    assert not dest_missing.exists()


def test_prune_checkpoints_keeps_latest(tmp_path):
    src = tmp_path / "config.vdf"
    src.write_text("hello")
    root = tmp_path / "bk"
    for ts in ["2026-05-10T00", "2026-05-11T00", "2026-05-12T00", "2026-05-13T00"]:
        backups.create_checkpoint(root, ts, {"config.vdf": src}, {})
    removed = backups.prune_checkpoints(root, limit=2)
    assert len(removed) == 2
    remaining = sorted(p.name for p in root.glob("*.tar.gz"))
    assert remaining == ["2026-05-12T00.tar.gz", "2026-05-13T00.tar.gz"]


def test_prune_checkpoints_below_limit_noop(tmp_path):
    src = tmp_path / "c.vdf"
    src.write_text("x")
    root = tmp_path / "bk"
    backups.create_checkpoint(root, "ts1", {"config.vdf": src}, {})
    assert backups.prune_checkpoints(root, limit=5) == []
    assert len(list(root.glob("*.tar.gz"))) == 1
