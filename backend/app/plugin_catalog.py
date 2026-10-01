"""Bundled, optional public-data connectors. No remote code is installed."""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Plugin
from .schemas import PluginCreate


BAIKE_SEARCH_URL = "https://baike.baidu.com/search/word"
LEGACY_BAIKE_API_URL = "https://baike.baidu.com/api/openapi/BaikeLemmaCardApi?appid=379020"


CATALOG = (
    {
        "id": "openalex",
        "name": "openalex_search",
        "title": "OpenAlex 学术检索",
        "description": "检索开放学术论文与作者元数据（OpenAlex 开源项目）。",
        "url": "https://api.openalex.org/works",
        "parameters": {"type": "object", "properties": {"search": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["search"], "additionalProperties": False},
    },
    {
        "id": "crossref",
        "name": "crossref_search",
        "title": "Crossref 文献查询",
        "description": "按关键词查询 DOI 和出版信息（Crossref REST API）。",
        "url": "https://api.crossref.org/works",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["query"], "additionalProperties": False},
    },
    {
        "id": "baidu_baike",
        "name": "baidu_baike_search",
        "title": "百度百科词条查询",
        "description": "用系统浏览器打开百度百科词条搜索。",
        "url": BAIKE_SEARCH_URL,
        "parameters": {"type": "object", "properties": {"bk_key": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["bk_key"], "additionalProperties": False},
    },
)
CATALOG_HOSTS = frozenset({"api.openalex.org", "api.crossref.org"})


def catalog_list(db: Session) -> list[dict]:
    installed = {row.name: row for row in db.scalars(select(Plugin)).all()}
    return [{"id": row["id"], "name": row["title"], "description": row["description"],
             "installed": row["name"] in installed,
             "enabled": installed[row["name"]].enabled if row["name"] in installed else False}
            for row in CATALOG]


def install_curated_plugin(db: Session, plugin_id: str) -> Plugin:
    from sqlalchemy.exc import IntegrityError

    manifest = next((row for row in CATALOG if row["id"] == plugin_id), None)
    if manifest is None:
        raise HTTPException(404, "推荐插件不存在")
    if db.scalar(select(Plugin).where(Plugin.name == manifest["name"])):
        raise HTTPException(409, "插件已安装")
    validated = PluginCreate.model_validate({
        "name": manifest["name"], "description": manifest["description"],
        "url": manifest["url"], "parameters": manifest["parameters"], "enabled": True,
    })
    plugin = Plugin(id=str(uuid4()), **{**validated.model_dump(), "url": str(validated.url)})
    db.add(plugin)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "插件已安装") from exc
    return plugin
