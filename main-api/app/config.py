from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_name: str = "main-api"

    postgres_user: str = "cloud"
    postgres_password: str = "cloud"
    postgres_db: str = "private_cloud"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    rabbitmq_user: str = "cloud"
    rabbitmq_password: str = "cloud"
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672

    host_node: str = "localhost"
    total_cpu: int = 32
    total_memory_mib: int = 131072
    total_disk_gib: int = 2000
    total_instances: int = 1000

    vm_command_timeout_seconds: int = 120
    task_stale_queued_timeout_seconds: int = 180
    task_stale_sweep_interval_seconds: int = 15
    outbox_notify_channel: str = "command_outbox_wakeup"
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 100
    outbox_lock_timeout_seconds: int = 30
    outbox_max_attempts: int = 20
    outbox_retry_max_seconds: int = 60
    outbox_relay_enabled: bool = True
    base_image_url: str = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
    vm_image_catalog_json: str = ""
    vm_image_default_id: str = ""
    vm_image_allow_insecure_no_checksum: bool = False
    console_ticket_ttl_seconds: int = 300
    console_proxy_host: str = "host.docker.internal"
    console_vnc_port_base: int = 20000
    console_vnc_port_span: int = 40000

    auth_jwt_secret: str = "dev-change-me"
    auth_jwt_algorithm: str = "HS256"
    auth_access_token_expire_minutes: int = 60
    auth_refresh_token_expire_days: int = 14
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin1234"
    bootstrap_admin_role: Literal["admin", "operator", "viewer"] = "admin"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_listener_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def rabbitmq_dsn(self) -> str:
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
