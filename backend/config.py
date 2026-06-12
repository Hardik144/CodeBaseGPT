from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM provider: "gemini" (free), "groq" (free), or "openai" (paid)
    llm_provider: str = "groq"

    gemini_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""

    github_token: str = ""
    chroma_path: str = "./chroma_db"
    allowed_origins: str = "http://localhost:3001"
    chat_model: str = "gpt-4o"   # only used when llm_provider=openai


@lru_cache()
def get_settings() -> Settings:
    return Settings()
# refactor: split config into backend and shared settings
# refactor: split config into backend and shared settings
# refactor: split config into backend and shared settings
# refactor: split config into backend and shared settings
