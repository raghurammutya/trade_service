# trade_service/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    user_service_url: str
    rabbitmq_host: str
    rabbitmq_port: int
    mongodb_url: str
    timescaledb_url: str
    redis_url: str
    telegram_bot_token: str = None
    stocksdeveloper_api_key: str = None  # Add this missing field
    user_rate_limit_5s: int = 500
    user_rate_limit_1m: int = 1500
    account_rate_limit_5s: int = 60
    account_rate_limit_1m: int = 130
    account_rate_limit_5m: int = 300
    mock_order_execution: bool = False

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
