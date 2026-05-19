from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path


PLUGIN_NAME = "bn_agent_bridge"
SKILL_NAME = "bn"

IS_WINDOWS = platform.system() == "Windows"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".codex"


def claude_home() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".claude"


def cache_home() -> Path:
    env = os.environ.get("BN_CACHE_DIR")
    if env:
        return Path(env).expanduser()

    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Caches" / "bn"
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "bn"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "bn"
    return home / ".cache" / "bn"


def bridge_registry_path() -> Path:
    return cache_home() / f"{PLUGIN_NAME}.json"


def bridge_socket_path() -> Path:
    return cache_home() / f"{PLUGIN_NAME}.sock"


BRIDGE_HOST = "127.0.0.1"


def bridge_port_file() -> Path:
    return cache_home() / f"{PLUGIN_NAME}.port"


def bridge_listen_address() -> tuple[str, int]:
    """Return (host, port) for the bridge server to listen on."""
    return (BRIDGE_HOST, 0)


def bridge_connect_address() -> tuple[str, int]:
    pf = bridge_port_file()
    try:
        port = int(pf.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(f"Bridge port file not found or invalid: {pf}") from exc
    return (BRIDGE_HOST, port)


def api_docs_index_path() -> Path:
    return cache_home() / "api_docs_index.json"


def spill_root() -> Path:
    root = Path(tempfile.gettempdir()) / "bn-spills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def plugin_source_dir() -> Path:
    return repo_root() / "plugin" / PLUGIN_NAME


def binary_ninja_plugin_dir() -> Path:
    env = os.environ.get("BN_PLUGIN_DIR")
    if env:
        return Path(env).expanduser()

    home = Path.home()
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Binary Ninja" / "plugins"
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / "Binary Ninja" / "plugins"
    return home / ".binaryninja" / "plugins"


def plugin_install_dir() -> Path:
    return binary_ninja_plugin_dir() / PLUGIN_NAME


def codex_skills_dir() -> Path:
    return codex_home() / "skills"


def claude_skills_dir() -> Path:
    return claude_home() / "skills"


def skill_source_dir() -> Path:
    return repo_root() / "skills" / SKILL_NAME


def skill_install_dir() -> Path:
    return codex_skills_dir() / SKILL_NAME


def claude_skill_install_dir() -> Path:
    return claude_skills_dir() / SKILL_NAME


SKILL_CLIENTS: tuple[str, ...] = ("codex", "claude-code")


def skill_install_dir_for(client: str) -> Path:
    if client == "codex":
        return skill_install_dir()
    if client == "claude-code":
        return claude_skill_install_dir()
    raise ValueError(f"Unknown skill client: {client}")
