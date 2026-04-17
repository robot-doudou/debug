# 达妙电机 DM4310-P / DM4340 调试工具

## 设备信息

- 型号: 达妙 **DM4310-P**（当前调试），**DM4340**（前向兼容规划）
- 协议: DM v4 CAN，1 Mbps
- CAN 适配器: Makerbase CANable 2.0（normaldotcom/canable2 fork）
- 电压: 12–28V（当前用 6S 22.2V LiPo）

**DM4310-P 推荐默认参数:**

| 参数 | 默认值 | 硬件上限 |
|------|--------|---------|
| p_max | 12.5 rad | 12.5 rad |
| v_max | 30 rad/s | 30 rad/s |
| t_max | 7 N·m | 7 N·m |

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
                    │       │ 7.5A 慢熔  │    │       ├─ VIN / GND
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

- XT60(母) 焊电池端，正极先串 7.5A 慢熔保险丝（5×20mm 玻璃管式或插片式）
- 保险丝座两端热缩管包裹
- 另一端焊 XT30(公)，16AWG 硅胶线
- 全程红正黑负，XT60/XT30 均有防呆槽但仍需目视确认极性

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

用 `fw_update.py` 将 CANable 2.0 从 slcan 固件升级到 candleLight（gs_usb / SocketCAN）。

```bash
# 查当前固件信息
uv run fw_update.py --info

# 烧录 candleLight 固件
uv run fw_update.py <path_to_candleLight_fw.bin>
```

**操作流程：**

1. 拔 USB
2. 短接 BOOT 跳线（或按住 BOOT 按键）
3. 插回 USB（进入 DFU 模式，`0483:df11` 出现）
4. 脚本自动轮询等待 DFU 设备，调用 `dfu-util` 烧录
5. 等设备重新枚举成 `1d50:606f`（约 10s），提示 `ip link show can0`

**`.bin` 文件不进仓库，请自行下载或编译：**

- 官方 `candle-usb/candleLight_fw`：`make CANABLE2=1`  
  → https://github.com/candle-usb/candleLight_fw
- `normaldotcom/candleLight_fw` Releases  
  → https://github.com/normaldotcom/canable2

**系统前置依赖：**

```bash
sudo apt install dfu-util
```

---

## 使用

### detect.py — 检测设备

```bash
uv run detect.py                      # 完整检测（USB + can0 + 电机探活）
uv run detect.py --skip-motor         # 只做 USB + can0
uv run detect.py --motor-id 0x05      # 非默认 ID 电机
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
| 电机无反馈 | `motor_id` / `master_id` 不匹配；bitrate 不是 1 Mbps；CAN_H/CAN_L 反接 |
| 使能后电机抽搐 | KP 过大；`pos_target` 离当前 pos 过远；未调用 `clear_error` |
| MIT 点控不动 | `tau_limit` 比克服负载所需扭矩小，用 `--unsafe --tau 2` 试 |
| `--live` 无窗口 | SSH 无 X11 转发，自动降级走 PNG；本地运行时检查 `DISPLAY` 环境变量 |
| 改完 ID 失联 | 拔电重上，用新 ID 重连；忘记旧 ID 时只能逐个 scan |

---

## 参考

- 达妙官网 / 手册: https://www.damiaoyeah.com/
- python-can 文档: https://python-can.readthedocs.io/
- CANable 2.0 (normaldotcom fork): https://github.com/normaldotcom/canable2
- candleLight_fw: https://github.com/candle-usb/candleLight_fw
- DM 电机 v4 协议 MIT/Servo 细节可查官方 SDK（正点原子 / GitHub 上多处开源实现）
