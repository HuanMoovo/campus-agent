"""User-configured HTTPS JSON connectors for campus information systems."""
from __future__ import annotations

import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from .config import get_settings
from .model_runtime import _decrypt, _encrypt


KINDS = {
    "grades": "成绩", "schedule": "课表", "credits": "学分",
    "classrooms": "空教室", "repairs": "报修",
    "notices": "校园公告", "library": "图书馆", "dining": "餐饮",
    "shuttle": "校车",
}
_lock = threading.RLock()
MAX_RESPONSE_BYTES = 2_000_000


def _path() -> Path:
    return Path(getattr(get_settings(), "data_dir", Path(__file__).resolve().parents[1] / "data")) / "campus-sources.json"


def _load() -> dict:
    path = _path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as exc:
        raise HTTPException(503, "校园数据源配置无法读取，请重新配置") from exc
    if (not isinstance(value, dict) or any(
            kind not in KINDS or not isinstance(source, dict)
            or not isinstance(source.get("url"), str) or not source["url"]
            or not isinstance(source.get("result_path", ""), str)
            or not isinstance(source.get("token", ""), str)
            for kind, source in value.items())):
        raise HTTPException(503, "校园数据源配置无效，请重新配置")
    return value


def _save(value: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".campus-sources-", suffix=".tmp", delete=False) as stream:
            name = stream.name
            os.chmod(name, 0o600)
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _validated_target(url: str) -> tuple[str, str, str]:
    try:
        if not isinstance(url, str):
            raise ValueError()
        parsed = urlsplit(url)
        if (len(url) > 2000 or parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or parsed.port not in (None, 443)
                or any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in url)):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = [ipaddress.ip_address(row[4][0]) for row in addresses]
        if not ips or any(not address.is_global or address.is_multicast or address.is_reserved for address in ips):
            raise ValueError()
        address = addresses[0][4][0]
        authority = f"[{address}]" if ":" in address else address
        pinned_url = urlunsplit(parsed._replace(netloc=authority))
    except (ValueError, UnicodeError, OSError, IndexError) as exc:
        raise HTTPException(422, "数据接口须为可解析的公网 HTTPS 地址") from exc
    return host, address, pinned_url


def _validate_url(url: str) -> str:
    _validated_target(url)
    return url


def _validate_result_path(value: str) -> str:
    if len(value) > 200 or (value and any(not part.isidentifier() for part in value.split("."))):
        raise HTTPException(422, "结果路径应为点分隔的 JSON 字段名，例如 data.items")
    return value


def _normalize_result(kind: str, value: object) -> dict:
    if kind == "credits":
        if (not isinstance(value, dict) or any(
            not _nonnegative_number(value.get(key))
            for key in ("required", "earned")
        )):
            raise HTTPException(502, "学分接口须返回非负数值 required 和 earned")
        return {"demo": False, "required": value["required"], "earned": value["earned"]}
    if kind == "repairs":
        if not isinstance(value, dict):
            raise HTTPException(502, "报修接口须返回 JSON 对象")
        return {"demo": False, "result": value}
    if isinstance(value, dict):
        items = value.get("items")
    else:
        items = value
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise HTTPException(502, "校园列表接口须返回对象数组或包含 items 对象数组的 JSON 对象")
    for row in items:
        if kind == "grades":
            valid = (_text(row.get("course"))
                     and (_nonnegative_number(row.get("score")) or _text(row.get("score")))
                     and ("credits" not in row or _nonnegative_number(row["credits"]))
                     and ("semester" not in row or _text(row["semester"])))
            expected = "course、score，及可选的 credits、semester"
        elif kind == "schedule":
            valid = all(_text(row.get(key)) for key in ("course", "weekday", "time", "room"))
            expected = "course、weekday、time、room"
        elif kind == "classrooms":
            valid = (all(_text(row.get(key)) for key in ("building", "room"))
                     and type(row.get("seats")) is int and row["seats"] >= 0
                     and ("available" not in row or type(row["available"]) is bool))
            expected = "building、room、非负整数 seats，及可选布尔值 available"
        else:
            continue
        if not valid:
            raise HTTPException(502, f"{KINDS[kind]}接口记录格式无效，须包含 {expected}")
    return {"demo": False, "items": items}


def _nonnegative_number(value: object) -> bool:
    return type(value) in (int, float) and 0 <= value <= 1e308


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def list_sources() -> list[dict]:
    stored = _load()
    return [{"kind": kind, "label": label, "configured": kind in stored,
             "url": stored.get(kind, {}).get("url", ""),
             "result_path": stored.get(kind, {}).get("result_path", ""),
             "has_token": bool(stored.get(kind, {}).get("token"))}
            for kind, label in KINDS.items()]


def configure_source(kind: str, body: dict) -> dict:
    if kind not in KINDS:
        raise HTTPException(404, "未知校园数据类型")
    if set(body) - {"url", "result_path", "token", "clear_token"}:
        raise HTTPException(422, "不支持的配置字段")
    if "clear_token" in body and type(body["clear_token"]) is not bool:
        raise HTTPException(422, "clear_token 必须为布尔值")
    if body.get("clear_token") and "token" in body:
        raise HTTPException(422, "清除令牌与设置令牌不可同时使用")
    changes = {}
    if "url" in body:
        if not isinstance(body["url"], str):
            raise HTTPException(422, "接口地址无效")
        changes["url"] = _validate_url(body["url"].strip())
    if "result_path" in body:
        if not isinstance(body["result_path"], str):
            raise HTTPException(422, "结果路径无效")
        changes["result_path"] = _validate_result_path(body["result_path"].strip())
    if "token" in body:
        token = body["token"]
        if not isinstance(token, str) or not 1 <= len(token) <= 4096 or any(not 33 <= ord(c) <= 126 for c in token):
            raise HTTPException(422, "访问令牌无效")
        try:
            changes["token"] = _encrypt(token)
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "无法安全保存访问令牌") from exc
    with _lock:
        stored = _load()
        current = dict(stored.get(kind, {}))
        # A saved secret belongs to its original host, never a replacement host.
        changed_host = ("url" in changes and current.get("url")
                        and urlsplit(current["url"]).hostname != urlsplit(changes["url"]).hostname)
        if body.get("clear_token") or changed_host:
            current.pop("token", None)
        current.update(changes)
        if not current.get("url"):
            raise HTTPException(422, "请填写接口地址")
        stored[kind] = current
        _save(stored)
    return next(row for row in list_sources() if row["kind"] == kind)


def remove_source(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(404, "未知校园数据类型")
    with _lock:
        stored = _load()
        stored.pop(kind, None)
        _save(stored)


def configured(kind: str) -> bool:
    return kind in _load()


def fetch_source(kind: str, payload: dict | None = None) -> dict:
    if kind not in KINDS:
        raise HTTPException(404, "未知校园数据类型")
    current = _load().get(kind)
    if not current:
        return {"demo": True, "items": []}
    try:
        host, _, pinned_url = _validated_target(current["url"])
    except (KeyError, TypeError) as exc:
        raise HTTPException(422, "校园数据源配置无效") from exc
    headers = {"Accept": "application/json"}
    if current.get("token"):
        try:
            headers["Authorization"] = "Bearer " + _decrypt(current["token"])
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "访问令牌无法解密，请重新保存令牌") from exc
    headers["Host"] = f"[{host}]" if ":" in host else host
    try:
        with httpx.Client(timeout=12, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST" if kind == "repairs" else "GET", pinned_url,
                               headers=headers, json=payload if kind == "repairs" else None,
                               extensions={"sni_hostname": host}) as response:
                if 300 <= response.status_code < 400:
                    raise HTTPException(502, "校园接口不允许跳转")
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=65_536):
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise HTTPException(413, "校园接口响应超过 2 MB")
                    content.extend(chunk)
                value = json.loads(content, parse_float=_finite_float,
                                   parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (httpx.HTTPError, ValueError, RecursionError) as exc:
        raise HTTPException(502, "校园数据接口请求失败，请检查地址、令牌和学校网络") from exc
    for key in current.get("result_path", "").split("."):
        if not key:
            continue
        if not isinstance(value, dict) or key not in value:
            raise HTTPException(502, "校园接口响应中找不到配置的结果路径")
        value = value[key]
    return _normalize_result(kind, value)
