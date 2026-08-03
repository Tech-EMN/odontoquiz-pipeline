"""
OdontoQuiz Pipeline — Configuração central
Todas as variáveis de ambiente e secrets são carregadas aqui.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # -- App --
    app_name: str = "OdontoQuiz Pipeline"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # -- Supabase --
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_anon_key: str = ""
    supabase_storage_bucket: str = "materiais"

    # -- OpenAI --
    openai_api_key: str = ""
    openai_org_id: str = ""
    openai_model: str = "gpt-4o"

    # -- OdontoQuiz API --
    odontoquiz_api_base_url: str = "https://www.odontoquiz.com.br/api/v1/quiz-ai"
    odontoquiz_api_key: str = ""

    # -- Webhook Token (for MCP auth) --
    webhook_token: str = ""

    # -- Processing --
    max_concurrent_tasks: int = 5
    ocr_timeout_seconds: int = 120
    image_max_size_mb: int = 20

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",  # Ignora vars extras no .env/ambiente (evita crash no startup)
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
