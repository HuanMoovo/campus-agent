from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .desktop_runtime import DesktopRuntime, desktop_enabled


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'campus.db').as_posix()}"
    data_dir: Path = BASE_DIR / "data"
    qwen_api_key: str = ""
    deepseek_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qwen_model: str = "qwen3-235b-a22b"
    deepseek_model: str = "deepseek-chat"
    enable_rag: bool = False
    bge_model_name: str = "BAAI/bge-m3"
    admin_token: str = ""
    plugin_allowed_hosts: str = ""
    cors_origins: str = "http://localhost:5173"
    update_manifest_url: str = ""
    web_search_enabled: bool = False
    web_search_provider: str = "auto"
    web_search_api_key: str = ""
    web_search_max_results: int = 5
    web_search_fetch_pages: int = 2
    # 网站部署的登录开关；桌面包保持 false（沿用外壳注入的令牌）
    auth_required: bool = False
    auth_admin_username: str = "admin"
    auth_admin_password: str = ""      # 首次启动创建该账号；留空则生成随机口令并打印一次
    session_days: int = 14
    cookie_secure: bool = False        # https 部署置 true
    # 自助注册：默认关闭；开启后任何人可注册普通账号；填了注册码就必须带对注册码
    allow_registration: bool = False
    register_code: str = ""

    @property
    def allowed_plugin_hosts(self) -> set[str]:
        return {host.strip().lower() for host in self.plugin_allowed_hosts.split(",") if host.strip()}


@lru_cache
def get_settings() -> Settings:
    config_file = os.environ.get("CAMPUS_CONFIG_FILE")
    data_dir = os.environ.get("CAMPUS_DATA_DIR")
    overrides = {}
    if config_file and not Path(config_file).is_absolute():
        raise ValueError("CAMPUS_CONFIG_FILE must be an absolute path")
    if data_dir:
        if not Path(data_dir).is_absolute():
            raise ValueError("CAMPUS_DATA_DIR must be an absolute path")
        resolved = Path(data_dir).resolve()
        overrides["data_dir"] = resolved
        # 指定数据目录时数据库也应落在同一目录，否则测试与多实例会共用同一个库。
        # 显式配置 DATABASE_URL（例如 Postgres）时以它为准。
        if not os.environ.get("DATABASE_URL"):
            overrides["database_url"] = f"sqlite:///{(resolved / 'campus.db').as_posix()}"
    if desktop_enabled():
        runtime = DesktopRuntime.from_environment()
        overrides.update(
            data_dir=runtime.data_dir,
            database_url=f"sqlite:///{(runtime.data_dir / 'campus.db').as_posix()}",
            admin_token=runtime.token,
            cors_origins="",
        )
        config_file = runtime.config_file
    return Settings(_env_file=config_file or BASE_DIR / ".env", **overrides)
