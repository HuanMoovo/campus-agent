"""Optional live web search and page reading for the chat agent.

Everything here is opt-in: an administrator enables it and each chat request still
chooses whether to use it. Outbound requests keep the same safety properties as plugin
calls — HTTPS on port 443, public IPs only, the connection pinned to the resolved
address with SNI/hostname checks retained, no redirects, and size/time caps.
"""
from __future__ import annotations

import html as html_module
import ipaddress
import json
import os
import re
import socket
import tempfile
import threading
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from .config import get_settings
from .model_runtime import _decrypt, _encrypt

BING_SEARCH_URL = "https://cn.bing.com/search"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"
PROVIDERS = ("auto", "bing", "tavily", "bocha")
KEYED_PROVIDERS = ("tavily", "bocha")
PROVIDER_LABELS = {"auto": "自动选择", "bing": "Bing 网页搜索（免密钥）", "tavily": "Tavily", "bocha": "博查 AI 搜索"}
CONFIG_FILE = "web-search.json"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
MAX_QUERY = 200
MAX_URL = 2000
MAX_PAGE_BYTES = 400_000
MAX_PAGE_TEXT = 2_000
MAX_SNIPPET = 400
MAX_RESULTS = 8
MAX_FETCH_PAGES = 3
SKIP_TAGS = ("script", "style", "noscript", "template", "svg", "head", "iframe")
BLOCK_TAGS = ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "br", "td", "th")
_lock = threading.RLock()


class WebSearchError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# --------------------------------------------------------------------------- config


def _config_path() -> Path:
    settings = get_settings()
    data_dir = getattr(settings, "data_dir", None) or Path(__file__).resolve().parents[1] / "data"
    return Path(data_dir) / CONFIG_FILE


def _defaults() -> dict:
    settings = get_settings()
    return {
        "enabled": bool(getattr(settings, "web_search_enabled", False)),
        "provider": getattr(settings, "web_search_provider", "auto") or "auto",
        "api_key": getattr(settings, "web_search_api_key", "") or "",
        "max_results": int(getattr(settings, "web_search_max_results", 5) or 5),
        "fetch_pages": int(getattr(settings, "web_search_fetch_pages", 2) or 0),
    }


def _load() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                        prefix=".web-search-", suffix=".tmp", delete=False) as stream:
            name = stream.name
            os.chmod(name, 0o600)
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _bounded(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def configuration() -> dict:
    """Effective configuration with the API key decrypted (never shown in responses)."""
    base = _defaults()
    stored = _load()
    provider = stored.get("provider", base["provider"])
    if provider not in PROVIDERS:
        provider = "auto"
    api_key = base["api_key"]
    if "api_key" in stored:
        try:
            api_key = _decrypt(stored["api_key"]) if stored["api_key"] else ""
        except (ValueError, OSError):
            api_key = ""
    return {
        "enabled": bool(stored.get("enabled", base["enabled"])),
        "provider": provider,
        "api_key": api_key,
        "max_results": _bounded(stored.get("max_results", base["max_results"]), base["max_results"], 1, MAX_RESULTS),
        "fetch_pages": _bounded(stored.get("fetch_pages", base["fetch_pages"]), base["fetch_pages"], 0, MAX_FETCH_PAGES),
    }


def resolved_provider(config: dict | None = None) -> str:
    config = config or configuration()
    if config["provider"] == "auto":
        return "tavily" if config["api_key"] else "bing"
    return config["provider"]


def status() -> dict:
    config = configuration()
    provider = resolved_provider(config)
    return {
        "enabled": config["enabled"],
        "provider": config["provider"],
        "resolved_provider": provider,
        "available": provider not in KEYED_PROVIDERS or bool(config["api_key"]),
        "api_key_set": bool(config["api_key"]),
        "max_results": config["max_results"],
        "fetch_pages": config["fetch_pages"],
        "max_fetch_pages": MAX_FETCH_PAGES,
        "max_results_limit": MAX_RESULTS,
        "providers": [{"id": row, "label": PROVIDER_LABELS[row], "keyed": row in KEYED_PROVIDERS} for row in PROVIDERS],
    }


def update_config(changes: dict) -> dict:
    """Validate and persist administrator changes; the API key is DPAPI-encrypted."""
    stored = _load()
    if "enabled" in changes:
        if not isinstance(changes["enabled"], bool):
            raise ValueError("启用状态必须是布尔值")
        stored["enabled"] = changes["enabled"]
    if "provider" in changes:
        if changes["provider"] not in PROVIDERS:
            raise ValueError("未知的搜索服务")
        stored["provider"] = changes["provider"]
    if "api_key" in changes:
        api_key = changes["api_key"]
        if api_key is None:
            api_key = ""
        if not isinstance(api_key, str) or len(api_key) > 200 or any(ord(char) < 32 for char in api_key):
            raise ValueError("API Key 格式无效")
        stored["api_key"] = _encrypt(api_key.strip()) if api_key.strip() else ""
    for field_name, low, high in (("max_results", 1, MAX_RESULTS), ("fetch_pages", 0, MAX_FETCH_PAGES)):
        if field_name in changes:
            value = changes[field_name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError("数值超出范围")
            stored[field_name] = value
    with _lock:
        _save(stored)
    return status()


# -------------------------------------------------------------------------- fetching


def validate_external_url(url: str) -> tuple[str, str]:
    """Only plain public HTTPS URLs; the caller must connect to the returned address."""
    if not isinstance(url, str) or len(url) > MAX_URL:
        raise WebSearchError("网页地址格式无效", 400)
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise WebSearchError("网页地址格式无效", 400) from exc
    if parsed.scheme != "https" or port not in (None, 443) or parsed.username is not None or parsed.password is not None:
        raise WebSearchError("只能读取公开的 HTTPS 网页", 400)
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebSearchError("无法解析网页地址", 502) from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise WebSearchError("网页地址解析到非公网地址", 400)
    return host, addresses[0][4][0]


def fetch_bytes(url: str, *, max_bytes: int = MAX_PAGE_BYTES,
                accept: str = "text/html,application/xhtml+xml") -> tuple[str, bytes]:
    """Fetch a public URL with the connection pinned to the validated address."""
    host, address = validate_external_url(url)
    parsed = urlparse(url)
    authority = f"[{address}]" if ":" in address else address
    pinned = urlunparse(parsed._replace(netloc=authority))
    headers = {"Host": host, "User-Agent": USER_AGENT, "Accept": accept,
               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"}
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", pinned, headers=headers, extensions={"sni_hostname": host}) as response:
                if 300 <= response.status_code < 400:
                    raise WebSearchError("网页返回了跳转，已停止读取")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=16_384):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise WebSearchError("网页内容超过大小限制", 413)
                return content_type, bytes(data)
    except httpx.HTTPError as exc:
        raise WebSearchError("无法访问该网页") from exc


def _decode(data: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    for encoding in ([match.group(1)] if match else []) + ["utf-8", "gb18030"]:
        try:
            return data.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- parsing


class _TextExtractor(HTMLParser):
    def __init__(self, limit: int):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.limit = limit
        self.length = 0
        self._skip = 0
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS and self.parts:
            self.parts.append("\n")

    def handle_data(self, data):
        text = data.strip()
        if self._in_title and text:
            self.title = (self.title + " " + text).strip()
            return
        if self._skip or not text:
            return
        if self.length < self.limit:
            self.parts.append(text)
            self.length += len(text)

    def text(self) -> str:
        collapsed = re.sub(r"[ \t\r\f\v]+", " ", "".join(
            part if part == "\n" else part + " " for part in self.parts))
        return re.sub(r"\n\s*\n+", "\n", collapsed).strip()


def html_to_text(markup: str, limit: int = MAX_PAGE_TEXT) -> tuple[str, str]:
    parser = _TextExtractor(limit)
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # Malformed markup must never break a search.
        pass
    title = html_module.unescape(re.sub(r"\s+", " ", parser.title)).strip()
    return title, parser.text()[:limit]


MAX_DOCUMENT_BYTES = 2_000_000
MAX_DOCUMENT_TEXT = 500_000


def fetch_document_text(url: str, limit: int = MAX_DOCUMENT_TEXT) -> tuple[str, str]:
    """Fetch one URL and return (title, text) for knowledge-base import.

    Uses the same discipline as page fetching during a search: HTTPS only, the connection is
    pinned to the validated public address with SNI preserved, redirects are refused, and the
    payload has a size cap. HTML is reduced to readable text; anything else is taken verbatim.
    """
    limit = max(1_000, min(limit, MAX_DOCUMENT_TEXT))
    content_type, data = fetch_bytes(url, max_bytes=MAX_DOCUMENT_BYTES)
    raw = _decode(data, content_type)
    if "html" in (content_type or "").lower() or "xhtml" in (content_type or "").lower():
        title, text = html_to_text(raw, limit=limit)
    else:
        title, text = "", raw
    return title, text[:limit]


def _plain(fragment: str) -> str:
    return html_module.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def parse_bing_results(markup: str, limit: int) -> list[dict]:
    results = []
    blocks = re.findall(r'<li class="b_algo".*?(?=<li class="b_algo"|</ol>)', markup, re.S)
    for block in blocks:
        title_match = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not title_match:
            continue
        url = html_module.unescape(title_match.group(1))
        if not url.startswith("https://"):
            continue
        snippet_match = (re.search(r'<p[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>', block, re.S)
                         or re.search(r"<p[^>]*>(.*?)</p>", block, re.S))
        results.append({
            "title": _plain(title_match.group(2))[:200],
            "url": url[:MAX_URL],
            "snippet": _plain(snippet_match.group(1))[:MAX_SNIPPET] if snippet_match else "",
        })
        if len(results) == limit:
            break
    return results


# ------------------------------------------------------------------------- providers


def _bing_search(query: str, limit: int, config: dict) -> list[dict]:
    url = BING_SEARCH_URL + "?" + urlencode({"q": query, "setlang": "zh-CN", "ensearch": "0"})
    content_type, data = fetch_bytes(url, accept="text/html,application/xhtml+xml")
    results = parse_bing_results(_decode(data, content_type), limit)
    if not results:
        raise WebSearchError("搜索服务没有返回可解析的结果，请稍后重试")
    return results


def _post_json(url: str, payload: dict, api_key: str, timeout: float = 12) -> dict:
    validate_external_url(url)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = client.post(url, json=payload, headers={
                "Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT, "Accept": "application/json"})
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise WebSearchError("搜索服务响应超过大小限制", 413)
            data = response.json()
    except httpx.HTTPError as exc:
        raise WebSearchError("搜索服务请求失败，请检查 API Key 与网络") from exc
    except ValueError as exc:
        raise WebSearchError("搜索服务返回了无效内容") from exc
    if not isinstance(data, dict):
        raise WebSearchError("搜索服务返回了无效内容")
    return data


def _tavily_search(query: str, limit: int, config: dict) -> list[dict]:
    data = _post_json(TAVILY_SEARCH_URL, {"query": query, "max_results": limit, "search_depth": "basic"},
                      config["api_key"])
    results = []
    for row in data.get("results", []) if isinstance(data.get("results"), list) else []:
        if not isinstance(row, dict) or not str(row.get("url", "")).startswith("https://"):
            continue
        results.append({"title": str(row.get("title") or row["url"])[:200], "url": str(row["url"])[:MAX_URL],
                        "snippet": _plain(str(row.get("content") or ""))[:MAX_SNIPPET]})
        if len(results) == limit:
            break
    return results


def _bocha_search(query: str, limit: int, config: dict) -> list[dict]:
    data = _post_json(BOCHA_SEARCH_URL, {"query": query, "count": limit, "summary": False}, config["api_key"])
    pages = data.get("data") if isinstance(data.get("data"), dict) else {}
    rows = ((pages.get("webPages") or {}).get("value") if isinstance(pages.get("webPages"), dict) else None) or []
    results = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not str(row.get("url", "")).startswith("https://"):
            continue
        results.append({"title": str(row.get("name") or row["url"])[:200], "url": str(row["url"])[:MAX_URL],
                        "snippet": _plain(str(row.get("snippet") or row.get("summary") or ""))[:MAX_SNIPPET]})
        if len(results) == limit:
            break
    return results


SEARCHERS = {"bing": _bing_search, "tavily": _tavily_search, "bocha": _bocha_search}


def read_page(url: str, limit: int = MAX_PAGE_TEXT) -> dict:
    content_type, data = fetch_bytes(url)
    if not any(token in content_type.lower() for token in ("text/html", "text/plain", "application/xhtml")):
        raise WebSearchError("该地址不是网页内容", 415)
    title, text = html_to_text(_decode(data, content_type), limit)
    return {"title": title or url, "url": url, "text": text}


def search(query: str, limit: int | None = None, config: dict | None = None) -> dict:
    """Run one web search. Raises WebSearchError with a user-facing message."""
    query = (query or "").strip()
    if not query or len(query) > MAX_QUERY:
        raise WebSearchError("搜索词必须为 1 至 200 个字符", 400)
    config = config or configuration()
    if not config["enabled"]:
        raise WebSearchError("联网搜索尚未启用，请在设置中开启", 403)
    provider = resolved_provider(config)
    if provider in KEYED_PROVIDERS and not config["api_key"]:
        raise WebSearchError("所选搜索服务缺少 API Key，请在设置中补充", 400)
    limit = _bounded(limit if limit is not None else config["max_results"], config["max_results"], 1, MAX_RESULTS)
    results = SEARCHERS[provider](query, limit, config)
    if not results:
        raise WebSearchError("没有检索到相关网页")
    return {"provider": provider, "results": results[:limit]}


def live_context(query: str, config: dict | None = None) -> dict:
    """Search and optionally read the top pages for the chat agent; never raises."""
    fetched_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    try:
        payload = search(query, config=config)
    except WebSearchError as exc:
        return {"provider": "", "results": [], "error": str(exc), "fetched_at": fetched_at}
    results = payload["results"]
    for row in results[: (config or configuration())["fetch_pages"]]:
        try:
            page = read_page(row["url"])
        except WebSearchError:
            continue
        row["text"] = page["text"]
        if not row["title"] and page["title"]:
            row["title"] = page["title"]
    return {"provider": payload["provider"], "results": results, "error": "", "fetched_at": fetched_at}
