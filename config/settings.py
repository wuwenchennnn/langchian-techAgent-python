from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
APP_ENV = os.getenv("APP_ENV", "dev").lower()
ENV_FILE_MAP = {
    "dev": BASE_DIR / ".env.dev",
    "prod": BASE_DIR / ".env.prod",
}
DEFAULT_ENV_FILE = ENV_FILE_MAP.get(APP_ENV, BASE_DIR / ".env.dev")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = APP_ENV

    # 智谱 / 模型配置
    zhipu_api_key: Optional[str] = None
    zhipu_api_key_enc: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_api_key_enc: Optional[str] = None
    openai_base_url: str = "https://api.deepseek.com"
    openai_model_name: str = "deepseek-v4-flash"

    # Embedding 配置（默认使用智谱 AI）
    embedding_api_key: Optional[str] = None
    embedding_api_key_enc: Optional[str] = None
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    embedding_model_name: str = "embedding-3"
    rag_top_k: int = 4
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 100

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_database: int = 2
    redis_password: Optional[str] = None
    redis_password_enc: Optional[str] = None
    redis_dimension: int = 1024

    # 数据库配置
    database_url: str = "mysql+pymysql://root:password@localhost:3307/volunteer?charset=utf8mb4"
    database_username: str = "root"
    database_password: Optional[str] = None
    database_password_enc: Optional[str] = None

    # LangSmith 可观测性配置
    langsmith_api_key: Optional[str] = None
    langsmith_tracing_v2: bool = True
    langsmith_project: str = "langchain4j-techAgent-python"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @model_validator(mode="after")
    def load_encrypted_secrets(self) -> "Settings":
        if self.app_env != "prod":
            return self

        secret_key = os.getenv("APP_CONFIG_SECRET")
        if not secret_key:
            raise ValueError("APP_CONFIG_SECRET is required when APP_ENV=prod")

        for plain_attr, enc_attr in (
            ("zhipu_api_key", "zhipu_api_key_enc"),
            ("openai_api_key", "openai_api_key_enc"),
            ("embedding_api_key", "embedding_api_key_enc"),
            ("redis_password", "redis_password_enc"),
            ("database_password", "database_password_enc"),
        ):
            plain_value = getattr(self, plain_attr)
            enc_value = getattr(self, enc_attr)
            if plain_value:
                continue
            if enc_value:
                setattr(self, plain_attr, self._decrypt_value(enc_value, secret_key))

        return self

    @model_validator(mode="after")
    def normalize_embedding_config(self) -> "Settings":
        # 处理 .env 中空值覆盖默认值
        if not self.embedding_base_url:
            self.embedding_base_url = "https://open.bigmodel.cn/api/paas/v4"
        # API key 优先级：embedding_api_key > zhipu_api_key > openai_api_key
        if not self.embedding_api_key:
            self.embedding_api_key = self.zhipu_api_key or self.openai_api_key
        return self

    @staticmethod
    def _decrypt_value(cipher_text: str, secret_key: str) -> str:
        cipher_bytes = base64.b64decode(cipher_text)
        key_bytes = secret_key.encode("utf-8")
        plain_bytes = bytes(
            byte ^ key_bytes[index % len(key_bytes)]
            for index, byte in enumerate(cipher_bytes)
        )
        return plain_bytes.decode("utf-8")


settings = Settings()