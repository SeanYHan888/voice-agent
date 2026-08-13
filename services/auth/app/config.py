from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://maya:maya_dev_pw@localhost:5432/voiceagent"
    jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 720
    admin_email: str = "admin@assortderm.com"
    admin_password: str = "admin-dev-password"


settings = Settings()
