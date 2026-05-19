from __future__ import annotations

import contextlib
import errno
import json
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import bridge_registry_path, IS_WINDOWS


class BridgeError(RuntimeError):
    pass


TRANSIENT_SOCKET_ERRNOS = {
    errno.ECONNREFUSED,
    errno.ENOENT,
}

DENIED_SOCKET_ERRNOS = {
    errno.EACCES,
    errno.EPERM,
}


@dataclass(slots=True)
class BridgeInstance:
    pid: int
    socket_path: Path
    registry_path: Path
    plugin_name: str
    plugin_version: str
    started_at: str | None
    meta: dict[str, Any]
    host: str | None = None
    port: int | None = None


def _is_tcp_instance(instance: BridgeInstance) -> bool:
    return IS_WINDOWS and instance.host is not None and instance.port is not None


def _purge_stale_registry(registry_path: Path) -> None:
    with contextlib.suppress(OSError):
        registry_path.unlink()


def _socket_probe_error(
    instance: BridgeInstance, timeout: float = 0.2
) -> OSError | None:
    try:
        if _is_tcp_instance(instance):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((instance.host, instance.port))
        else:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(instance.socket_path))
        return None
    except OSError as exc:
        return exc


def _connect_and_send(
    instance: BridgeInstance,
    encoded: bytes,
    chunks: list[bytes],
    timeout: float | None,
) -> None:
    if _is_tcp_instance(instance):
        family, connect_addr = socket.AF_INET, (instance.host, instance.port)
    else:
        family, connect_addr = socket.AF_UNIX, str(instance.socket_path)
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if timeout is not None:
            sock.settimeout(timeout)
        sock.connect(connect_addr)
        sock.sendall(encoded)
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_WR)
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)


def _load_instance(path: Path) -> BridgeInstance | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        socket_path = Path(payload["socket_path"])
        pid = int(payload["pid"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None

    host = payload.get("host")
    port = payload.get("port")

    if IS_WINDOWS and host is not None and port is not None:
        # On Windows, probe the TCP port instead of checking file existence
        pass
    elif not socket_path.exists():
        _purge_stale_registry(path)
        return None

    probe_error = _socket_probe_error(
        BridgeInstance(
            pid=pid,
            socket_path=socket_path,
            registry_path=path,
            host=host,
            port=port,
            plugin_name="",
            plugin_version="",
            started_at=None,
            meta=payload,
        )
    )
    if probe_error is not None and probe_error.errno in DENIED_SOCKET_ERRNOS:
        payload["socket_probe_error"] = str(probe_error)
    elif probe_error is not None:
        _purge_stale_registry(path)
        return None

    return BridgeInstance(
        pid=pid,
        socket_path=socket_path,
        registry_path=path,
        host=host,
        port=port,
        plugin_name=str(payload.get("plugin_name", "bn_agent_bridge")),
        plugin_version=str(payload.get("plugin_version", "0")),
        started_at=payload.get("started_at"),
        meta=payload,
    )


def list_instances() -> list[BridgeInstance]:
    fixed_registry = bridge_registry_path()
    if not fixed_registry.exists():
        return []

    instances: list[BridgeInstance] = []
    instance = _load_instance(fixed_registry)
    if instance is not None:
        instances.append(instance)
    return instances


def choose_instance() -> BridgeInstance:
    instances = list_instances()
    if not instances:
        raise BridgeError("No running Binary Ninja bridge instances found")
    return instances[0]


def _send_request_to_instance(
    instance: BridgeInstance,
    op: str,
    *,
    params: dict[str, Any] | None = None,
    target: str | None = None,
    timeout: float | None = None,
    connect_retries: int = 4,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "op": op,
        "params": params or {},
    }
    if target is not None:
        payload["target"] = target

    encoded = (json.dumps(payload) + "\n").encode("utf-8")

    chunks: list[bytes] = []
    last_error: OSError | None = None
    for attempt in range(connect_retries):
        try:
            _connect_and_send(instance, encoded, chunks, timeout)
            break
        except OSError as exc:
            last_error = exc
            if exc.errno not in TRANSIENT_SOCKET_ERRNOS or attempt == connect_retries - 1:
                break
            time.sleep(0.05 * (attempt + 1))

    if last_error is not None and not chunks:
        if _is_tcp_instance(instance):
            address = f"{instance.host}:{instance.port}"
        else:
            address = str(instance.socket_path)
        if isinstance(last_error, TimeoutError):
            timeout_suffix = f" after {timeout:.1f}s" if timeout is not None else ""
            raise BridgeError(
                f"Timed out waiting for Binary Ninja bridge pid {instance.pid} at {address}"
                f"{timeout_suffix}"
            ) from last_error
        raise BridgeError(
            f"Failed to contact Binary Ninja bridge pid {instance.pid} at {address}: {last_error}"
        ) from last_error

    if not chunks:
        raise BridgeError("Binary Ninja bridge returned an empty response")

    try:
        response = json.loads(b"".join(chunks).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BridgeError("Binary Ninja bridge returned invalid JSON") from exc

    if not isinstance(response, dict):
        raise BridgeError("Binary Ninja bridge returned a malformed response")

    if response.get("ok"):
        return response

    error = response.get("error") or "Unknown Binary Ninja bridge error"
    raise BridgeError(str(error))


def send_request(
    op: str,
    *,
    params: dict[str, Any] | None = None,
    target: str | None = None,
    timeout: float | None = None,
    connect_retries: int = 4,
) -> dict[str, Any]:
    instance = choose_instance()
    return _send_request_to_instance(
        instance,
        op,
        params=params,
        target=target,
        timeout=timeout,
        connect_retries=connect_retries,
    )
