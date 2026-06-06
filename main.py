"""
LOL 自动录制工具
检测游戏进程 → 自动开始/停止 OBS 录制
"""

import sys
import time
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path

import psutil
import yaml

try:
    import obsws_python as obs
except ImportError:
    print("错误: 请先安装 obsws-python: pip install obsws-python")
    sys.exit(1)


# ── 状态机 ──────────────────────────────────────────────

class State(Enum):
    IDLE = "空闲"
    WAITING = "等待中"
    RECORDING = "录制中"
    COOLDOWN = "冷却中"


# ── 配置 ────────────────────────────────────────────────

def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        print(f"错误: 找不到配置文件 {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 日志 ────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger("lol-auto-recorder")
    logger.setLevel(logging.INFO)

    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "[%(asctime)s] %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(console)

    # 文件输出
    log_file = log_dir / f"recorder_{datetime.now():%Y%m%d}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    return logger


# ── 进程检测 ─────────────────────────────────────────────

def is_game_running(process_name: str) -> bool:
    """检测游戏进程是否在运行"""
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == process_name:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


# ── OBS 控制 ─────────────────────────────────────────────

class OBSController:
    def __init__(self, host: str, port: int, password: str, logger: logging.Logger):
        self.host = host
        self.port = port
        self.password = password
        self.logger = logger
        self.client = None

    def connect(self) -> bool:
        """连接 OBS WebSocket"""
        try:
            self.client = obs.ReqClient(
                host=self.host,
                port=self.port,
                password=self.password
            )
            # 测试连接
            self.client.get_version()
            self.logger.info("已连接 OBS WebSocket")
            return True
        except Exception as e:
            self.logger.warning(f"连接 OBS 失败: {e}")
            self.client = None
            return False

    def ensure_connected(self) -> bool:
        """确保连接可用"""
        if self.client is None:
            return self.connect()
        try:
            self.client.get_version()
            return True
        except Exception:
            return self.connect()

    def set_recording_path(self, path: str) -> bool:
        """设置录制保存路径（通过修改 OBS 配置参数）"""
        if not self.ensure_connected():
            return False
        try:
            # 高级模式下的录制路径
            self.client.set_profile_parameter("AdvOut", "RecFilePath", path)
            # 简单模式下的录制路径
            self.client.set_profile_parameter("SimpleOutput", "FilePath", path)
            self.logger.info(f"录制路径已设置: {path}")
            return True
        except Exception as e:
            self.logger.warning(f"设置录制路径失败: {e}")
            return False

    def start_recording(self, filename_template: str = "") -> bool:
        """开始录制"""
        if not self.ensure_connected():
            return False
        try:
            self.client.start_record()
            self.logger.info("▶ OBS 开始录制")
            return True
        except Exception as e:
            self.logger.error(f"开始录制失败: {e}")
            return False

    def stop_recording(self) -> str | None:
        """停止录制，返回录制文件路径"""
        if not self.ensure_connected():
            return None
        try:
            result = self.client.stop_record()
            output_path = getattr(result, "output_path", "未知")
            self.logger.info(f"■ OBS 停止录制 → {output_path}")
            return output_path
        except Exception as e:
            self.logger.error(f"停止录制失败: {e}")
            return None

    def is_recording(self) -> bool:
        """检查 OBS 是否正在录制"""
        if not self.ensure_connected():
            return False
        try:
            status = self.client.get_record_status()
            return status.is_recording
        except Exception:
            return False


# ── 主循环 ───────────────────────────────────────────────

def main():
    config = load_config()
    logger = setup_logging()

    obs_cfg = config["obs"]
    monitor_cfg = config["monitor"]
    output_cfg = config["output"]

    process_name = monitor_cfg["process_name"]
    poll_interval = monitor_cfg["poll_interval"]
    startup_delay = monitor_cfg["startup_delay"]
    cooldown = monitor_cfg["cooldown"]

    obs_ctrl = OBSController(
        host=obs_cfg["host"],
        port=obs_cfg["port"],
        password=obs_cfg["password"],
        logger=logger
    )

    state = State.IDLE
    state_time = time.time()

    logger.info("=" * 50)
    logger.info("LOL 自动录制工具已启动")
    logger.info(f"监控进程: {process_name}")
    logger.info(f"轮询间隔: {poll_interval}s | 启动延迟: {startup_delay}s | 冷却: {cooldown}s")
    logger.info(f"OBS 地址: {obs_cfg['host']}:{obs_cfg['port']}")
    logger.info("=" * 50)

    # 设置录制保存路径
    recording_path = output_cfg.get("recording_path", "")
    if recording_path:
        obs_ctrl.set_recording_path(recording_path)

    logger.info("等待游戏开始...")

    try:
        while True:
            game_running = is_game_running(process_name)
            now = time.time()

            if state == State.IDLE:
                if game_running:
                    state = State.WAITING
                    state_time = now
                    logger.info(f"检测到 {process_name}，等待 {startup_delay}s 后开始录制...")

            elif state == State.WAITING:
                if not game_running:
                    # 游戏进程消失（可能闪退），回到空闲
                    state = State.IDLE
                    logger.info("游戏进程已消失，取消录制")
                elif now - state_time >= startup_delay:
                    # 延迟结束，开始录制
                    if obs_ctrl.start_recording():
                        state = State.RECORDING
                        state_time = now
                        logger.info("录制中...")
                    else:
                        # OBS 连接失败，继续等待重试
                        logger.warning("OBS 连接失败，3 秒后重试...")
                        time.sleep(3)

            elif state == State.RECORDING:
                if not game_running:
                    state = State.COOLDOWN
                    state_time = now
                    logger.info(f"游戏进程消失，等待 {cooldown}s 确认...")

            elif state == State.COOLDOWN:
                if game_running:
                    # 游戏重新出现（可能是崩溃重启），回到录制状态
                    state = State.RECORDING
                    state_time = now
                    logger.info("游戏进程重新出现，继续录制")
                elif now - state_time >= cooldown:
                    # 确认游戏结束，停止录制
                    output_path = obs_ctrl.stop_recording()
                    state = State.IDLE
                    logger.info(f"录制完成: {output_path}")
                    logger.info("等待下一场游戏...")

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("\n用户中断，正在停止...")
        if obs_ctrl.is_recording():
            obs_ctrl.stop_recording()
        logger.info("已退出")


if __name__ == "__main__":
    main()
