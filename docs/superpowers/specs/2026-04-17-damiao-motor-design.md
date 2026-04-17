# 达妙电机 DM4310-P / DM4340 调试工具 设计文档

日期: 2026-04-17
目标设备: 达妙 DM4310-P（当前），DM4340（后续，协议同为 v4，同工具支持）
CAN 适配器: Makerbase CANable 2.0（normaldotcom fork）

## 1. 目标与范围

### 本期交付（B 范围）

在 `damiao/` 子目录下提供与 `respeaker/` `realsense/` 同风格的独立调试工具，功能覆盖：

1. USB / CAN 链路检测，电机探活与固件版本读取
2. CANable 2.0 固件从 slcan 烧到 candleLight（进 SocketCAN）
3. 电机使能 / 失能 / 清错 / 实时状态读取
4. MIT 模式点控（step / sine / hold），带安全限幅
5. Servo 模式点控（POS / SPEED）
6. 电机参数读写（ID / 限幅 / PID / 零点 / 保存到 Flash）
7. 数据记录：默认落 CSV + 静态 PNG，`--live` 切 matplotlib 实时窗口
8. HTTP 浏览 `out/` 下的数据（复用 realsense `main.py`）

### 后续规划（C 范围 — 写进 README roadmap）

- 同总线多电机支持（4310P + 4340 共用 `can0`）
- DM 协议固件升级（直接通过 CAN 烧电机固件）
- 高频控制循环 benchmark（1 kHz 闭环 + 抖动测量）
- 故障码解析表（电机错误字段人类可读）

## 2. 硬件台架

### 2.1 接线图（ASCII，写进 README）

```
         ┌──────────── 桌面空转，输出轴不夹持 ──────────┐
         │                                              │
         │                                              ▼
  22.2V LiPo 6S1P ──┬── XT60(母) ──┐           ┌── DM4310-P
  3000mAh 75C       │              │           │    ├─ 动力 +/-  (XT30 公)
  (格氏)            │              │           │    └─ CAN/电源头 (5P)
                    │       ┌──────┴──────┐    │       │
                    │       │ 7.5A 慢熔  │    │       ├─ VIN / GND
                    │       │ 保险丝     │    │       ├─ CAN_H
                    │       └──────┬──────┘    │       ├─ CAN_L
                    │              │           │       └─ GND (逻辑地)
                    │         XT30(公) ────────┘
                    │
                    └── 热缩管封装整段适配线
                                          ┌─────────────────┐
  USB Type-C ─── CANable 2.0 ─ CAN_H ─────┤ CAN_H
              (板载 120Ω 终端 ON)  CAN_L ─┤ CAN_L
                                    GND ──┤ GND
                                          └─── 电机 CAN 侧
```

### 2.2 通电顺序（写进 README 安全章节）

1. 确认 XT60/XT30 适配线完好、保险丝装好、电机轴无缠绕
2. USB 先插上主机（`can0` 出现，`ip link` 可见）
3. 电池 XT60 接适配线，此时电机上电待机
4. `uv run detect.py` 验证 CAN 通讯 + 读电机版本
5. 跑任何控制脚本前再次目视确认电机能自由旋转
6. **紧急情况：拔电池 XT60 头**，不要依赖软件急停

### 2.3 适配线自制（README 配 ASCII 图）

- XT60(母) 焊电池端，正极先串 7.5A 慢熔汽车保险丝（5×20mm 玻璃管式，或插片式）
- 保险丝座两端热缩管包裹
- 另一端焊 XT30(公)，16AWG 硅胶线足够
- 全程红正黑负不可反，XT60/XT30 均有防呆槽但仍需目视确认

### 2.4 CAN 终端电阻

- **CANable 2.0 板侧** —— 焊盘跳线 `R_TERM` 焊上（或拨码开关 ON）
- **电机侧** —— 4310P / 4340 内部未集成，单电机场景无需外加
- 未来接入第二颗电机时，在总线物理最远端电机的 CAN_H/CAN_L 之间并一颗 120Ω 1/4W 电阻

### 2.5 短线单机理想布线

- 三根线：CAN_H / CAN_L / GND 全接
- 长度 ≤ 0.5m，双绞更好（1 Mbps 下短线不双绞也能跑）
- GND 必须连，否则差分信号共模漂移会误码

## 3. CAN 适配器固件

### 3.1 选型

当前：`16d0:117e` slcan（normaldotcom/canable2）
目标：`1d50:606f` candleLight（gs_usb 内核驱动，SocketCAN 原生 `can0`）

### 3.2 `fw_update.py` 功能

- `--info`：列当前 USB ID、固件版本、bus 名称
- 默认：
  1. 读当前固件（slcan `V` 命令 或 USB descriptor）
  2. 提示用户操作：**短接 BOOT 跳线（或按住 BOOT 按键）后重插 USB** 进 DFU 模式
     —— 不尝试"软触发 DFU"，不同固件版本支持情况不一致，依靠物理 BOOT 更确定
  3. 等 `0483:df11` DFU 设备出现（轮询 30s，每秒打印一次"等待中..."）
  4. `dfu-util -a 0 -s 0x08000000:leave -D <bin>` 烧录
  5. 等重新枚举成 candleLight VID:PID（轮询 10s），提示 `ip link show can0`
- `-y` 跳过交互式确认，仍需物理 BOOT 跳线人工操作（烧录本身是破坏性操作，不做全自动化）
- `.bin` 不进仓库，README 指引两个候选来源：
  - 官方 `candle-usb/candleLight_fw`（`make CANABLE2=1`）
  - `normaldotcom/candleLight_fw` Releases

### 3.3 前置依赖

- `dfu-util` 系统包（`apt install dfu-util`）
- 可选 `pyusb` 用于查询 DFU 状态

## 4. Linux 环境

### 4.1 `setup.sh` 一键脚本

```
1. 写 /etc/udev/rules.d/99-canable.rules:
   SUBSYSTEM=="usb", ATTR{idVendor}=="16d0", ATTR{idProduct}=="117e", MODE="0666"  # slcan
   SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666"  # candleLight

2. 写 /etc/systemd/system/can0-up.service:
   [Unit]
   Description=Bring up can0 at 1 Mbps
   BindsTo=sys-subsystem-net-devices-can0.device
   After=sys-subsystem-net-devices-can0.device
   [Service]
   Type=oneshot
   ExecStart=/usr/sbin/ip link set can0 up type can bitrate 1000000
   RemainAfterExit=yes
   [Install]
   WantedBy=sys-subsystem-net-devices-can0.device

3. udevadm control --reload-rules && udevadm trigger
4. systemctl daemon-reload && systemctl enable --now can0-up.service
5. 检查: ip -details link show can0
```

选 systemd unit 方案而非 systemd-networkd：更通用（不依赖 networkd），CAN 接口出现时自动触发，脚本一次性输出，排错直观。

幂等：已存在的规则文件跳过写入，打印 `[skip]`。
需要 `sudo`；脚本首行 `#!/usr/bin/env bash`，第二行 `set -euo pipefail`。

### 4.2 运行时依赖

- `python-can >= 4.4`
- `numpy`
- `matplotlib`
- kernel ≥ 5.x 带 `gs_usb` 驱动（主流发行版默认有）

## 5. 软件架构

### 5.1 目录布局

```
damiao/
├── README.md
├── pyproject.toml
├── setup.sh
├── device.py
├── detect.py
├── fw_update.py
├── enable.py
├── mit.py
├── servo.py
├── params.py
├── main.py
└── out/
    ├── trace_mit_sine_YYYYMMDD_HHMMSS.csv
    ├── trace_mit_sine_YYYYMMDD_HHMMSS.png
    └── ...
```

### 5.2 `device.py` — 共享层

**`DMMotor` 类**（上下文管理器）

```python
class DMMotor:
    def __init__(self, bus, motor_id=0x01, master_id=0x11,
                 p_max=12.5, v_max=30.0, t_max=7.0,
                 safety=SAFE_DEFAULTS): ...

    # 控制帧
    def enable(self)           # CAN ID=motor_id, data=FF×7 + FC
    def disable(self)          # ...FD
    def set_zero(self)         # ...FE
    def clear_error(self)      # ...FB
    def mit_cmd(self, pos, vel, kp, kd, tau)   # 64bit 位域打包
    def servo_pos(self, pos, vel)              # ID=0x100+motor_id
    def servo_speed(self, vel)                 # ID=0x200+motor_id

    # 反馈（订阅 master_id）
    def read_state(self, timeout=0.05) -> MotorState  # pos, vel, tau, T_mos, T_rotor, err

    # 参数读写（寄存器号按 DM v4 协议表）
    def read_param(self, reg_id) -> float
    def write_param(self, reg_id, value)
    def save_to_flash(self)
    def change_id(self, new_motor_id, new_master_id)  # 敏感操作，要求 --confirm-id-change

    # 纪律
    def __enter__(self):  clear_error → ping → enable
    def __exit__(...):    disable (无条件重试 1 次)
```

**辅助函数**
- `open_bus(interface='socketcan', channel='can0', bitrate=1_000_000, fallback_slcan=True)` — 优先 socketcan，失败尝试 slcan `/dev/ttyACM0`
- `output_dir(subdir='') -> Path`（同 realsense）
- `timestamped(prefix, ext)`（同 realsense）
- `register_safe_shutdown(motor)` — SIGINT + `atexit` 注册

**安全默认常量**

```python
SAFE_DEFAULTS = SafetyLimits(
    tau=1.0,     # N·m
    vel=5.0,     # rad/s
    pos=3.14,    # rad (±π)
    kp=20.0,
    kd=1.0,
)
```

所有控制脚本默认启用；`--unsafe` 放开到硬件上限。

### 5.3 脚本清单

| 脚本 | 功能 |
|------|------|
| `detect.py` | USB 枚举 CANable（两种 VID:PID）+ `can0` 状态 + 1-shot 探活电机 + 读固件版本 |
| `fw_update.py` | slcan → candleLight DFU 烧录（第 3 节） |
| `enable.py` | 单次使能、读状态、失能；`--hold 5` 保持使能 5 秒测反馈稳定性 |
| `mit.py` | MIT 模式点控，`--profile step|sine|hold`，`--duration` `--kp` `--kd` `--tau-limit` `--live` |
| `servo.py` | `--mode pos|speed`，`--target <值>`，`--duration` |
| `params.py` | `--list` 列可读寄存器，`--get <reg>`，`--set <reg>=<值>`，`--set-zero`，`--clear-error`，`--save`，`--change-id NEW_ID NEW_MASTER_ID --confirm-id-change` |
| `main.py` | LAN HTTP（复用 realsense 同款，`0.0.0.0:8001`） |

### 5.4 启停纪律

1. `with DMMotor(bus, ...) as m:` —— 进入即 clear_error → ping → enable
2. 控制循环内所有命令过 `safety` 限幅（软限）
3. `Ctrl-C / 异常 / 正常退出` 均触发 `disable()`；`atexit` 再兜底一次
4. MIT 首帧：`pos_target = m.read_state().pos`，避免冷启动瞬间猛拉

### 5.5 数据记录

**默认（静态）**

- `out/trace_<profile>_<ts>.csv`：列 = `t, pos, vel, tau, tau_cmd, pos_cmd, vel_cmd, err_code`
- `out/trace_<profile>_<ts>.png`：matplotlib 4 子图（位置、速度、扭矩对比、误差码）

**`--live`（实时）**

- matplotlib `FuncAnimation` 窗口，关窗后同时落 CSV + PNG
- 无 `DISPLAY`/`WAYLAND_DISPLAY` 时自动降级为默认模式（打印一行提示，不报错）
- 数据采样频率独立于绘图刷新，底层用 ring buffer

## 6. 安全策略总览

| 层级 | 手段 |
|------|------|
| 物理 | 保险丝 7.5A + 电机空转 + 拔电池为终极急停 |
| 驱动 | `DMMotor` 上下文进出强制 enable/disable，`atexit` + `SIGINT` 兜底 |
| 软件限幅 | `SAFE_DEFAULTS` 默认启用，`--unsafe` 才放开 |
| 首帧 | MIT `pos_target = 当前 pos`，servo 同理从当前状态起步 |
| 参数写入 | `change-id` 类敏感操作要求 `--confirm-id-change` 显式 flag |

## 7. 故障排查（写进 README）

| 现象 | 可能原因 / 处理 |
|------|----------------|
| `detect.py` 找不到 USB 设备 | CANable 未插 / udev 规则未生效 / cable 只供电不通讯 |
| `can0` 不存在 | 固件仍是 slcan（先跑 `fw_update.py`）或内核缺 gs_usb 驱动 |
| `ip link set can0 up` 失败 | 未加 bitrate / 权限不够（跑 `setup.sh` 装 unit） |
| 电机无反馈 | motor_id / master_id 不匹配（问过上位机确认）、bitrate 不是 1 Mbps、CAN_H/L 反接 |
| 使能后电机抽搐 | KP 过大、pos_target 离当前 pos 过远、未调用 clear_error |
| MIT 点控不动 | tau_limit 比克服阻力小（放开到 2 N·m 试） |
| `--live` 无窗口 | SSH 无 X11 转发，自动降级走 PNG；本地运行检查 DISPLAY |
| 改完 ID 失联 | 拔电重上，用新 ID 重连；忘记旧 ID 时只能逐个 scan |

## 8. 开放问题

- DM4340 与 4310P 的扭矩/速度/位置上限不同，`DMMotor` 构造时允许覆盖 `p_max/v_max/t_max`；README 给两款的推荐默认值
- 固件 v4 的具体寄存器号表需照官方手册实现 `params.py`，实现阶段确认最新版本

## 9. 与仓库其他调试工具的关系

- 根 `README.md` 的「设备清单」表格追加 `达妙电机 DM4310-P / DM4340 | damiao/ | 基础调试 (MIT/Servo/参数/录波)`
- `main.py` 与 realsense 保持一致，但本目录独立一份（每个子项目自成 uv 项目）
- 不共享 Python 代码到仓库根部；每个设备的 `device.py` 自给自足
