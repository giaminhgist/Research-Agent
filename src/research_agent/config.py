"""Layered TOML configuration: repo defaults < ~/.research-agent/config.toml < project.toml."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from . import paths


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(project: Path | None = None) -> dict:
    cfg = _read(paths.plugin_root() / "config" / "default.toml")
    cfg = _merge(cfg, _read(paths.ra_home() / "config.toml"))
    if project is not None:
        cfg = _merge(cfg, _read(paths.state_dir(project) / "project.toml"))
    return cfg


def get(cfg: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
