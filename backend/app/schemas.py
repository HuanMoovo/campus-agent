import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def validate_parameter_schema(schema: dict) -> dict:
    """Accept a bounded JSON Schema subset that can be represented by GET parameters."""
    if not isinstance(schema, dict) or set(schema) - {"type", "properties", "required", "additionalProperties", "description"}:
        raise ValueError("插件参数只支持简单对象 JSON Schema")
    if schema.get("type", "object") != "object" or schema.get("additionalProperties", False) is not False:
        raise ValueError("插件参数必须为禁止额外属性的对象")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or len(properties) > 40:
        raise ValueError("插件最多支持 40 个参数")
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required) or len(set(required)) != len(required) or set(required) - set(properties):
        raise ValueError("required 必须引用已定义的参数且不能重复")
    for name, spec in properties.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", name) or not isinstance(spec, dict):
            raise ValueError("插件参数定义无效")
        if set(spec) - {"type", "description", "enum", "minimum", "maximum", "minLength", "maxLength"}:
            raise ValueError("插件参数包含不支持的约束")
        kind = spec.get("type")
        if not isinstance(kind, str) or kind not in {"string", "integer", "number", "boolean"}:
            raise ValueError("插件仅支持字符串、数字和布尔参数")
        if "description" in spec and (not isinstance(spec["description"], str) or len(spec["description"]) > 500):
            raise ValueError("参数描述无效")
        if "enum" in spec:
            values = spec["enum"]
            if not isinstance(values, list) or not 1 <= len(values) <= 100 or any(not parameter_type_matches(value, kind) for value in values):
                raise ValueError("参数枚举必须匹配声明类型")
        for bound in ("minimum", "maximum"):
            if bound in spec and (kind not in {"integer", "number"} or not parameter_type_matches(spec[bound], "number")):
                raise ValueError("数字边界必须为有限数字")
        for bound in ("minLength", "maxLength"):
            if bound in spec and (kind != "string" or type(spec[bound]) is not int or not 0 <= spec[bound] <= 4000):
                raise ValueError("字符串长度边界无效")
        if spec.get("minimum", float("-inf")) > spec.get("maximum", float("inf")) or spec.get("minLength", 0) > spec.get("maxLength", 4000):
            raise ValueError("参数上下界冲突")
    return {**schema, "type": "object", "properties": properties, "required": required, "additionalProperties": False}


def parameter_type_matches(value, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str) and len(value) <= 4000
    if kind == "boolean":
        return type(value) is bool
    if kind == "integer":
        return type(value) is int and abs(value) <= 2**53 - 1
    return type(value) in (int, float) and abs(value) <= 1e308 and math.isfinite(value)


class RequestModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ChatRequest(RequestModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    client_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")
    model: Literal["auto", "qwen", "deepseek", "ollama"] | None = None
    web: bool = False
    local_model: str | None = Field(default=None, min_length=1, max_length=128,
                                    pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")

    @model_validator(mode="after")
    def local_model_requires_ollama(self):
        if self.local_model is not None and self.model != "ollama":
            raise ValueError("指定本地模型时，model 必须为 ollama")
        return self


class Source(BaseModel):
    title: str
    snippet: str = ""
    url: str = ""
    kind: str = ""


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: list[Source] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    mode: str = "demo"
    web: dict = Field(default_factory=dict)


class DocumentCreate(RequestModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=500_000)


class DocumentUpdate(DocumentCreate):
    pass


class ImportUrlRequest(RequestModel):
    """Import one public web page into the knowledge base."""

    url: str = Field(min_length=8, max_length=2048)

    @field_validator("url")
    @classmethod
    def require_https(cls, value: str) -> str:
        if not value.lower().startswith("https://"):
            raise ValueError("网页地址必须是 https:// 开头")
        return value


class PluginCreate(RequestModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    description: str = Field(min_length=1, max_length=500)
    url: HttpUrl = Field(max_length=500)
    parameters: dict = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("parameters")
    @classmethod
    def valid_parameters(cls, value: dict) -> dict:
        return validate_parameter_schema(value)


class PluginUpdate(RequestModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    enabled: bool | None = None

    @field_validator("description", "enabled")
    @classmethod
    def disallow_explicit_null(cls, value):
        if value is None:
            raise ValueError("字段不可为 null；不修改的字段请省略")
        return value


class McpServerCreate(RequestModel):
    """登记一个 MCP 服务器；env 里可放令牌，接口只回掩码不回显。"""

    name: str = Field(min_length=1, max_length=40)
    command: str = Field(min_length=1, max_length=300)
    args: list[str] = Field(default_factory=list, max_length=30)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class McpServerUpdate(RequestModel):
    name: str | None = Field(default=None, max_length=40)
    command: str | None = Field(default=None, max_length=300)
    args: list[str] | None = Field(default=None, max_length=30)
    env: dict[str, str] | None = None
    enabled: bool | None = None


class RepairCreate(RequestModel):
    location: str = Field(min_length=2, max_length=120)
    issue: str = Field(min_length=5, max_length=2000)
    contact: str = Field(min_length=2, max_length=120)


class SettingsUpdate(RequestModel):
    model: Literal["auto", "qwen", "deepseek", "ollama"]


class WebSearchConfigUpdate(RequestModel):
    enabled: bool | None = None
    provider: Literal["auto", "bing", "tavily", "bocha"] | None = None
    api_key: str | None = Field(default=None, max_length=200)
    max_results: int | None = Field(default=None, ge=1, le=8)
    fetch_pages: int | None = Field(default=None, ge=0, le=3)


class ModelProviderUpdate(RequestModel):
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    clear_api_key: bool = False
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=128)


class LocalModelPull(RequestModel):
    model: Literal["qwen3:0.6b", "qwen3:1.7b", "deepseek-r1:1.5b"]
    source: Literal["ollama", "huggingface", "hf-mirror"] = "ollama"
