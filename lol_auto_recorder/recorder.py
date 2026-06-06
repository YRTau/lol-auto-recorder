"""录制核心逻辑：进程检测 + OBS 控制 + 状态机"""

import time
import logging
from enum import Enum
from typing import Callable, Optional

import psutil

try:
    import obsws_python as obs
except ImportError:
    obs = None


class State(Enum):
    IDLE = "空闲"
    WAITING = "等待中"
    RECORDING = "录制中"
    COOLDOWN = "冷却中"


def is_game_running(process_name: str) -> bool:
    """检测游戏进程是否在运行"""
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == process_name:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


class OBSController:
    """OBS WebSocket 控制器"""

    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password
        self.client = None

    def connect(self) -> bool:
        if obs is None:
            return False
        try:
            self.client = obs.ReqClient(
                host=self.host, port=self.port, password=self.password
            )
            self.client.get_version()
            return True
        except Exception:
            self.client = None
            return False

    def ensure_connected(self) -> bool:
        if self.client is None:
            return self.connect()
        try:
            self.client.get_version()
            return True
        except Exception:
            return self.connect()

    def is_connected(self) -> bool:
        if self.client is None:
            return False
        try:
            self.client.get_version()
            return True
        except Exception:
            self.client = None
            return False

    def start_recording(self) -> bool:
        if not self.ensure_connected():
            return False
        try:
            self.client.start_record()
            return True
        except Exception:
            return False

    def stop_recording(self) -> Optional[str]:
        if not self.ensure_connected():
            return None
        try:
            result = self.client.stop_record()
            return getattr(result, "output_path", "未知")
        except Exception:
            return None

    def is_recording(self) -> bool:
        if not self.ensure_connected():
            return False
        try:
            status = self.client.get_record_status()
            return status.is_recording
        except Exception:
            return False


class Recorder:
    """录制控制器，运行在独立线程中"""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._running = False
        self._thread = None

        self.state = State.IDLE
        self.state_time = 0.0

        # 回调函数
        self.on_state_change: Optional[Callable[[State], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_connected: Optional[Callable[[bool], None]] = None

        # 初始化 OBS 控制器
        obs_cfg = config["obs"]
        self.obs_ctrl = OBSController(
            host=obs_cfg["host"],
            port=obs_cfg["port"],
            password=obs_cfg["password"],
        )

    def _emit_log(self, msg: str):
        self.logger.info(msg)
        if self.on_log:
            self.on_log(msg)

    def _set_state(self, new_state: State):
        if self.state != new_state:
            self.state = new_state
            self.state_time = time.time()
            if self.on_state_change:
                self.on_state_change(new_state)

    def update_config(self, config: dict):
        """更新配置（运行时）"""
        self.config = config
        obs_cfg = config["obs"]
        self.obs_ctrl = OBSController(
            host=obs_cfg["host"],
            port=obs_cfg["port"],
            password=obs_cfg["password"],
        )
        self._emit_log("配置已更新")

    def start(self):
        """启动监控"""
        if self._running:
            return

        self._running = True
        self._emit_log("=" * 40)
        self._emit_log("LOL 自动录制工具已启动")

        monitor_cfg = self.config["monitor"]
        self._emit_log(f"监控进程: {monitor_cfg['process_name']}")
        self._emit_log(f"轮询: {monitor_cfg['poll_interval']}s | "
                       f"延迟: {monitor_cfg['startup_delay']}s | "
                       f"冷却: {monitor_cfg['cooldown']}s")
        self._emit_log("=" * 40)
        self._emit_log("等待游戏开始...")

        import threading
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止监控"""
        self._running = False
        if self.state == State.RECORDING:
            self.obs_ctrl.stop_recording()
            self._emit_log("■ 手动停止录制")
        self._set_state(State.IDLE)
        self._emit_log("监控已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    def _run_loop(self):
        """主监控循环（在后台线程运行）"""
        monitor_cfg = self.config["monitor"]
        process_name = monitor_cfg["process_name"]
        poll_interval = monitor_cfg["poll_interval"]
        startup_delay = monitor_cfg["startup_delay"]
        cooldown = monitor_cfg["cooldown"]

        # 检查 OBS 连接
        connected = self.obs_ctrl.ensure_connected()
        if self.on_connected:
            self.on_connected(connected)

        while self._running:
            game_running = is_game_running(process_name)
            now = time.time()

            if self.state == State.IDLE:
                if game_running:
                    self._set_state(State.WAITING)
                    self._emit_log(f"检测到 {process_name}，等待 {startup_delay}s...")

            elif self.state == State.WAITING:
                if not game_running:
                    self._set_state(State.IDLE)
                    self._emit_log("游戏进程消失，取消录制")
                elif now - self.state_time >= startup_delay:
                    if self.obs_ctrl.start_recording():
                        self._set_state(State.RECORDING)
                        self._emit_log("▶ 开始录制")
                    else:
                        self._emit_log("OBS 连接失败，3s 后重试...")
                        # 更新连接状态
                        if self.on_connected:
                            self.on_connected(False)
                        time.sleep(3)
                        continue

            elif self.state == State.RECORDING:
                if not game_running:
                    self._set_state(State.COOLDOWN)
                    self._emit_log(f"游戏进程消失，等待 {cooldown}s 确认...")

            elif self.state == State.COOLDOWN:
                if game_running:
                    self._set_state(State.RECORDING)
                    self._emit_log("游戏进程重新出现，继续录制")
                elif now - self.state_time >= cooldown:
                    output_path = self.obs_ctrl.stop_recording()
                    self._set_state(State.IDLE)
                    self._emit_log(f"■ 录制完成: {output_path}")
                    self._emit_log("等待下一场游戏...")

            time.sleep(poll_interval)

        # 循环结束
        self._set_state(State.IDLE)
