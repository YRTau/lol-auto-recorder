"""图形界面"""

import logging
import os
import subprocess
import threading
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray

from .recorder import Recorder, State
from .config import load_config, save_config


# ── 颜色常量 ──────────────────────────────────────────────

COLORS = {
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#eab308",
    "orange": "#f97316",
    "gray": "#6b7280",
}

STATE_COLORS = {
    State.IDLE: COLORS["gray"],
    State.WAITING: COLORS["yellow"],
    State.RECORDING: COLORS["green"],
    State.COOLDOWN: COLORS["orange"],
}


# ── GUI 主窗口 ────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("LOL 自动录制工具")
        self.geometry("520x620")
        self.resizable(False, False)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # 加载配置
        self.config_data = load_config()

        # 日志
        self.logger = logging.getLogger("lol-auto-recorder")
        self.logger.setLevel(logging.INFO)

        # 录制器
        self.recorder = Recorder(self.config_data, self.logger)
        self.recorder.on_state_change = self._on_state_change
        self.recorder.on_log = self._on_log
        self.recorder.on_connected = self._on_connected

        # 系统托盘
        self.tray_icon = None
        self._is_closing = False

        # 构建界面
        self._build_ui()
        self._update_status_display()

        # 关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 界面构建 ──────────────────────────────────────────

    def _build_ui(self):
        # 状态栏
        self._build_status_bar()

        # 启停按钮
        self._build_toggle_button()

        # 参数配置
        self._build_config_frame()

        # 日志输出
        self._build_log_frame()

    def _build_status_bar(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=(15, 5))

        # OBS 连接状态
        obs_frame = ctk.CTkFrame(frame, fg_color="transparent")
        obs_frame.pack(side="left", expand=True)

        self.obs_dot = ctk.CTkLabel(obs_frame, text="●", font=("", 18), text_color=COLORS["red"])
        self.obs_dot.pack(side="left", padx=(0, 5))
        self.obs_label = ctk.CTkLabel(obs_frame, text="OBS 未连接", font=("", 13))
        self.obs_label.pack(side="left")

        # 录制状态
        rec_frame = ctk.CTkFrame(frame, fg_color="transparent")
        rec_frame.pack(side="right", expand=True)

        self.rec_dot = ctk.CTkLabel(rec_frame, text="●", font=("", 18), text_color=COLORS["gray"])
        self.rec_dot.pack(side="left", padx=(0, 5))
        self.rec_label = ctk.CTkLabel(rec_frame, text="空闲", font=("", 13))
        self.rec_label.pack(side="left")

    def _build_toggle_button(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=10)

        self.toggle_btn = ctk.CTkButton(
            frame,
            text="▶  启动监控",
            font=("", 16, "bold"),
            height=45,
            width=200,
            fg_color=COLORS["green"],
            hover_color="#16a34a",
            command=self._toggle_recorder,
        )
        self.toggle_btn.pack(side="left", expand=True, padx=(0, 5))

        self.open_folder_btn = ctk.CTkButton(
            frame,
            text="📁 打开录制文件夹",
            font=("", 13),
            height=45,
            width=180,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            command=self._open_recording_folder,
        )
        self.open_folder_btn.pack(side="right", expand=True, padx=(5, 0))

    def _build_config_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=20, pady=(10, 5))

        title = ctk.CTkLabel(frame, text="参数配置", font=("", 14, "bold"))
        title.pack(anchor="w", padx=15, pady=(10, 5))

        # OBS 配置
        obs_cfg = self.config_data["obs"]
        monitor_cfg = self.config_data["monitor"]
        output_cfg = self.config_data["output"]

        grid = ctk.CTkFrame(frame, fg_color="transparent")
        grid.pack(fill="x", padx=15, pady=(0, 10))

        self.entries = {}
        fields = [
            ("OBS 地址", "obs_host", obs_cfg.get("host", "localhost")),
            ("OBS 端口", "obs_port", str(obs_cfg.get("port", 4455))),
            ("OBS 密码", "obs_password", obs_cfg.get("password", "")),
            ("轮询间隔 (秒)", "poll_interval", str(monitor_cfg.get("poll_interval", 3))),
            ("启动延迟 (秒)", "startup_delay", str(monitor_cfg.get("startup_delay", 10))),
            ("冷却时间 (秒)", "cooldown", str(monitor_cfg.get("cooldown", 5))),
            ("录制路径", "recording_path", output_cfg.get("recording_path", "")),
        ]

        for i, (label, key, default) in enumerate(fields):
            ctk.CTkLabel(grid, text=label, font=("", 12)).grid(
                row=i, column=0, sticky="w", pady=3
            )
            show = "•" if key == "obs_password" else ""
            entry = ctk.CTkEntry(grid, width=280, show=show, font=("", 12))
            entry.insert(0, default)
            entry.grid(row=i, column=1, sticky="e", pady=3, padx=(10, 0))
            self.entries[key] = entry

        grid.grid_columnconfigure(1, weight=1)

        # 保存按钮
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkButton(
            btn_frame,
            text="保存配置",
            width=100,
            command=self._save_config,
        ).pack(side="right")

    def _build_log_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=(5, 15))

        title = ctk.CTkLabel(frame, text="运行日志", font=("", 14, "bold"))
        title.pack(anchor="w", padx=15, pady=(10, 5))

        self.log_text = ctk.CTkTextbox(frame, font=("", 11), state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=15, pady=(0, 10))

    # ── 状态更新 ──────────────────────────────────────────

    def _update_status_display(self):
        """更新状态指示灯和按钮"""
        state = self.recorder.state
        color = STATE_COLORS.get(state, COLORS["gray"])

        # 录制状态指示灯
        self.rec_dot.configure(text_color=color)
        self.rec_label.configure(text=state.value)

        # OBS 连接状态
        connected = self.recorder.obs_ctrl.is_connected()
        self.obs_dot.configure(text_color=COLORS["green"] if connected else COLORS["red"])
        self.obs_label.configure(text="OBS 已连接" if connected else "OBS 未连接")

        # 按钮状态
        if self.recorder.is_running:
            self.toggle_btn.configure(
                text="■  停止监控",
                fg_color=COLORS["red"],
                hover_color="#dc2626",
            )
        else:
            self.toggle_btn.configure(
                text="▶  启动监控",
                fg_color=COLORS["green"],
                hover_color="#16a34a",
            )

    # ── 回调（从后台线程调用，需要 after 切到主线程）──────

    def _on_state_change(self, state: State):
        self.after(0, self._update_status_display)

    def _on_log(self, msg: str):
        self.after(0, lambda: self._append_log(msg))

    def _on_connected(self, connected: bool):
        self.after(0, self._update_status_display)

    def _append_log(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ── 按钮事件 ──────────────────────────────────────────

    def _toggle_recorder(self):
        if self.recorder.is_running:
            self.recorder.stop()
        else:
            self.recorder.start()
        self._update_status_display()

    def _open_recording_folder(self):
        """打开录制保存文件夹"""
        path = self.config_data.get("output", {}).get("recording_path", "")
        if not path:
            # 从 OBS 配置文件读取实际录制路径
            path = self._get_obs_recording_path()
        if path and os.path.isdir(path):
            os.startfile(path)
        else:
            self._append_log(f"路径不存在: {path}")

    def _get_obs_recording_path(self) -> str:
        """从 OBS 配置文件读取当前录制路径"""
        import configparser
        # 先读 global.ini 获取当前活跃的 profile
        global_ini = os.path.expandvars(r"%APPDATA%\obs-studio\global.ini")
        cfg = configparser.ConfigParser()
        try:
            with open(global_ini, encoding="utf-8-sig") as f:
                cfg.read_file(f)
        except Exception:
            return ""
        profile_name = cfg.get("Basic", "Profile", fallback="")

        # 读取当前 profile 的录制路径
        ini_path = os.path.expandvars(
            rf"%APPDATA%\obs-studio\basic\profiles\{profile_name}\basic.ini"
        )
        if not os.path.isfile(ini_path):
            return ""
        cfg2 = configparser.ConfigParser()
        try:
            with open(ini_path, encoding="utf-8-sig") as f:
                cfg2.read_file(f)
        except Exception:
            return ""
        path = cfg2.get("AdvOut", "RecFilePath", fallback="")
        if not path:
            path = cfg2.get("SimpleOutput", "FilePath", fallback="")
        return path

    def _save_config(self):
        """保存配置到 config.yaml"""
        try:
            self.config_data["obs"]["host"] = self.entries["obs_host"].get()
            self.config_data["obs"]["port"] = int(self.entries["obs_port"].get())
            self.config_data["obs"]["password"] = self.entries["obs_password"].get()
            self.config_data["monitor"]["poll_interval"] = int(self.entries["poll_interval"].get())
            self.config_data["monitor"]["startup_delay"] = int(self.entries["startup_delay"].get())
            self.config_data["monitor"]["cooldown"] = int(self.entries["cooldown"].get())
            self.config_data["output"]["recording_path"] = self.entries["recording_path"].get()

            save_config(self.config_data)

            # 如果监控正在运行，更新配置
            if self.recorder.is_running:
                self.recorder.update_config(self.config_data)

            self._append_log("配置已保存")
        except ValueError as e:
            self._append_log(f"配置保存失败: {e}")

    # ── 系统托盘 ──────────────────────────────────────────

    def _create_tray_icon_image(self, color: str = "#22c55e") -> Image.Image:
        """生成托盘图标"""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill=color)
        return img

    def _setup_tray(self):
        """创建系统托盘图标"""
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", self._show_window, default=True),
            pystray.MenuItem("退出", self._quit_from_tray),
        )
        self.tray_icon = pystray.Icon(
            "LOL Auto Recorder",
            self._create_tray_icon_image(),
            "LOL 自动录制工具",
            menu,
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_window(self, icon=None, item=None):
        """从托盘恢复窗口"""
        self.after(0, self._restore_window)

    def _restore_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_from_tray(self, icon=None, item=None):
        """从托盘退出程序"""
        self._is_closing = True
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, self._do_quit)

    def _do_quit(self):
        if self.recorder.is_running:
            self.recorder.stop()
        self.destroy()

    def _on_close(self):
        """关闭窗口 → 最小化到托盘"""
        if self._is_closing:
            self._do_quit()
            return

        if self.tray_icon is None:
            self._setup_tray()

        self.withdraw()
        self._append_log("已最小化到系统托盘")
