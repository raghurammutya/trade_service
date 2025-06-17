# trade_service/app/core/config.py
import os

class Settings:
    def __init__(self):
        self.trade_api_url: str = os.getenv("TRADE_API_URL", "http://localhost:8000")
        self.stocksdeveloper_api_key: str = os.getenv("STOCKSDEVELOPER_API_KEY", "dfca9ea1-2726-4821-b35a-72d4ca28c589")
        self.host: str = "0.0.0.0"
        self.port: int = 8000
        self.user_service_url: str = os.getenv("USER_SERVICE_URL", "http://localhost:8001")
        
        # RabbitMQ settings
        self.RABBITMQ_HOST: str = os.getenv("RABBITMQ_HOST", "rabbitmq")
        self.RABBITMQ_PORT: int = int(os.getenv("RABBITMQ_PORT", "5672"))
        self.RABBITMQ_USER: str = os.getenv("RABBITMQ_USER", "guest")
        self.RABBITMQ_PASSWORD: str = os.getenv("RABBITMQ_PASSWORD", "guest")
        self.RABBITMQ_URL: str = f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/"
        
        self.mongodb_url: str = os.getenv("MONGODB_URI", "mongodb://mongo:27017")
        self.timescaledb_url: str = os.getenv("TIMESCALEDB_URL", "postgresql://tradmin:tradpass@timescaledb:5432/tradingdb")
        self.redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379")
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
        # Rate limiting
        self.user_rate_limit_5s: int = int(os.getenv("USER_RATE_LIMIT_5S", "500"))
        self.user_rate_limit_1m: int = int(os.getenv("USER_RATE_LIMIT_1M", "1500"))
        self.account_rate_limit_5s: int = int(os.getenv("ACCOUNT_RATE_LIMIT_5S", "60"))
        self.account_rate_limit_1m: int = int(os.getenv("ACCOUNT_RATE_LIMIT_1M", "130"))
        self.account_rate_limit_5m: int = int(os.getenv("ACCOUNT_RATE_LIMIT_5M", "300"))
        
        # Feature flags
        self.mock_order_execution: bool = os.getenv("MOCK_ORDER_EXECUTION", "true").lower() == "true"
        self.mock_user_service: bool = os.getenv("MOCK_USER_SERVICE", "true").lower() == "true"
        self.testing: bool = os.getenv("TESTING", "false").lower() == "true"
    
    @classmethod
    def from_config(cls):
        return cls()

settings = Settings()
