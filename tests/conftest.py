import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    ra = tmp_path / "ra_home"
    claude = tmp_path / "claude_home"
    ra.mkdir()
    claude.mkdir()
    monkeypatch.setenv("RA_HOME", str(ra))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    return {"ra": ra, "claude": claude}


@pytest.fixture
def project(tmp_path, tmp_home):
    p = tmp_path / "proj"
    state = p / ".research-agent"
    state.mkdir(parents=True)
    (state / "project.toml").write_text(
        '[data]\nprotected_paths = ["data/raw"]\nsensitive_paths = ["data/phi"]\n',
        encoding="utf-8",
    )
    (p / "data" / "raw").mkdir(parents=True)
    (p / "data" / "phi").mkdir(parents=True)
    return p
