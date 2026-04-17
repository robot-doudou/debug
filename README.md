# doudou-debug

四足机器人豆豆的设备调试工具集。每个设备一个子目录，包含独立的调试/测试脚本。

## 项目结构

```
respeaker/       # ReSpeaker XVF3800 4-Mic Array 调试
realsense/       # Intel RealSense D435i 深度相机调试
damiao/          # 达妙电机 DM4310-P / DM4340 调试 (CAN via CANable 2.0)
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
