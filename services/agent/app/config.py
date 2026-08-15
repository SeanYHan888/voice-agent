from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://maya:maya_dev_pw@localhost:5432/voiceagent"
    domain_service_url: str = "http://domain:8000"
    jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"

    openai_api_key: str = ""
    elevenlabs_llm_api_key: str = ""
    # Voice turns need first-token latency under a second; analysis can afford to think.
    voice_model: str = "gpt-5.6-luna"
    analysis_model: str = "gpt-5.6-terra"
    # gpt-5.6 rejects any other effort alongside function tools on /v1/chat/completions,
    # and "none" is the latency floor regardless.
    voice_reasoning_effort: str = "none"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://us.cloud.langfuse.com"

    clinic_name: str = "Assort Dermatology"
    agent_name: str = "Maya"


settings = Settings()
