# 达妙电机 DM4310-P / DM4340 调试工具

## 设备信息

- 型号: 达妙 **DM4310-P**（当前调试），**DM4340**（前向兼容规划）
- 协议: DM v4 CAN，1 Mbps
- CAN 适配器: Makerbase CANable 2.0（normaldotcom/canable2 fork）
- 电压: 12–28V（当前用 6S 22.2V LiPo）

**DM4310-P V4 电气规格:**

| 参数 | 额定 | 峰值 |
|------|------|------|
| 扭矩 | 3.5 N·m | 12.5 N·m |
| 电流 | 5 A | 20 A |
| 转速 | — | 30 rad/s |
| 位置范围 | — | ±12.5 rad |

**DMMotor 构造默认（`p_max / v_max / t_max`）—— 对应电机固件 PMAX/VMAX/TMAX 寄存器值:**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| p_max | 12.5 rad | 固件 PMAX (reg 0x15) |
| v_max | 30 rad/s | 固件 VMAX (reg 0x16) |
| t_max | 10.0 N·m | 固件 TMAX (reg 0x17) —— 注意：电机物理峰值 12.5 N·m，但固件出厂 TMAX=10 是 MIT tau 字段的缩放上限，想访问 12.5 N·m 需先用 `params.py --set TMAX 12.5 --save` 改固件 |

**如果 DMMotor `t_max` 和电机固件 TMAX 不一致，MIT tau 编码会有缩放偏差**（比如你代码写 `tau=10, t_max=12.5`，电机固件 TMAX=10 实际只输出 10×(10/12.5)=8 N·m）。改寄存器和代码两端都要同步。

**DM4340 参数（TODO: 待实机测试确认，以手册为准）:**

| 参数 | 占位默认值 | 说明 |
|------|-----------|------|
| p_max | 12.5 rad | 待确认 |
| v_max | 25 rad/s | 待确认 |
| t_max | 15 N·m | 待确认 |

> DM4340 参数为规划占位值，实际使用前务必查阅达妙官方手册，以手册数值为准。

---

## 硬件台架

### 接线图

```
         ┌──────────── 桌面空转，输出轴不夹持 ──────────┐
         │                                              │
         │                                              ▼
  22.2V LiPo 6S1P ──┬── XT60(母) ──┐           ┌── DM4310-P
  3000mAh 75C       │              │           │    ├─ 动力 +/-  (XT30 公)
  (格氏)            │              │           │    └─ CAN/电源头 (5P)
                    │       ┌──────┴──────┐    │       │
                    │       │ 20A 慢熔   │    │       ├─ VIN / GND
                    │       │ 保险丝     │    │       ├─ CAN_H
                    │       └──────┬──────┘    │       ├─ CAN_L
                    │              │           │       └─ GND (逻辑地)
                    │         XT30(公) ────────┘
                    │
                    └── 热缩管封装整段适配线

  USB Type-C ─── CANable 2.0 ─ CAN_H ─────┤ CAN_H
              (板载 120Ω 终端 ON)  CAN_L ─┤ CAN_L
                                    GND ──┤ GND
                                          └─── 电机 CAN 侧
```

### 通电顺序

1. 确认 XT60/XT30 适配线完好、保险丝装好、电机轴无缠绕
2. **USB 先插上主机**（`can0` 出现，`ip link` 可见）
3. 电池 XT60 接适配线，此时电机上电待机
4. `uv run detect.py` 验证 CAN 通讯 + 读电机版本
5. 跑任何控制脚本前再次**目视确认电机能自由旋转**

### 适配线自制说明

- XT60(母) 焊电池端，正极先串 **20A 慢熔保险丝**（汽车刀片式或 5×20mm 玻璃管式）
- 保险丝座两端热缩管包裹
- 另一端焊 XT30(公)，16 AWG 硅胶线
- 全程红正黑负，XT60/XT30 均有防呆槽但仍需目视确认极性

**保险丝选型原理：**

| 规格 | 评价 |
|------|------|
| 7.5A / 15A | 正常堵转/急加速峰值 20A 就会误熔，别用 |
| **20A 慢熔** | **推荐**：允许 30A 脉冲短时通过（慢熔特性），持续 >20A 才断；匹配 XT30 连续 15A / 脉冲 30A 的载流瓶颈 |
| 25A | 折衷可用，但 XT30 在 25A 持续下会慢慢过热 |
| 40A | 只防 LiPo 死短路起火（百安级瞬断），不保护 XT30——故障半导通拉 30A 持续时 XT30 会先融化 |

关键线路瓶颈排序：**XT30 连续 15A < 16AWG 硅胶线 22A < 4310P 峰值 20A**。20A 慢熔是让"正常峰值过、异常持续断"的最佳点。

### CAN 终端电阻

- **CANable 2.0 板侧**：焊盘跳线 `R_TERM` 焊上（或拨码开关 ON）
- **电机侧（单机）**：4310P / 4340 内部未集成，单电机场景无需外加终端电阻
- **多电机**：总线物理最远端电机的 CAN_H/CAN_L 之间并一颗 120Ω 1/4W 电阻

---

## 安全

### 默认软限幅

所有控制脚本默认启用安全限幅（`SAFE_DEFAULTS`）。`--unsafe` 才放开到硬件上限。

| 参数 | 软限幅默认值 | 硬件上限（4310P） |
|------|-------------|-----------------|
| tau（扭矩） | 1 N·m | 7 N·m |
| vel（速度） | 5 rad/s | 30 rad/s |
| pos（位置） | ±π rad | ±12.5 rad |
| kp | 20 | 500 |
| kd | 1 | 5 |

### 启停纪律

1. 所有控制脚本均用 `with DMMotor(bus, ...) as m:` 上下文管理器——进入即 `clear_error → enable`，退出无条件 `disable()`
2. MIT 首帧：`pos_target = 当前 pos`，避免冷启动瞬间猛拉
3. `Ctrl-C / 异常 / 正常退出` 均触发 `disable()`；`atexit` 再兜底一次
4. 改电机 ID 等敏感操作需要 `--confirm-id-change` 显式 flag
5. 改完 ID 必须**拔电重上**，用新 ID 重连

### 急停规程

> **紧急情况：拔电池 XT60 头。** 不要依赖软件急停——软件挂掉后电机会停在最后一条命令状态，物理断电是唯一可靠的急停手段。

---

## Linux 环境

`sudo bash setup.sh` 一次性完成所有 Linux 配置：

1. 写 `/etc/udev/rules.d/99-canable.rules`（slcan `16d0:117e` 和 candleLight `1d50:606f` 两种 VID:PID 的 USB 权限）
2. 写 `/etc/systemd/system/can0-up.service`（`can0` 设备出现时自动以 1 Mbps 拉起）
3. `udevadm control --reload-rules && udevadm trigger`
4. `systemctl daemon-reload && systemctl enable --now can0-up.service`

```bash
# 一次性装好
sudo bash setup.sh

# 验证 can0 状态
ip -details link show can0
```

### CANable 2.0 固件状态对比

| 固件 | VID:PID | 接口 | 备注 |
|------|---------|------|------|
| slcan（出厂）| `16d0:117e` | `/dev/ttyACM0` | python-can slcan 模式，速度受限 |
| candleLight（目标） | `1d50:606f` | `can0`（SocketCAN） | 内核 `gs_usb` 驱动，推荐 |

> 如果 `ip link show can0` 找不到设备，说明固件仍是 slcan，需先跑 `fw_update.py` 烧录 candleLight。

---

## 固件烧录

将 CANable 2.0 从 slcan 固件升级到 candleLight（gs_usb / SocketCAN）。三条路按简易程度排：

### 方式 A：浏览器一键烧（最简单，推荐）

打开 https://canable.io/updater/canable2.html ，选 **candlelight**，点按钮。浏览器通过 WebUSB 直接烧录，免 `dfu-util` 也免 BOOT 跳线。仅 Chrome / Edge 支持 WebUSB。

### 方式 B：本仓库自带 bin + 烧录脚本

仓库里已放好 `canable2_fw-ba6b1dd.bin`（16752 字节，commit `ba6b1dd`，2021-07，canable.io 官方 flasher 用的同一份）。

```bash
# 系统前置依赖
sudo apt install dfu-util

# 查当前固件信息 (应显示 slcan 16d0:117e)
uv run fw_update.py --info

# 烧录 (脚本会提示 BOOT 跳线操作, 等 DFU, 调 dfu-util)
uv run fw_update.py canable2_fw-ba6b1dd.bin
```

想取最新版自行下载：`wget https://canable.io/builds/canable2/candlelight/canable2_fw-ba6b1dd.bin`。

**方式 B 操作流程：**

1. 拔 USB
2. 短接 BOOT 跳线（或按住 BOOT 按键）
3. 插回 USB（进入 DFU 模式，`0483:df11` 出现）
4. 脚本自动轮询等待 DFU 设备，调用 `dfu-util` 烧录
5. 等设备重新枚举成 `1d50:606f`（约 10s），提示 `ip link show can0`

### 方式 C：从源码编译

```bash
git clone https://github.com/normaldotcom/candleLight_fw.git
cd candleLight_fw && git checkout canable
mkdir build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=../cmake/arm-none-eabi-gcc.cmake
make
```

### 注意事项

- 方式 A/B 的 pre-built bin 是 2021 年的 commit `ba6b1dd`，**3 年未更新**，但它就是 canable.io 官方 flasher 用的版本，无数设备已验证
- 上游 `candle-usb/candleLight_fw` 仓库**不支持** STM32G431，G431 的 candleLight 代码在 `normaldotcom/candleLight_fw` 的 `canable` 分支
- 烧完 `lsusb` 应看到 `1d50:606f` 代替 `16d0:117e`

---

## 使用

**所有单电机脚本（detect / enable / mit / servo / params）共用一套 ID 参数：**

- `--id N`（十进制 1..15）—— **快捷写法**：`motor_id = N`，`master_id = N + 0x10`。例：`--id 2` ≡ `--motor-id 0x02 --master-id 0x12`；`--id 10` ≡ `--motor-id 0x0A --master-id 0x1A`
- `--motor-id 0xXX` / `--master-id 0xXX` —— 显式指定（可覆盖 `--id` 推算值，比如出厂电机 motor_id=0x01、master_id=0x00，不走 `--id` 的 +0x10 约定）
- 都不给 → 默认 `0x01 / 0x00`（刚到手出厂电机）

### detect.py — 检测设备

```bash
uv run detect.py                      # 完整检测（USB + can0 + 电机探活, 用出厂默认 0x01/0x00）
uv run detect.py --skip-motor         # 只做 USB + can0
uv run detect.py --id 5               # 探活 FR_HFE (motor=0x05, master=0x15)
uv run detect.py --motor-id 0x05      # 非 +0x10 约定的电机, 配合 --master-id 用
```

枚举 CANable 2.0（两种 VID:PID）、检查 `can0` 状态、发送 1-shot 探活帧并读取电机固件版本。

---

### enable.py — 使能 / 状态 / 失能烟雾测试

```bash
uv run enable.py                      # 瞬时：使能 → 读几帧 → 失能
uv run enable.py --hold 5             # 保持 5 秒，每 100ms 打印一帧状态
```

---

### mit.py — MIT 模式点控

```bash
uv run mit.py --profile sine --duration 5 --kp 10 --kd 0.5
uv run mit.py --profile step --duration 2 --target 0.3
uv run mit.py --profile hold --duration 3
uv run mit.py --profile sine --duration 10 --live       # 实时画图
uv run mit.py --profile sine --unsafe --tau 5           # 放开安全限幅
```

输出到 `out/`：`mit_<profile>_<ts>.csv` + 同名 `.png`（4 子图：pos、vel、tau vs 时间，err 码）。

`--live` 模式打开 matplotlib 实时窗口；SSH 无 `DISPLAY`/`WAYLAND_DISPLAY` 时自动降级为静态 PNG，不报错。

---

### servo.py — Servo POS / SPEED 模式

> 前置：电机已通过 `params.py` 切换到 Servo 模式。

```bash
uv run servo.py --mode pos --target 1.0 --duration 3
uv run servo.py --mode speed --target 2.0 --duration 3
```

---

### params.py — 寄存器读写

```bash
uv run params.py --list                                          # 列可识别寄存器
uv run params.py --get PMAX                                      # 按名字读
uv run params.py --get 0x07                                      # 按 ID 读
uv run params.py --set TMAX 5.0                                  # 写（未固化）
uv run params.py --save                                          # 保存到 Flash
uv run params.py --set-zero                                      # 当前位置置零
uv run params.py --clear-error                                   # 清错
uv run params.py --change-id 0x05 0x15 --confirm-id-change      # 改 ID（需确认 flag）
```

> 改完 ID 必须拔电重上，用新 ID 重连。如忘记旧 ID 只能逐个扫描。

---

### main.py — 远程查看 out/ 数据

```bash
uv run main.py                  # 默认监听 0.0.0.0:8001
uv run main.py -p 8080          # 换端口
uv run main.py -b 127.0.0.1     # 仅本机访问
```

浏览器打开 `http://<设备 IP>:8001/out/` 即可浏览所有 CSV / PNG。查本机 IP: `hostname -I`

---

## 多电机配置（12 电机四足）

豆豆四足 = 4 腿 × 3 关节 = **12 电机**。出厂电机全是 `motor_id=0x01, master_id=0x00`，多颗共总线**必须先孤立配 ID**，否则同 ID 帧会冲突无法配置。

### 推荐 ID 分配

| 腿 | 关节 | motor_id | MST_ID |
|----|------|---------|--------|
| **FL**（前左） | HAA (Hip 外展) | 0x01 | 0x11 |
|  | HFE (Thigh) | 0x02 | 0x12 |
|  | KFE (Knee) | 0x03 | 0x13 |
| **FR**（前右） | HAA | 0x04 | 0x14 |
|  | HFE | 0x05 | 0x15 |
|  | KFE | 0x06 | 0x16 |
| **RL**（后左） | HAA | 0x07 | 0x17 |
|  | HFE | 0x08 | 0x18 |
|  | KFE | 0x09 | 0x19 |
| **RR**（后右） | HAA | 0x0A | 0x1A |
|  | HFE | 0x0B | 0x1B |
|  | KFE | 0x0C | 0x1C |

**编号规则：**

- `motor_id = leg_idx × 3 + joint_idx + 1`，腿顺序 FL/FR/RL/RR，关节顺序 HAA/HFE/KFE
- `MST_ID = motor_id + 0x10`，命令 ID(0x01-0x0C) 与回复 ID(0x11-0x1C) 不冲突
- `motor_id ≤ 0x0F`：MIT 反馈帧 byte 0 低 4 bit 装 motor_id，**≥ 16 会被截断**，12 颗刚好够用 1-C
- `motor_id = 0x00` 不用：避免和广播/调试保留值打架

### 配置命令（每颗电机走一遍）

**关键：一次只让一颗待配电机在总线上**（出厂全都是 0x01，多颗同 ID 会撞）。

```bash
# 步骤循环 12 次, 每次:
#   1) 拔掉所有已配好的电机 CAN 线 (动力线可以保留)
#   2) 接上下一颗待配电机的 CAN_H/L/GND
#   3) 给这颗电机上电
#   4) 跑下面对应的 uv 命令
#   5) 拔电重上 (ID 更改后必须复位)
#   6) 用新 ID 验证

# FL (前左)
uv run params.py --change-id 0x01 0x11 --confirm-id-change   # FL_HAA (出厂默认即 0x01/0x00, 此条只改 MST_ID)
uv run params.py --change-id 0x02 0x12 --confirm-id-change   # FL_HFE
uv run params.py --change-id 0x03 0x13 --confirm-id-change   # FL_KFE

# FR (前右)
uv run params.py --change-id 0x04 0x14 --confirm-id-change   # FR_HAA
uv run params.py --change-id 0x05 0x15 --confirm-id-change   # FR_HFE
uv run params.py --change-id 0x06 0x16 --confirm-id-change   # FR_KFE

# RL (后左)
uv run params.py --change-id 0x07 0x17 --confirm-id-change   # RL_HAA
uv run params.py --change-id 0x08 0x18 --confirm-id-change   # RL_HFE
uv run params.py --change-id 0x09 0x19 --confirm-id-change   # RL_KFE

# RR (后右)
uv run params.py --change-id 0x0A 0x1A --confirm-id-change   # RR_HAA
uv run params.py --change-id 0x0B 0x1B --confirm-id-change   # RR_HFE
uv run params.py --change-id 0x0C 0x1C --confirm-id-change   # RR_KFE
```

**每颗电机配完立刻验证：**

```bash
# 拔电重上后, 用新 ID 探活
uv run detect.py --motor-id 0x05 --master-id 0x15   # 例: 验 FR_HFE
```

**全部 12 颗配完后挂总线扫描验证：用 `multi_motor.py`**

```bash
uv run multi_motor.py --scan          # 探活全部 12 颗, 报告 alive/dead 列表
uv run multi_motor.py --scan --leg FL # 只扫前左 3 颗
uv run multi_motor.py --read --hold 3 # 全部 enable 3 秒读 state, 然后失能
```

详见 `multi_motor.py --help`。

### 总线带宽

单路 CAN 1 Mbps 实际帧率上限 ~7-8k 帧/s。12 电机命令+回复 = 24 帧/周期，**前期建议 200 Hz 控制**（4800 帧/s，余 40% 带宽）。1 kHz 控制需要 4 路 CAN（每腿独立），属 C scope 升级路径。

---

## 后续规划

以下功能在 C 范围规划中，暂未实现：

- **同总线多电机支持**：4310P + 4340 共用 `can0`，需分配不同 CAN_ID
- **DM 协议 CAN 固件升级**：直接通过总线烧写电机固件（无需额外工具）
- **高频控制循环 benchmark**：1 kHz 闭环 + 抖动测量
- **故障码解析表**：将电机 `err_code` 字段翻译为人类可读描述

---

## 故障排查

| 现象 | 可能原因 / 处理 |
|------|----------------|
| `detect.py` 找不到 USB 设备 | CANable 未插 / udev 规则未生效（跑 `setup.sh`）/ cable 只供电不通讯 |
| `can0` 不存在 | 固件仍是 slcan（先跑 `fw_update.py`）；或内核缺 `gs_usb` 驱动 |
| `ip link set can0 up` 失败 | 未指定 bitrate / 权限不够，跑 `sudo bash setup.sh` 装 systemd unit |
| 电机无反馈 | `motor_id` / `master_id` 不匹配；bitrate 不是 1 Mbps；CAN_H/CAN_L 反接；CAN GND 没接（差分信号缺共模参考）|
| 探活默认 master_id 不对 | DM4310-P V4 出厂 master_id 实测为 `0x00`，不是某些手册写的 `0x11`；本仓库已默认 `0x00`，如手动指定别忘改 |
| 使能后电机抽搐 | KP 过大；`pos_target` 离当前 pos 过远；未调用 `clear_error` |
| MIT 点控不动 | `tau_limit` 比克服负载所需扭矩小，用 `--unsafe --tau 2` 试 |
| `--live` 无窗口 | SSH 无 X11 转发，自动降级走 PNG；本地运行时检查 `DISPLAY` 环境变量 |
| 改完 ID 失联 | 拔电重上，用新 ID 重连；忘记旧 ID 时只能逐个 scan |
| `dfu-util: Cannot open DFU device ... LIBUSB_ERROR_ACCESS` | DFU 模式 (`0483:df11`) 权限不够。老版本 `setup.sh` 未包含此规则，跑 `sudo bash setup.sh` 覆盖更新即可；临时过关可 `sudo uv run fw_update.py <bin>` |
| `dfu-util: Warning: Invalid DFU suffix signature` | 无害。pre-built bin 没附 DFU 后缀签名，脚本用 `-s 0x08000000:leave` 绕过，不影响烧录 |

---

## 参考

- 达妙官网 / 手册: https://www.damiaoyeah.com/
- **达妙官方控制例程仓库 (Gitee)**: https://gitee.com/kit-miao/motor-control-routine/tree/master
  - Python 版 DM_CAN.py: https://gitee.com/kit-miao/motor-control-routine/raw/master/Python%E4%BE%8B%E7%A8%8B/u2can/DM_CAN.py
  - 本仓库 `device.py` 的 MIT/Servo/参数帧已与此例程核对一致（详见 commit history）
- 社区实现 (C + Python, 独立核对): https://github.com/cmjang/DM_Control_Python
- python-can 文档: https://python-can.readthedocs.io/
- CANable 2.0 (normaldotcom slcan fork): https://github.com/normaldotcom/canable2
- candleLight_fw (normaldotcom G431 fork): https://github.com/normaldotcom/candleLight_fw
- candleLight_fw 上游 (不支持 G431): https://github.com/candle-usb/candleLight_fw
- CANable 官方 web flasher: https://canable.io/updater/canable2.html
