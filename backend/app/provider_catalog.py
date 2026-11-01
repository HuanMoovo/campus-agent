"""Public provider registry; no credentials or network activity."""
from typing import Literal


CLOUD_PROTOCOLS = ("chat_completions", "responses", "anthropic", "gemini")


def _row(id, label, base_url, docs_url, note="", protocol="chat_completions", region="china", auth_header="Authorization", **options):
    return {"id": id, "label": label, "base_url": base_url, "protocol": protocol,
            "region": region, "docs_url": docs_url, "note": note, "auth_header": auth_header, "request_options": options}


CATALOG = (
    _row("qwen", "阿里百炼 · Qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1",
         "https://help.aliyun.com/en/model-studio/base-url",
         "密钥与地域、工作空间及套餐绑定；请按账号控制台调整基础地址。"),
    _row("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "https://api-docs.deepseek.com/",
         "填写当前账号可用的模型 ID；旧模型别名可能已下线。"),
    _row("zhipu", "智谱 · GLM（国内）", "https://open.bigmodel.cn/api/paas/v4",
         "https://docs.bigmodel.cn/cn/api/introduction",
         "标准 API 与 Coding 套餐的地址及密钥用途不同，请按套餐修改。"),
    _row("moonshot", "月之暗面 · Kimi", "https://api.moonshot.cn/v1", "https://platform.kimi.com/docs/api/chat",
         "使用对应平台的模型 ID；推理模型的 temperature/工具支持以模型说明为准。"),
    _row("doubao", "火山方舟 · 豆包", "https://ark.cn-beijing.volces.com/api/v3",
         "https://docs.volcengine.com/docs/ark/chat-api",
         "填写已开通的模型 ID 或推理接入点 ID，核对服务地域。"),
    _row("siliconflow", "硅基流动", "https://api.siliconflow.cn/v1",
         "https://docs.siliconflow.cn/docs/api/chat-completions-post",
         "模型名通常含组织/模型路径；国内与国际平台的密钥及地址不同。"),
    _row("hunyuan", "腾讯混元", "https://api.hunyuan.cloud.tencent.com/v1",
         "https://cloud.tencent.com/document/product/1729/111007",
         "此为旧混元 OpenAI 兼容入口；平台正迁移至 TokenHub，请按账号当前文档调整地址与模型。"),
    _row("qianfan", "百度千帆", "https://qianfan.baidubce.com/v2",
         "https://cloud.baidu.com/doc/qianfan-api/s/3m7of64lb",
         "使用 V2 API Key；不适用旧版 access_token/OAuth 调用地址。"),
    _row("minimax", "MiniMax", "https://api.minimax.cn/v1",
         "https://platform.minimax.cn/docs/api-reference/text-chat-openai",
         "使用当前平台模型 ID；部分模型强制思考，温度固定或忽略。",
         token_parameter="max_completion_tokens", send_temperature=False),
    _row("stepfun", "阶跃星辰", "https://api.stepfun.com/v1", "https://platform.stepfun.ai/cookbook/step-5-tool-calling",
         "国内与国际接入地址/密钥分别管理，按账号修改地址。"),
    _row("spark", "讯飞星火", "https://spark-api-open.xf-yun.com/v1", "https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html",
         "此处密钥栏填写 HTTP APIPassword；不同模型可能使用独立 /agent/v1 地址，先诊断流式能力。"),
    _row("yi", "零一万物 · Yi", "https://api.lingyiwanwu.com/v1", "https://platform.lingyiwanwu.com/docs",
         "填写平台当前可用的模型 ID 并分别诊断所需能力。"),
    _row("openai_responses", "OpenAI · Responses", "https://api.openai.com/v1",
         "https://developers.openai.com/api/docs/guides/migrate-to-responses",
         "Responses 原生接口；按模型要求设置输出上限与推理参数。", protocol="responses", region="global", send_temperature=False),
    _row("anthropic", "Anthropic · Claude", "https://api.anthropic.com/v1",
         "https://platform.claude.com/docs/en/api/messages", "Messages 原生接口；填写实际可用模型 ID。", protocol="anthropic", region="global", auth_header="x-api-key"),
    _row("gemini", "Google · Gemini", "https://generativelanguage.googleapis.com/v1beta",
         "https://ai.google.dev/api/generate-content", "Gemini Developer API Key；Vertex AI/IAM 接口需独立适配。", protocol="gemini", region="global", auth_header="x-goog-api-key"),
    _row("xiaomi", "小米 · MiMo", "https://api.xiaomimimo.com/v1", "https://mimo.mi.com/docs/en-US/api/chat/openai-api", "实时按量 API；使用对应密钥与当前模型 ID。Token Plan/批量接口另有专用地址与密钥。思考开启时温度固定，工具历史需保留 reasoning_content。",
         protocol="chat_completions", region="china", auth_header="api-key", token_parameter="max_completion_tokens", send_temperature=False),
    _row("zai", "Z.AI · GLM（国际）", "https://api.z.ai/api/paas/v4", "https://docs.z.ai/api-reference/llm/chat-completion", "国际标准 API，使用 Standard API Key；与国内智谱及 Coding Plan 地址/密钥分开。思考能力与 reasoning_effort 按具体模型配置。",
         protocol="chat_completions", region="global", auth_header="Authorization", token_parameter="max_tokens"),
    _row("xai", "xAI · Grok", "https://api.x.ai/v1", "https://docs.x.ai/developers/model-capabilities/legacy/chat-completions", "Chat Completions 为仍可用的旧接口；新功能优先 Responses。填写账号可用模型 ID，并按推理耗时调整超时。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "https://openrouter.ai/docs/quickstart", "使用 OpenRouter 模型 slug；HTTP-Referer 与应用标题头为可选。模型能力及供应商路由以账号配置为准。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("groq", "Groq", "https://api.groq.com/openai/v1", "https://console.groq.com/docs/openai", "使用 Groq 账号可用模型；输出上限使用 max_completion_tokens。部分 OpenAI 参数不受支持。",
         protocol="chat_completions", region="global", auth_header="Authorization", token_parameter="max_completion_tokens"),
    _row("mistral", "Mistral AI", "https://api.mistral.ai/v1", "https://docs.mistral.ai/api", "使用 Mistral Studio API Key 与当前可用模型 ID；工具及结构化输出需按模型诊断。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("together", "Together AI", "https://api.together.ai/v1", "https://docs.together.ai/docs/inference/openai-compatibility", "使用 Together API Key；模型 ID 通常为组织/模型路径。专用部署和地域地址按账号文档调整。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1", "https://docs.fireworks.ai/tools-sdks/openai-compatibility", "使用 Fireworks 模型或部署 ID，常见格式为 accounts/账号/models/模型；按模型诊断工具与流式能力。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai", "https://docs.deepinfra.com/chat/overview", "使用 DeepInfra Token 与目录中的完整模型 ID；此地址为 OpenAI 兼容聊天接口。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("cerebras", "Cerebras", "https://api.cerebras.ai/v1", "https://inference-docs.cerebras.ai/resources/openai", "共享推理填写精确模型 ID，专用推理填写账号分配的 endpoint ID；各模型能力分别诊断。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("huggingface", "Hugging Face · Inference Providers", "https://router.huggingface.co/v1", "https://huggingface.co/docs/inference-providers/tasks/chat-completion", "填写具有 Inference Providers 权限的 HF Token 和支持聊天的模型 ID；可按官方规则添加 :供应商 或路由后缀。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("cohere", "Cohere · OpenAI 兼容", "https://api.cohere.ai/compatibility/v1", "https://docs.cohere.com/docs/compatibility-api", "此为 Cohere 专用 OpenAI 兼容入口，不是原生 /v2/chat；部分 OpenAI 参数不支持，推理强度仅支持 none/high。",
         protocol="chat_completions", region="global", auth_header="Authorization"),
    _row("openai_compatible", "自定义模型服务", "https://api.openai.com/v1",
         "https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create",
         "按服务商实际协议选择 Chat Completions、Responses、Messages 或 Gemini；配置预设不代表所有能力已验证。", region="custom"),
)

PROVIDERS = {row["id"]: row for row in CATALOG}
CLOUD_PROVIDER_IDS = tuple(PROVIDERS)
ModelPreference = Literal[tuple(("auto", "ollama") + CLOUD_PROVIDER_IDS)]


def provider_defaults(provider):
    row = PROVIDERS[provider]
    return {"api_key": "", "base_url": row["base_url"], "model": "", "protocol": row["protocol"],
            "request_options": dict(row["request_options"])}


def public_catalog():
    return [{**row, "request_options": dict(row["request_options"])} for row in CATALOG]
