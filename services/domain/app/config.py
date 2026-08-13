from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://maya:maya_dev_pw@localhost:5432/voiceagent"
    jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    openai_api_key: str = ""


settings = Settings()
