from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fatsecret_consumer_key: str = ""
    fatsecret_consumer_secret: str = ""
    usda_api_key: str = ""
    foodlog_db_path: str = "/data/foodlog.db"
    foodlog_host: str = "127.0.0.1"
    foodlog_port: int = 8042

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.foodlog_db_path}"

    @property
    def fatsecret_configured(self) -> bool:
        return bool(self.fatsecret_consumer_key and self.fatsecret_consumer_secret)

    @property
    def usda_configured(self) -> bool:
        return bool(self.usda_api_key)


settings = Settings()
