from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "小苏 AI 助手"
    database_url: str = "sqlite:///./xiaosu.db"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    upload_dir: str = "./uploads"
    log_dir: str = "../logs"
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""
    dingtalk_enabled: bool = False
    dingtalk_bot_name: str = "小苏"
    retrieval_threshold: float = 0.22
    max_history_messages: int = 12


settings = Settings()
