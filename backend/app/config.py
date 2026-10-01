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
        overrides["data_dir"] = Path(data_dir).resolve()
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
