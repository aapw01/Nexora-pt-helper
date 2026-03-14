"""
配置加载模块
支持 YAML 配置文件和环境变量覆盖
"""

import os
from typing import Any, ClassVar

import yaml


class Config:
    """配置管理类"""

    # 配置文件搜索路径
    CONFIG_PATHS: ClassVar[list[str]] = [
        "/app/config/config.yaml",  # Docker 容器内
        "config.yaml",  # 当前目录
    ]

    def __init__(self, config_data: dict[str, Any]):
        self._data = config_data
        self._apply_env_overrides()
        self._validate()

    def _apply_env_overrides(self):
        """应用环境变量覆盖"""
        # Telegram 配置
        if os.getenv("TELEGRAM_TOKEN"):
            self._data.setdefault("telegram", {})["token"] = os.getenv("TELEGRAM_TOKEN")
        if os.getenv("TELEGRAM_CHAT_ID"):
            self._data.setdefault("telegram", {})["chat_id"] = os.getenv("TELEGRAM_CHAT_ID")

        # M-Team 配置
        if os.getenv("MTEAM_API_KEY"):
            self._data.setdefault("mteam", {})["api_key"] = os.getenv("MTEAM_API_KEY")
        if os.getenv("MTEAM_DOMAIN"):
            self._data.setdefault("mteam", {})["domain"] = os.getenv("MTEAM_DOMAIN")

        # qBittorrent 配置
        if os.getenv("QBIT_HOST"):
            self._data.setdefault("qbittorrent", {})["host"] = os.getenv("QBIT_HOST")
        if os.getenv("QBIT_PORT"):
            self._data.setdefault("qbittorrent", {})["port"] = int(os.getenv("QBIT_PORT"))
        if os.getenv("QBIT_USERNAME"):
            self._data.setdefault("qbittorrent", {})["username"] = os.getenv("QBIT_USERNAME")
        if os.getenv("QBIT_PASSWORD"):
            self._data.setdefault("qbittorrent", {})["password"] = os.getenv("QBIT_PASSWORD")

    def _validate(self):
        """验证必要配置项"""
        errors = []

        if not self.telegram.get("token"):
            errors.append("缺少 telegram.token 配置")
        if not self.mteam.get("api_key"):
            errors.append("缺少 mteam.api_key 配置")
        if not self.qbittorrent.get("host"):
            errors.append("缺少 qbittorrent.host 配置")

        if errors:
            raise ValueError("配置验证失败:\n" + "\n".join(f"  - {e}" for e in errors))

    @property
    def telegram(self) -> dict[str, Any]:
        """Telegram 配置"""
        return self._data.get("telegram", {})

    @property
    def mteam(self) -> dict[str, Any]:
        """M-Team 配置"""
        return self._data.get("mteam", {})

    @property
    def qbittorrent(self) -> dict[str, Any]:
        """qBittorrent 配置"""
        return self._data.get("qbittorrent", {})

    @property
    def download(self) -> dict[str, Any]:
        """下载配置"""
        return self._data.get("download", {})

    @property
    def organize(self) -> dict[str, Any]:
        """整理/刮削配置"""
        return self._data.get("organize", {})

    @property
    def subscription(self) -> dict[str, Any]:
        """订阅配置"""
        return self._data.get("subscription", {})

    @property
    def api(self) -> dict[str, Any]:
        """Web API 配置"""
        return self._data.get("api", {})

    @property
    def file_manager(self) -> dict[str, Any]:
        """文件管理器配置"""
        return self._data.get("file_manager", {})

    @property
    def raw(self) -> dict[str, Any]:
        """原始配置数据"""
        return self._data

    @property
    def mteam_categories(self) -> dict[str, dict[str, Any]]:
        """M-Team 类别配置"""
        return self.mteam.get("categories", {})

    @property
    def telegram_admins(self) -> list[str]:
        """Telegram 管理员列表"""
        admins = self.telegram.get("admins", [])
        return [str(a) for a in admins] if admins else []

    @property
    def telegram_chat_id(self) -> str | None:
        """允许的 Telegram Chat ID"""
        chat_id = self.telegram.get("chat_id")
        return str(chat_id) if chat_id else None

    @classmethod
    def load(cls, config_file: str | None = None) -> "Config":
        """
        加载配置文件

        :param config_file: 指定配置文件路径，None 则自动搜索
        :return: Config 实例
        """
        config_path = None

        if config_file:
            if os.path.exists(config_file):
                config_path = config_file
            else:
                raise FileNotFoundError(f"指定的配置文件不存在: {config_file}")
        else:
            for path in cls.CONFIG_PATHS:
                if os.path.exists(path):
                    config_path = path
                    break

        if not config_path:
            # 无配置文件时使用空配置（依赖环境变量）
            print("⚠️ 未找到配置文件，使用环境变量配置")
            config_data = {}
        else:
            print(f"📄 加载配置文件: {config_path}")
            with open(config_path, encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}

        return cls(config_data)


# 全局配置实例（延迟初始化）
_config: Config | None = None


def get_config() -> Config:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config(config_file: str | None = None) -> Config:
    """重新加载配置"""
    global _config
    _config = Config.load(config_file)
    return _config
