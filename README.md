# doudou-debug

四足机器人豆豆的设备调试工具集。每个设备一个子目录，包含独立的调试/测试脚本。

## 项目结构

```
respeaker/       # ReSpeaker XVF3800 4-Mic Array 调试
realsense/       # Intel RealSense D435i 深度相机调试
damiao/          # 达妙电机 DM4310-P / DM4340 调试 (CAN via CANable 2.0)
bmi088/          # Bosch BMI088 六轴 IMU 调试 (SPI on Jetson)
ina228/          # TI INA228 电流/电压/功率监测 (I2C on Jetson)
```

## 开发约定

- Python 项目统一使用 [uv](https://docs.astral.sh/uv/) 管理依赖，每个子目录是独立的 uv 项目
- 所有调试/测试代码写成可复现的脚本，方便在不同机器上直接运行
- 进入子目录后 `uv run <script>.py` 即可运行，uv 会自动处理虚拟环境和依赖
- 各子目录的 README.md 包含详细的使用说明和设备功能文档

## 快速开始

```bash
# 安装 uv (如果还没装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 进入子项目目录直接运行
cd respeaker
uv run detect.py
```

## 设备清单

| 设备 | 目录 | 状态 |
|------|------|------|
| ReSpeaker XVF3800 4-Mic Array | `respeaker/` | 基础调试完成 (录音/播放/VAD/AEC/降噪/DOA) |
| Intel RealSense D435i | `realsense/` | 基础调试 (检测/单帧抓取/实时流/IMU/对齐/点云) |
| 达妙电机 DM4310-P / DM4340 | `damiao/` | 基础调试 (使能/MIT/Servo/参数/录波, 多电机+固件升级规划中) |
| Bosch BMI088 六轴 IMU | `bmi088/` | 基础调试完成 (detect/probe/stream/imu，含 CHIP_ID / 重力模长 / 陀螺零偏校验，GYR ODR 可配) |
| TI INA228 电流/功率监测 | `ina228/` | 基础调试 + 电量估算 (detect/read/stream/soc，OCV+CHARGE 混合法，6S 3000mAh 自动识别) |

## Jetson USB 接线坑

**XVF3800 不能与 CANable + 蓝牙共用同一个 USB 2.0 Hub**。Jetson Orin Nano dev kit 的某些 USB 口在 `lsusb -t` 里会显示挂在同一个内部 480M Hub 下（例如 `Bus 01 Port 2` 那一组），XVF3800 是 USB isoc SYNC 端点，如果枚举时 isoc 带宽已被 `gs_usb` (CAN) 或 `rtk_btusb` 占用，XHCI 调度出来的包时序错乱，`arecord -D hw:0,0` 读出来就是纯白噪声/沙沙声，喊话无反应。

**现象**: 同一份代码/设备在其它 Ubuntu 机器正常，Jetson 上 `arecord` 也是噪声。
**定位**: `lsusb -t` 看 XVF3800 是否和 gs_usb / Bluetooth 挂在同一个 `Driver=hub` 节点下。
**解决**: 把 XVF3800 插到不经过该内部 Hub 的 USB 口（dev kit 上不同物理口走不同调度路径）。
