# 豆豆四足机器人 — 设备调试工具集

`doudou-debug/` 是自制四足机器人 **"豆豆"** 的硬件 bring-up / 回归验证工具集。每个子目录对应豆豆身上的一块硬件，独立的 uv 项目。

**计算平台**: Jetson Orin Nano Developer Kit, JetPack 6.x (L4T 36.x), kernel 5.15.x-tegra

## 硬件栈

| 目录 | 设备 | 接口 | 作用 |
|------|------|------|------|
| `respeaker/` | Seeed ReSpeaker XVF3800 4-Mic Array | USB | 语音交互 |
| `realsense/` | Intel RealSense D435i (含 BMI055 IMU) | USB 3 | 机头感知 / VIO |
| `damiao/` | 达妙 DM4310-P / DM4340 ×12 | CAN (CANable 2.0) | 12 关节电机 |
| `bmi088/` | Bosch BMI088 六轴 IMU | SPI0 | 躯干 IMU，平衡控制闭环 |

BMI088 与 D435i 内置 IMU 分工：BMI088 测**身体**，D435i IMU 跟相机头 (做 VIO 用)。

## Jetson 平台关键坑

- **40-pin J12**: I2C1/I2C7 出厂启用；**SPI0/SPI1 出厂是 GPIO**，必须 `sudo /opt/nvidia/jetson-io/jetson-io.py` 勾 `spi1` / `spi3` 才路由到物理针。菜单名按 SoC 控制器编号，Linux 侧叫 `spidev0` / `spidev1`，两套命名要对照。
- **`/dev/spidev*` 出厂就绑 `spidev` 驱动，但 pinmux 可能没切过去** —— "节点存在 ≠ SPI 真工作"。**loopback 测试** (MOSI pin 19 短 MISO pin 21，看首字节回送) 是唯一可靠的硬件层验证。
- 出厂用户默认在 `gpio` 组，`/dev/spidev*` 是 `root:gpio` 0660，**无需配 udev**。
- I2C Bus 1 (pin 27/28) 默认占用地址 `0x40` 和 `0x25`；接外设（尤其 INA228 默认地址 `0x40`）走 **Bus 7 (pin 3/5)** 避免冲突。

## 协作原则

- **Python 项目统一用 `uv`**，子项目 `pyproject.toml` 默认 `>=3.10,<3.13` (respeaker 例外 3.14)
- **README 先行**：开发新子项目先出接线方案 / 启用步骤 / 验证方法 / 预期现象，用户对照接线完再写代码
- **硬件资料原文保留**：用户贴的 pinout / 寄存器表等参考资料**完整复刻**到 README "硬件参考资料" 章节，不只做精简摘要；前面放速查，后面放原文兜底
- **设备介绍单开 `intro.md`**：README 是接线/使用手册，`intro.md` 解释"这东西是啥/干嘛用"，README 开头加一行链接指引
- **脚本命名跨子项目对齐**：`detect.py` / `stream.py` / `imu.py` / `main.py` / `device.py`，新子项目照 `realsense/` 骨架搭
- **不擅自动系统**：`sudo` / `jetson-io.py` / `udevadm` 等改系统状态的操作只给指令让用户跑，不绕过
- **"节点存在 ≠ 功能可用"**：下"已配好"结论必须有硬件层验证（loopback / chip_id / 回环波形），不要只凭 `/dev/xxx` 出现就下结论
