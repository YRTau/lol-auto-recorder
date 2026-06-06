# LOL 自动录制工具

检测英雄联盟游戏进程，自动控制 OBS 录制。开局自动录制，游戏结束自动停止。

## 工作原理

```
Python 脚本常驻后台
    ↓ 每 3 秒轮询
检测 League of Legends.exe 进程
    ↓ 检测到进程
等待 10 秒（游戏加载）→ WebSocket → OBS 开始录制
    ↓ 进程消失
等待 5 秒确认 → OBS 停止录制
    ↓ 继续轮询
```

### 状态机

```
IDLE ──检测到进程──→ WAITING ──等10秒──→ RECORDING
 ↑                                          │
 │                                    进程消失
 │                                          ↓
 └──确认进程消失── COOLDOWN ←──等5秒确认──┘
```

### 音频方案（OBS 多音轨）

| 音源 | 音轨 1 | 音轨 2 | 说明 |
|------|--------|--------|------|
| 应用音频采集（LOL进程） | ✅ | ❌ | 纯游戏声音 |
| 桌面音频（耳机输出） | ❌ | ✅ | 游戏+队友语音+系统声音 |
| 麦克风 | ❌ | ✅ | 你的声音 |

录制出来的视频包含两条独立音轨，播放时可切换。

## 前置条件

1. **Python 3.10+**
2. **OBS Studio 28+**（自带 WebSocket 插件）
3. **NVIDIA 显卡**（推荐，使用 NVENC 硬件编码降低性能影响）

## 安装

```bash
cd lol-auto-recorder
pip install -r requirements.txt
```

## OBS 配置

### 1. 开启 WebSocket 服务器

打开 OBS → 工具 → WebSocket 服务器设置 → 勾选「启用 WebSocket 服务器」

默认端口 4455，可设置密码。将密码填入 `config.yaml`。

### 2. 创建英雄联盟专用场景

在 OBS 中创建一个新场景，添加以下源：

| 源类型 | 名称 | 配置 |
|--------|------|------|
| 应用音频采集 | 游戏音频 | 选择 `League of Legends.exe` |
| 音频输出采集 | 桌面音频 | 默认设备（耳机输出） |
| 音频输入采集 | 麦克风 | 默认设备（耳机麦克风） |
| 窗口采集 | 游戏 | 选择 LOL 游戏窗口 |

### 3. 配置音轨

打开「高级音频属性」（混音器右键 → 高级音频属性）：

- 游戏音频 → 只勾选 **音轨 1**
- 桌面音频 → 只勾选 **音轨 2**
- 麦克风 → 只勾选 **音轨 2**

### 4. 录制设置

设置 → 输出 → 输出模式：**高级**

| 配置项 | 推荐值 |
|--------|--------|
| 编码器 | NVIDIA NVENC |
| 码率 | 5000 kbps |
| 格式 | fragmented_mp4（断电不丢数据） |
| 录制音轨 | 勾选音轨 1 + 音轨 2 |

## 使用

```bash
python main.py
```

脚本启动后常驻后台，自动检测游戏并控制 OBS 录制。按 `Ctrl+C` 停止。

## 配置说明

编辑 `config.yaml`：

```yaml
obs:
  host: "localhost"
  port: 4455
  password: ""  # OBS WebSocket 密码

monitor:
  process_name: "League of Legends.exe"
  poll_interval: 3       # 轮询间隔（秒）
  startup_delay: 10      # 开始录制前等待时间（秒）
  cooldown: 5            # 停止录制前确认时间（秒）
```

## 开机自启动（可选）

1. `Win+R` → 输入 `shell:startup` → 打开启动文件夹
2. 创建 `start.bat`：

```bat
@echo off
cd /d "F:\GAME\firstCC\lol-auto-recorder"
python main.py
```

3. 将快捷方式放入启动文件夹

## 性能影响

| 组件 | CPU 占用 |
|------|---------|
| Python 脚本 | ~0.01% |
| OBS 录制（NVENC） | ~3-5% |
| **总计** | **~3-5%** |

## 常见问题

**Q: OBS 没有声音？**
检查场景中是否添加了音频源（应用音频采集 / 音频输出采集），以及音轨是否正确配置。

**Q: 录制文件太大？**
检查 OBS 码率设置。高级输出模式需要在「输出 → 录制」中设置码率，简单模式的码率设置不通用。

**Q: 脚本检测不到游戏？**
确认游戏进程名是 `League of Legends.exe`（不是 `LeagueClient.exe`）。

## 项目结构

```
lol-auto-recorder/
├── main.py           # 主脚本
├── config.yaml       # 配置文件
├── requirements.txt  # Python 依赖
├── .gitignore
└── README.md
```
