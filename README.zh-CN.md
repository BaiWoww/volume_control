# VolumeMixer（音量合成器）

一款轻量级 Windows 音量合成助手，以桌面悬浮球的形式存在。它复刻了 Windows 设置 -> 声音 -> 音量合成器中的按应用音量控制，并通过一个极简、随时可用的界面呈现出来。

[English](./README.md) · **简体中文**

---

## 功能

- **悬浮控制球** – 可拖动、边缘吸附、数秒无操作后自动隐藏，默认置顶。
- **按应用音量合成器** – 列出所有活动音频会话（含系统音效），每个会话都有独立的音量滑块与静音开关。
- **主音量控制** – 在同一面板调节系统端点音量并静音。
- **实时刷新** – 通过 `IAudioSessionNotification` 自动出现新音频源；面板还会每两秒轮询一次。
- **友好的进程名** – 从可执行文件资源中解析 `FileDescription`（例如显示“Google Chrome”而非“chrome”）。
- **系统音效会话** – 通过 `SHLoadIndirectString` 读取本地化显示名资源来检测并标注。
- **平滑动画** – 使用 `QPropertyAnimation` 实现悬停、点击、边缘吸附、自动隐藏与面板淡入淡出。
- **单实例、低开销** – 应用是无托盘、无边框的 PyQt5 部件；不安装任何后台服务。

## 截图

_在此添加截图。_ 典型布局：

```
+-------------------------------------+
|  悬浮球           音量面板           |
|    ( )             +-----------+    |
|                   | 主音量 80 |    |
|                   | Chrome 60 |    |
|                   | Spotify 40 |    |
|                   +-----------+    |
+-------------------------------------+
```

## 环境要求

- Windows 10 或 Windows 11（使用 Windows Audio Session API / WASAPI）
- Python 3.7 或更高版本
- 可用的音频输出设备

## 安装

```powershell
# 1. 克隆仓库
git clone https://github.com/BaiWoww/volume_control.git
cd volume_control

# 2.（推荐）创建虚拟环境
python -m venv venv
.\venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt
```

## 从源码运行

```powershell
python main.py
```

主屏幕右边缘会出现一个蓝色悬浮球。左键打开音量面板；右键打开上下文菜单（切换置顶、退出）。

### Windows 便捷启动脚本

双击 `start.bat`。它会检查 Python，首次运行时创建虚拟环境，安装依赖并启动应用。

## 构建独立可执行文件

提供了 PyInstaller spec 文件：

```powershell
pyinstaller volume_mixer.spec
```

单文件可执行程序会输出到 `dist/VolumeMixer.exe`。`build/`、`dist/` 和 `__pycache__/` 目录已通过 `.gitignore` 排除出版本控制。

## 项目结构

```
volume_control/
├── audio_controller.py   # COM / WASAPI 封装，会话枚举，静音 / 音量控制
├── floating_ball.py      # 无边框圆形部件，拖动 / 吸附 / 自动隐藏逻辑
├── volume_panel.py       # 按会话的合成器面板，含滑块与静音按钮
├── main.py               # 入口：QApplication，异常钩子，装配
├── requirements.txt      # 固定版本的 Python 依赖
├── start.bat             # Windows 启动器，创建 venv 并运行 main.py
├── volume_mixer.spec     # PyInstaller 构建配置
├── .gitignore            # 标准 Python + PyInstaller + IDE 排除项
├── LICENSE               # MIT 许可证
└── README.md             # 本文件
```

## 工作原理

### `audio_controller.py`

- 在 STA 单元中初始化 COM，与 PyQt5 的线程模型匹配。
- 封装 `pycaw.pycaw.AudioUtilities`，通过 `GetAllSessions()` 枚举音频会话。
- 对每个会话：
  - 跳过 `AudioSessionState.Expired`（state = 2）条目以避免 COM 错误。
  - 通过 `IsSystemSoundsSession()` 检测系统音效会话，并用 `SHLoadIndirectString` 解析其本地化名称（因为原始值是 `@dllpath,-resid` 资源引用）。
  - 按 PID 缓存友好名称，优先使用可执行文件版本资源中的 `FileDescription`。
- 提供一个 `SessionNotificationSink` COM 对象，实现 `IAudioSessionNotification`，并通过 Qt 信号将新会话事件转发回 UI。
- 暴露 `get_master_volume / set_master_volume / get_master_mute / set_master_mute` 用于系统端点。

### `floating_ball.py`

- 一个无边框、半透明的 `QWidget`，带 `Qt.Tool | Qt.WindowStaysOnTopHint`。
- 自绘一个带径向渐变高光和手绘喇叭图标的蓝色光亮球体。
- 使用 `QPropertyAnimation` 实现悬停缩放（1.0 -> 1.12）、按下缩放（0.92）、边缘吸附与空闲自动隐藏。
- 左键切换 `VolumePanel`；右键打开带样式的上下文菜单。

### `volume_panel.py`

- 一个无边框弹窗，带圆角半透明容器，使用 Qt 样式表绘制。
- 包含一个用于主端点的 `VolumeSlider`，外加每个活动会话一个。
- 可见时每两秒刷新会话列表；每次刷新都会增量地添加 / 移除 / 更新滑块部件以避免闪烁。
- 滑块颜色层级（静音 / 低 / 中 / 高）通过分层样式表应用，以降低重绘开销。

## 限制

- 仅支持 Windows。`pycaw` 与 `comtypes` 库及底层 WASAPI 调用没有可移植的等价物。
- 少量系统进程（尤其是某些运行在 `PID 0` 下、并非系统音效会话的 Windows 组件）会被过滤掉。
- 某些进程即使存在活动音频会话也拒绝暴露 `SimpleAudioVolume`；这些进程在面板中不可见，与 Windows 内置音量合成器的行为一致。

## 贡献

欢迎提交 Pull Request。请先开 issue 讨论重大改动。提交前请运行现有测试 / 手动冒烟测试面板。

## 开发

### 安装

```powershell
git clone https://github.com/BaiWoww/volume_control.git
cd volume_control
python -m venv venv
.\venv\Scripts\activate
pip install -e ".[dev]"
```

`.[dev]` 额外依赖会安装 `mypy`、`PyQt5-stubs`、`pytest` 和 `pytest-qt`。

### 类型检查

代码库带有完整的 PEP 484 类型注解。运行 `mypy` 检查源码模块：

```powershell
python -m mypy --ignore-missing-imports config.py logging_setup.py main.py audio_controller.py volume_panel.py floating_ball.py i18n.py hotkey.py
```

`pyproject.toml`（`[tool.mypy]`）中的配置是规范设置文件。

### 测试

测试套件位于 `tests/` 下。它 mock 了 COM / WASAPI 栈，并使用
`QT_QPA_PLATFORM=offscreen` 以便在 CI 上无人值守运行：

```powershell
python -m pytest tests/
```

覆盖范围：

- `tests/test_pure_functions.py` – `_volume_tier`、`_color_for_name`、层级
  边界与配置驱动的阈值。
- `tests/test_audio_controller.py` – 会话枚举、排序、去重、跳过 Expired、
  `_sav_cache` 填充、主音量钳制、COM 失败处理、幂等的 `shutdown()`。
- `tests/test_volume_panel.py` – 主滑块回退、单次 emit 的
  `panel_closed`、应用滑块的增量添加/移除、空状态标签。
- `tests/test_config.py` – `apply_overrides()` 校验规则。
- `tests/test_i18n.py` – 文本目录健全性。
- `tests/test_main.py` – 程序化应用图标、单实例互斥锁。

### 日志

滚动文件日志写入 `%APPDATA%\VolumeMixer\app.log`（非 Windows 为
`~/.config/VolumeMixer/app.log`）。所有异常通过
`logging_setup.install_excepthook()` 路由到此日志。该日志对调试在真实
Windows 会话之外无法复现的 COM 问题极为有用。

### 用户配置

`%APPDATA%\VolumeMixer\config.json`（非 Windows 为
`~/.config/VolumeMixer/config.json`）处的 JSON 文件可覆盖以下值：

```json
{
  "panel_refresh_ms": 2000,
  "idle_hide_ms": 5000
}
```

未知键会被忽略。低于合理下限的值（例如
`panel_refresh_ms < 250`）会被拒绝，以防止 UI 饥饿。

## 许可证

[MIT](LICENSE) – Copyright (c) 2025 BaiWoww.
