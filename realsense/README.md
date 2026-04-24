# Intel RealSense D435i 调试工具

## 设备信息

- 型号: Intel RealSense Depth Camera **D435i** (含 IMU)
- USB 标识: VID `0x8086`, PID `0x0B3A`
- 接口: USB 3.0 (USB 2.0 会大幅限制分辨率/帧率)
- 深度传感器: 主动式红外立体视觉 (left + right IR + 红外投射器)
- 彩色传感器: Full HD 1920×1080
- IMU: Bosch BMI055 (accel + gyro)

## 传感器流概览

| 流 | 典型配置 | 说明 |
|----|---------|------|
| Color | 640×480 / 1280×720 / 1920×1080 @ 6-60fps | BGR8/RGB8/YUYV |
| Depth | 640×480 / 848×480 / 1280×720 @ 6-90fps | Z16 (单位见 depth_scale) |
| Infrared 1/2 | 与 Depth 同分辨率 | 左/右红外原图，可用于自定义立体匹配 |
| Accel | 63 / 250 Hz | m/s² |
| Gyro | 200 / 400 Hz | rad/s |

## 平台注意事项

### macOS (arm64)

官方 `pyrealsense2` 不提供 macOS arm64 wheel，本项目在 `pyproject.toml` 里用 [cansik/pyrealsense2-macosx](https://github.com/cansik/pyrealsense2-macosx) 社区构建自动替换，`uv sync` 即可装好。两个包暴露的模块名都是 `pyrealsense2`，脚本无需区分。

**已知问题 1 — USB 权限 / 速率**: macOS 下打开流常报 `failed to set power state`：

1. 设备必须接 USB 3 口 (Type-C 直连或 SS 标识的 USB-A)。USB 2 协商下 librealsense 拒绝进入深度相机模式
2. 系统原生 UVC 驱动会抢占接管 RealSense，librealsense 无法独占设备
3. macOS Sequoia 15+ 的 USB 权限策略对 libusb 设备更严格

**已知问题 2 — 析构竞态**: `pyrealsense2-macosx` 的 librealsense 后台轮询线程会在 Python 退出时与 `~context()` 析构竞争 libusb mutex → 段错误 (signal 11)。本项目在 `device.py` 提供 `clean_exit()`，macOS arm64 下用 `os._exit(0)` 跳过析构；`detect.py` 的 SDK 子进程也做了同样处理。所有脚本 `if __name__ == "__main__"` 块都调用了它。

建议 macOS 下用 `detect.py` 做 USB 层验证即可，完整功能测试走 Linux。

### Linux

#### Jetson (aarch64): pyrealsense2 PyPI wheel 两条都不通，必须源码编

Jetson L4T 36.x / JetPack 6.x 底层 Ubuntu 22.04，glibc 2.35。PyPI pyrealsense2 wheel 两个版本都废：

| 版本 | aarch64 wheel Python ABI | 症状 |
|------|-----------------------|------|
| 2.56.5 (及以前) | 最高到 cp310 | glibc OK，但 **bundled librealsense 2.56 在 Jetson 上枚举设备时 IMU HID 初始化炸** — 日志 `No HID info provided, IMU is disabled` → `rs2_create_device bad optional access`，`ctx.query_devices()[0]` 直接抛 RuntimeError |
| 2.57.7 | cp39/310/312 | wheel 打了假的 `manylinux2014` 标，实际要 glibc 2.38，`import` 时报 `GLIBC_2.38' not found` |

根因：stock Jetson 内核没编 `hid-sensor-hub.ko`，D435i 的 IMU 只绑到 `hid-generic`，不挂 IIO 子系统。Intel 官方 apt 装的 `librealsense2:arm64`（Intel realsense 源）**能**在 Jetson 上跑，是因为它编译时开了 `FORCE_RSUSB_BACKEND=ON`，走纯 libusb 后端，绕开 V4L2+HID。但 Intel apt 源**不提供** `python3-pyrealsense2` 包。PyPI 的两版 wheel 都是默认 V4L2+HID 后端编的。

解决：从源码 v2.57.7 自己编 + Python binding，也加 `FORCE_RSUSB_BACKEND=ON`，装进本子项目 venv：

```bash
# 一次性装好构建依赖（不影响已装的 librealsense2:arm64）
sudo apt install cmake libusb-1.0-0-dev pybind11-dev libssl-dev

# 一键编译 + 安装 (克隆源码到 third_party/, 编译 ~15 min, 装进 .venv)
uv sync                                   # 先建好 venv (Python 3.12, 没有 pyrealsense2 deps)
scripts/build_pyrealsense2.sh             # 克隆 → cmake → make -j6 → 装进 venv → 自检
```

脚本幂等：重跑只做增量 make；换 Python 版本先跑 `scripts/build_pyrealsense2.sh clean` 再重跑。

pyproject.toml 在 linux+aarch64 **不声明** pyrealsense2 依赖（见注释），避免 `uv sync` 从 PyPI 拉坏 wheel 覆盖掉我们的本地 .so。其它平台（linux x86_64 / macOS arm64）仍走 PyPI。

**意外收获**：libuvc 后端不走 Linux HID，反而让 IMU 通了 —— `detect.py` 能枚举到 Motion Module（gyro/accel），`imu.py` 采样正常。

#### USB 设备权限 (udev)

直接 pip/uv 装的 pyrealsense2 通过 libuvc 访问 USB，需配置 udev 规则（或用 `sudo uv run`）：

```bash
# 使用官方仓库规则（推荐）
wget https://raw.githubusercontent.com/realsenseai/librealsense/master/config/99-realsense-libusb.rules
sudo cp 99-realsense-libusb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

插拔设备后生效。

#### USB 速率检查

```bash
lsusb -t   # 观察 D435i 所在 hub 的速率，必须是 5000M (USB 3) 而非 480M (USB 2)
```

USB 2.0 下很多高帧率/高分辨率组合会失败。

#### 图形会话

`stream.py` / `pointcloud.py --view` 需要 `DISPLAY` 或 `WAYLAND_DISPLAY`。SSH 无 X11 转发时会自动切到 headless（保存样本帧）。

#### 固件复位绕过 (历史遗留, Jetson 源码编译链上可能不需要)

早期测试设备固件 **5.12.6** 时，在 Linux kernel 6.x 上不预先复位直接 `pipeline.start()` + `wait_for_frames()` 会稳定超时 `Frame didn't arrive within 5000`。当前测试设备已升级到 **5.17.0.10**，加之 Jetson 走源码编 libuvc 后端，复位绕过可能已不需要；但 `device.py::require_device()` 默认 `reset=True` 暂未改，每个脚本启动多花约 3s。等后续跑流/imu 全部验证稳定后再改默认值。

升级固件用仓库里的 `fw_update.py`——基于 pyrealsense2 自带 API（`check_firmware_compatibility` / `enter_update_state` / `update_device.update`），不依赖 `rs-fw-update` 或 `librealsense2-utils` apt 包（Ubuntu 24.04 noble 上 Intel 源也没对应包）。

```bash
# 下载固件 (D435i 推荐 5.17.0.10):
#   https://dev.realsenseai.com/docs/firmware-releases-d400/
#   选 Signed_Image_UVC_5_17_0_10.bin

uv run fw_update.py                                        # 只列出当前设备 / 固件
uv run fw_update.py --backup Signed_Image_UVC_5_17_0_10.bin   # 升级前先备份
uv run fw_update.py -s 902512070700 Signed_Image_UVC_5_17_0_10.bin
uv run fw_update.py -y Signed_Image_UVC_5_17_0_10.bin      # 跳过确认 (自动化)
```

流程自动走 DFU：`check_firmware_compatibility` → 可选备份 → `enter_update_state` → 等 recovery 模式出现 → `update_device.update` → 等回普通模式 → 打印新版本。升级若从普通模式中断，下次可直接对 recovery 模式设备续写。

升级后把 `require_device(reset=False)` 再测一遍，确认流能直接起来后可考虑把 `device.py::require_device` 默认值改回 `False`。

## 使用

### 检测设备

```bash
uv run detect.py
```

输出 USB 层信息 + pyrealsense2 枚举的设备 / 传感器 / 支持的流配置。

### 抓单帧

```bash
# 默认 640x480 @30fps，抓 color + depth + IR_L + IR_R
uv run capture.py

# 跳过 IR
uv run capture.py --no-ir

# 高分辨率
uv run capture.py --width 1280 --height 720
```

输出到 `./out/`:

- `color_<ts>.png` 彩色图
- `depth_<ts>.png` 16-bit 原始深度 (乘 depth_scale 得米)
- `depth_<ts>_colorized.png` 彩色化可视深度
- `ir_left/right_<ts>.png` 红外图
- `intrinsics_<ts>.json` 内参 + 外参 + depth_scale + 中心像素深度

### 实时预览 / FPS 测试

```bash
# 有 GUI: OpenCV 窗口并排显示 color + 彩色深度，按 q/ESC 退出，s 保存当前帧
uv run stream.py

# 强制 headless: 采集 30s 并统计 FPS，周期性保存样本帧
uv run stream.py --headless --duration 30

uv run stream.py --width 1280 --height 720
```

### IMU 测试 (D435i 专属)

```bash
# 采集 5s，检查采样率 / 重力模长 / 姿态
uv run imu.py

# 换高采样率
uv run imu.py --accel-rate 250 --gyro-rate 400 --duration 10
```

测试时让设备保持静止。重力模长应在 9.8 m/s² ±0.5 以内，gyro 零偏应 <0.05 rad/s。

### 深度对齐测试

```bash
uv run align.py
```

输出到 `./out/align/`:

- `color_raw_*.png` / `depth_raw_colorized_*.png` 原始 (深度相机视角)
- `depth_aligned_colorized_*.png` 对齐到彩色视角
- `overlay_raw_*.png` vs `overlay_aligned_*.png` 叠加图，对齐后深度色带应贴合物体边缘

### 点云导出

```bash
uv run pointcloud.py

# 如安装了 open3d 则弹出 3D 窗口
uv add open3d
uv run pointcloud.py --view
```

输出 `./out/pointcloud/pointcloud_<ts>.ply`，可用 MeshLab / CloudCompare / Open3D 打开。

### 查看结果 (局域网)

在 Linux / 远程机器上跑完后，本机没 GUI 看图片，用 `main.py` 启一个 HTTP 服务把当前目录暴露到局域网：

```bash
uv run main.py              # 默认 0.0.0.0:8001
uv run main.py -p 8080      # 换端口
uv run main.py -b 127.0.0.1 # 仅本机
```

浏览器打开 `http://<设备 IP>:8001/out/` 即可浏览所有抓帧 / PLY / JSON。查本机 IP: `hostname -I` (Linux) 或 `ipconfig getifaddr en0` (macOS)。

## 故障排查

| 现象 | 可能原因 / 处理 |
|------|----------------|
| `pyrealsense2` 导入失败 | Jetson: 必须跑 `scripts/build_pyrealsense2.sh` 从源码编；macOS arm64 依赖 `pyrealsense2-macosx` 自动拉取；其它 linux `uv sync` 就行 |
| `GLIBC_2.38' not found` 或 `bad optional access` | Jetson 用了 PyPI wheel。见 "Jetson (aarch64): pyrealsense2 PyPI wheel 两条都不通" |
| macOS: `failed to set power state` | 换 USB 3 接口；原生 UVC 抢占问题，建议切 Linux 测试 |
| `No device connected` | 检查 `lsusb` / `ioreg`；Linux 上缺 udev 规则 |
| `Couldn't resolve requests` | 分辨率/帧率组合不支持，先跑 `detect.py` 查可用配置 |
| 深度全为 0 | 场景反光过强/距离 <0.2m；或 USB 2.0 带宽不足 |
| `Frame didn't arrive within 5000` | 固件太旧 + 新 kernel 组合问题。`require_device(reset=True)` 已默认绕过，详见 "固件复位绕过" 章节 |
| IMU 采集失败 | D435 无 IMU；确认型号为 D435i |
| color/depth 尺寸不同 | align.py 对齐前尺寸本就不同，这是预期 |

## 参考

- librealsense: https://github.com/realsenseai/librealsense
- Python 绑定文档: https://github.com/realsenseai/librealsense/tree/master/wrappers/python#table-of-contents
- D435i 产品页: https://www.realsenseai.com/products/depth-camera-d435i/
- IMU 坐标系说明: https://github.com/realsenseai/librealsense/blob/master/doc/d435i.md
