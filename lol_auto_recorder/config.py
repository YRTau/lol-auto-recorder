"""配置文件读写"""

from pathlib import Path
import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    """读取 config.yaml"""
    if not CONFIG_PATH.exists():
        return get_default_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict) -> None:
    """写入 config.yaml"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


def get_default_config() -> dict:
    """默认配置"""
    return {
        "obs": {"host": "localhost", "port": 4455, "password": ""},
        "monitor": {
            "process_name": "League of Legends.exe",
            "poll_interval": 3,
            "startup_delay": 10,
            "cooldown": 5,
        },
        "output": {"recording_path": "", "filename_template": "LOL_{date}_{time}"},
    }
