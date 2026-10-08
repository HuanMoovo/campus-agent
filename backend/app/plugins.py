"""Plugin egress and installation: public-HTTPS fetch gate, GitHub custom install, invocation.

Plugins are declarative JSON-over-HTTPS registrations only — no remote code is
ever downloaded or executed by this module.
"""
import ipaddress
import json
import re
import socket
from urllib.parse import quote, urlparse, urlunparse

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Plugin
from .schemas import parameter_type_matches, validate_parameter_schema


BAIKE_SEARCH_URL = "https://baike.baidu.com/search/word"
LEGACY_BAIKE_API_URL = "https://baike.baidu.com/api/openapi/BaikeLemmaCardApi?appid=379020"

GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
GITHUB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?$")
GITHUB_REF_PATTERN = re.compile(r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
MANIFEST_MAX_BYTES = 100_000


def _parse_plugin_url(url: str) -> str:
    """Shared URL syntax checks for every plugin-related fetch; returns the host."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "插件地址格式无效") from exc
    if (len(url) > 2000 or parsed.scheme != "https" or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment
            or not host):
        raise HTTPException(400, "插件必须使用 HTTPS 公网地址") from None
    return host


def _resolve_public_ips(host: str) -> list[str]:
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(400, "无法解析插件主机") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise HTTPException(400, "插件主机解析到非公网地址")
    resolved: list[str] = []
    for item in addresses:
        address = item[4][0]
        if address not in resolved:
            resolved.append(address)
    return resolved


def validate_plugin_url(url: str) -> tuple[str, list[str]]:
    """Gate for plugin egress: a public HTTPS host, plus PLUGIN_ALLOWED_HOSTS when set."""
    host = _parse_plugin_url(url)
    allowed = get_settings().allowed_plugin_hosts
    if allowed and host not in allowed:
        raise HTTPException(400, "插件主机不在白名单内")
    return host, _resolve_public_ips(host)


class _TransportFailure(Exception):
    """One pinned connection attempt failed at the transport layer."""


def _stream_from_address(url: str, host: str, address: str, parameters: dict | None, max_bytes: int) -> tuple[int, object | None]:
    parsed = urlparse(url)
    authority = f"[{address}]" if ":" in address else address
    pinned_url = urlunparse(parsed._replace(netloc=authority))
    try:
        # Connecting to a numeric IP removes the second DNS lookup (DNS rebinding).
        # Explicit SNI retains certificate/hostname validation; proxies are disabled.
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", pinned_url, params=parameters, headers={"Host": host},
                               extensions={"sni_hostname": host}) as response:
                if 300 <= response.status_code < 400:
                    raise HTTPException(502, "插件不允许重定向")
                if response.status_code != 200:
                    return response.status_code, None
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=16_384):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise HTTPException(413, "插件响应超过大小限制")
                try:
                    return 200, json.loads(data)
                except ValueError as exc:
                    raise HTTPException(502, "插件响应不是有效 JSON") from exc
    except httpx.HTTPError as exc:
        raise _TransportFailure(str(exc)) from exc


def _stream_plugin_json(url: str, host: str, addresses: list[str], parameters: dict | None, max_bytes: int) -> tuple[int, object | None]:
    """Try each resolved address until one completes a full request/response cycle.

    Some networks reset connections to individual CDN addresses while other
    addresses of the same host work (observed with jsDelivr), so pinning to the
    first resolved address alone is not reliable.
    """
    failure: _TransportFailure | None = None
    for address in addresses[:2]:
        try:
            return _stream_from_address(url, host, address, parameters, max_bytes)
        except _TransportFailure as exc:
            failure = exc
    raise HTTPException(502, "插件请求失败或响应不是有效 JSON") from failure


def fetch_plugin_json(url: str, parameters: dict | None = None, max_bytes: int = 1_000_000):
    host, addresses = validate_plugin_url(url)
    status, data = _stream_plugin_json(url, host, addresses, parameters, max_bytes)
    if status != 200:
        raise HTTPException(502, "插件请求失败或响应不是有效 JSON")
    return data


def fetch_manifest_json(url: str, *, use_url_whitelist: bool = False):
    """Fetch a plugin manifest (JSON object) from a public HTTPS host.

    The fixed GitHub hosts used for custom installs skip the optional
    PLUGIN_ALLOWED_HOSTS gate; direct manifest URLs honour it.
    """
    if use_url_whitelist:
        host, addresses = validate_plugin_url(url)
    else:
        host = _parse_plugin_url(url)
        addresses = _resolve_public_ips(host)
    status, data = _stream_plugin_json(url, host, addresses, None, MANIFEST_MAX_BYTES)
    if status == 404:
        raise HTTPException(404, "未找到插件清单")
    if status != 200:
        raise HTTPException(502, "无法读取插件清单")
    return data


def parse_github_source(source: str) -> tuple[str, str, str]:
    """Parse a GitHub link into (owner, repo, ref); the default ref is HEAD."""
    try:
        parsed = urlparse(source)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "GitHub 地址格式无效") from exc
    if (parsed.scheme != "https" or (parsed.hostname or "").lower() not in GITHUB_HOSTS
            or port not in (None, 443) or parsed.username is not None or parsed.password is not None):
        raise HTTPException(400, "仅支持 https://github.com/<所有者>/<仓库> 地址")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise HTTPException(400, "GitHub 地址需包含仓库所有者与名称")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    ref = "HEAD"
    if len(parts) > 2:
        mode, tail = parts[2], parts[3:]
        if mode == "tree" and tail:
            ref = "/".join(tail)
        elif mode in ("blob", "raw") and len(tail) >= 2 and tail[-1] == "plugin.json":
            ref = "/".join(tail[:-1])
        else:
            raise HTTPException(400, "仅支持仓库首页、/tree/<分支> 或 /blob/<分支>/plugin.json 链接")
    if not GITHUB_NAME_PATTERN.match(owner) or not GITHUB_NAME_PATTERN.match(repo):
        raise HTTPException(400, "GitHub 所有者或仓库名包含无效字符")
    if ref != "HEAD" and not GITHUB_REF_PATTERN.match(ref):
        raise HTTPException(400, "分支或引用名无效")
    return owner, repo, ref


def github_manifest_urls(owner: str, repo: str, ref: str) -> list[str]:
    """Candidate manifest locations: jsDelivr CDNs first (CN-friendly), raw as the last resort."""
    return [
        f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{ref}/plugin.json",
        f"https://fastly.jsdelivr.net/gh/{owner}/{repo}@{ref}/plugin.json",
        f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/plugin.json",
    ]


def fetch_github_manifest(source: str) -> dict:
    """Read plugin.json from a GitHub repository, trying jsDelivr CDNs then raw."""
    owner, repo, ref = parse_github_source(source)
    errors: list[HTTPException] = []
    for url in github_manifest_urls(owner, repo, ref):
        try:
            data = fetch_manifest_json(url)
        except HTTPException as exc:
            errors.append(exc)
            continue
        if not isinstance(data, dict):
            raise HTTPException(422, "插件清单格式无效：应为 JSON 对象")
        return data
    if any(exc.status_code == 413 for exc in errors):
        raise HTTPException(413, "插件清单超过大小限制")
    if any(exc.status_code == 404 for exc in errors):
        raise HTTPException(404, "仓库根目录未找到 plugin.json（请确认文件存在且仓库公开）")
    raise HTTPException(502, "无法访问该 GitHub 仓库（网络不可达或仓库为私有）")


def validate_plugin_parameters(parameters: dict, schema: dict) -> dict:
    try:
        schema = validate_parameter_schema(schema)
    except ValueError as exc:
        raise HTTPException(400, "插件参数定义无效，请重新安装插件") from exc
    properties = schema["properties"]
    if set(parameters) - set(properties):
        raise HTTPException(400, "插件参数不在允许列表中")
    if set(schema["required"]) - set(parameters):
        raise HTTPException(400, "缺少插件必填参数")
    for name, value in parameters.items():
        spec = properties[name]
        if not parameter_type_matches(value, spec["type"]):
            raise HTTPException(400, f"参数 {name} 类型无效")
        if "enum" in spec and value not in spec["enum"]:
            raise HTTPException(400, f"参数 {name} 不在允许值范围内")
        if spec["type"] == "string":
            if not spec.get("minLength", 0) <= len(value) <= spec.get("maxLength", 4000):
                raise HTTPException(400, f"参数 {name} 长度无效")
        elif spec["type"] in {"integer", "number"}:
            if not spec.get("minimum", float("-inf")) <= value <= spec.get("maximum", float("inf")):
                raise HTTPException(400, f"参数 {name} 超出范围")
    return parameters


def invoke_plugin(db: Session, name: str, parameters: dict) -> dict:
    from sqlalchemy import select

    plugin = db.scalar(select(Plugin).where(Plugin.name == name, Plugin.enabled.is_(True)))
    if plugin is None:
        raise HTTPException(404, "插件不可用")
    validated = validate_plugin_parameters(parameters, plugin.parameters)
    if plugin.name == "baidu_baike_search" and plugin.url in (BAIKE_SEARCH_URL, LEGACY_BAIKE_API_URL):
        query = validated.get("bk_key")
        if (not isinstance(query, str) or not query.strip() or len(query) > 200
                or any(ord(char) < 32 or 127 <= ord(char) <= 159
                       or 0xD800 <= ord(char) <= 0xDFFF for char in query)):
            raise HTTPException(400, "百科搜索词必须为 1 至 200 个有效字符")
        # Baidu's public website is opened by the user. Do not call its retired
        # unofficial JSON endpoint or allow a manifest to choose an external URL.
        return {"plugin": name, "result": {"url": BAIKE_SEARCH_URL + "?word=" + quote(query.strip(), safe=""), "external": True}}
    return {"plugin": name, "result": fetch_plugin_json(plugin.url, validated)}
