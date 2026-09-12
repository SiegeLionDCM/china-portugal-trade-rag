from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    siliconflow_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None

    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    rerank_model: str = "Qwen/Qwen3-Reranker-4B"
    embedding_dimension: int = 4096

    deepseek_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_max_tokens: int = Field(1600, ge=256, le=8192)

    qdrant_path: Path = Path("data/index/qdrant")
    sqlite_path: Path = Path("data/metadata.db")
    raw_data_dir: Path = Path("data/raw")
    manifest_dir: Path = Path("data/manifests")
    collection_name: str = "trade_compliance"

    dense_top_k: int = Field(12, ge=1, le=100)
    lexical_top_k: int = Field(12, ge=1, le=100)
    rerank_top_k: int = Field(5, ge=1, le=20)
    min_rerank_score: float = Field(0.20, ge=0, le=1)
    request_timeout_seconds: float = Field(45, gt=0, le=180)
    log_level: str = "INFO"
    debug_context: bool = False

    @field_validator("siliconflow_base_url", "deepseek_base_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.rstrip("/")

    def ensure_directories(self) -> None:
        for path in (self.qdrant_path, self.sqlite_path.parent, self.raw_data_dir, self.manifest_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
