import ipaddress
import json
import socket
from urllib.parse import quote, urlparse, urlunparse

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Plugin
from .plugin_catalog import BAIKE_SEARCH_URL, CATALOG_HOSTS, LEGACY_BAIKE_API_URL
from .schemas import parameter_type_matches, validate_parameter_schema


def validate_plugin_url(url: str) -> tuple[str, str]:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "插件地址格式无效") from exc
    if (len(url) > 2000 or parsed.scheme != "https" or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment
            or host not in get_settings().allowed_plugin_hosts | CATALOG_HOSTS):
        raise HTTPException(400, "插件必须使用白名单内的 HTTPS 主机")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise HTTPException(400, "插件主机解析到非公网地址")
    except socket.gaierror as exc:
        raise HTTPException(400, "无法解析插件主机") from exc
    return host, addresses[0][4][0]


def fetch_plugin_json(url: str, parameters: dict | None = None, max_bytes: int = 1_000_000):
    """Pin the connection to the validated IP while verifying TLS for the original host."""
    host, address = validate_plugin_url(url)
    parsed = urlparse(url)
    authority = f"[{address}]" if ":" in address else address
    pinned_url = urlunparse(parsed._replace(netloc=authority))
    try:
        # Connecting to a numeric IP removes the second DNS lookup (DNS rebinding).
        # Explicit SNI retains certificate/hostname validation; proxies are disabled.
        with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", pinned_url, params=parameters, headers={"Host": host},
                               extensions={"sni_hostname": host}) as response:
                if 300 <= response.status_code < 400:
                    raise HTTPException(502, "插件不允许重定向")
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=16_384):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise HTTPException(413, "插件响应超过大小限制")
                return json.loads(data)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "插件请求失败或响应不是有效 JSON") from exc


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
