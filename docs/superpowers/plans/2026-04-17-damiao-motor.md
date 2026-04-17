# 达妙电机 DM4310-P / DM4340 调试工具 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `damiao/` 子目录下交付达妙 DM4310-P（含 4340 前向兼容）的 Python 调试工具集，覆盖 USB/CAN 检测、CANable 2.0 slcan→candleLight 烧录、MIT/Servo 模式控制、参数读写、数据录波。

**Architecture:** 单进程 Python 脚本集 + python-can SocketCAN（slcan 自动降级）。`device.py` 封装 DM v4 协议与安全限幅的 `DMMotor` 类（上下文管理器，进入即 enable，退出无条件 disable）。纯协议逻辑（位域打包/解包/限幅）走 TDD，硬件脚本实现后人工验收。

**Tech Stack:** Python 3.10+、uv、python-can ≥ 4.4、numpy、matplotlib、pytest（dev）、dfu-util（系统包）、systemd unit + udev。

**Spec:** `docs/superpowers/specs/2026-04-17-damiao-motor-design.md`

---

## 文件布局

```
damiao/
├── README.md              # T16: 硬件接线 ASCII + 安全章节 + 脚本用法 + 故障排查
├── pyproject.toml         # T1: uv 项目
├── setup.sh               # T8: udev + systemd unit 一键安装
├── device.py              # T2-T7: 协议 + 安全 + DMMotor 类
├── detect.py              # T9: USB + can0 + 电机探活
├── fw_update.py           # T10: DFU 烧录
├── enable.py              # T11: 使能/读状态/失能
├── mit.py                 # T12: MIT 模式 + 录波 + --live
├── servo.py               # T13: Servo POS/SPEED
├── params.py              # T14: 寄存器读写 + 改 ID + 保存
├── main.py                # T15: HTTP 文件浏览（复用 realsense 同款）
├── tests/
│   ├── __init__.py
│   ├── test_protocol.py   # T3-T7: MIT/Servo/param 帧编解码
│   └── test_safety.py     # T2: 限幅钳制
└── out/                   # 运行时生成
```

---

## Task 1: uv 项目骨架

**Files:**
- Create: `damiao/pyproject.toml`
- Create: `damiao/tests/__init__.py`

- [ ] **Step 1: 创建目录与空测试包**

```bash
mkdir -p damiao/tests
touch damiao/tests/__init__.py
```

- [ ] **Step 2: 写 `damiao/pyproject.toml`**

```toml
[project]
name = "damiao"
version = "0.1.0"
description = "达妙电机 DM4310-P / DM4340 调试工具 (CAN via Makerbase CANable 2.0)"
requires-python = ">=3.10,<3.13"
dependencies = [
    "python-can>=4.4",
    "numpy>=1.26",
    "matplotlib>=3.8",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: 跑 `uv sync` 确认依赖能装**

```bash
cd damiao && uv sync
```

Expected: 成功，`.venv/` 与 `uv.lock` 生成。

- [ ] **Step 4: Commit**

```bash
git add damiao/pyproject.toml damiao/tests/__init__.py damiao/uv.lock
git commit -m "Scaffold damiao/ uv project"
```

---

## Task 2: device.py — 安全限幅与工具函数

**Files:**
- Create: `damiao/device.py`
- Create: `damiao/tests/test_safety.py`

- [ ] **Step 1: 写失败测试 `tests/test_safety.py`**

```python
"""测试 SafetyLimits 钳制逻辑 (纯函数, 无硬件)。"""
import math
import pytest
from device import SafetyLimits, SAFE_DEFAULTS


def test_safe_defaults_values():
    assert SAFE_DEFAULTS.tau == 1.0
    assert SAFE_DEFAULTS.vel == 5.0
    assert math.isclose(SAFE_DEFAULTS.pos, 3.14)
    assert SAFE_DEFAULTS.kp == 20.0
    assert SAFE_DEFAULTS.kd == 1.0


def test_clamp_tau_saturates_positive():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_tau(5.0) == 1.0


def test_clamp_tau_saturates_negative():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_tau(-10.0) == -1.0


def test_clamp_tau_within_range_unchanged():
    limits = SafetyLimits(tau=2.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_tau(0.5) == 0.5


def test_clamp_vel_symmetric():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_vel(10.0) == 5.0
    assert limits.clamp_vel(-10.0) == -5.0


def test_clamp_pos_symmetric():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=1.0, kp=20.0, kd=1.0)
    assert limits.clamp_pos(2.0) == 1.0
    assert limits.clamp_pos(-2.0) == -1.0


def test_clamp_kp_nonnegative_upper_only():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_kp(100.0) == 20.0
    assert limits.clamp_kp(-5.0) == 0.0  # KP 不能为负


def test_clamp_kd_nonnegative_upper_only():
    limits = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)
    assert limits.clamp_kd(5.0) == 1.0
    assert limits.clamp_kd(-1.0) == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd damiao && uv run pytest tests/test_safety.py -v
```

Expected: `ModuleNotFoundError: No module named 'damiao.device'` 或类似。

- [ ] **Step 3: 实现 `damiao/device.py` 骨架（安全限幅 + 工具函数）**

```python
"""达妙电机 DM4310-P / DM4340 共享层: CAN 总线 / DM v4 协议 / 安全限幅 / 输出路径。

DM 电机 USB 适配器标识 (CANable 2.0):
    slcan:        VID 0x16D0, PID 0x117E  (normaldotcom fork)
    candleLight:  VID 0x1D50, PID 0x606F  (gs_usb 内核驱动)
"""

from __future__ import annotations

import os
import pathlib
import sys
from dataclasses import dataclass
from datetime import datetime


# --- 安全限幅 ---

@dataclass(frozen=True)
class SafetyLimits:
    tau: float   # N·m, 对称
    vel: float   # rad/s, 对称
    pos: float   # rad, 对称
    kp: float    # 非负上限
    kd: float    # 非负上限

    def clamp_tau(self, x: float) -> float:
        return max(-self.tau, min(self.tau, x))

    def clamp_vel(self, x: float) -> float:
        return max(-self.vel, min(self.vel, x))

    def clamp_pos(self, x: float) -> float:
        return max(-self.pos, min(self.pos, x))

    def clamp_kp(self, x: float) -> float:
        return max(0.0, min(self.kp, x))

    def clamp_kd(self, x: float) -> float:
        return max(0.0, min(self.kd, x))


SAFE_DEFAULTS = SafetyLimits(tau=1.0, vel=5.0, pos=3.14, kp=20.0, kd=1.0)


# --- 输出路径 / 时间戳 ---

def output_dir(subdir: str = "") -> pathlib.Path:
    base = pathlib.Path(__file__).parent / "out"
    if subdir:
        base = base / subdir
    base.mkdir(parents=True, exist_ok=True)
    return base


def timestamped(prefix: str, ext: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}.{ext}"


def has_display() -> bool:
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd damiao && uv run pytest tests/test_safety.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add damiao/device.py damiao/tests/test_safety.py
git commit -m "Add SafetyLimits and output helpers to damiao.device"
```

---

## Task 3: device.py — MIT 命令帧位域打包

**Files:**
- Modify: `damiao/device.py`
- Create: `damiao/tests/test_protocol.py`

**背景:** DM v4 MIT 模式 8 字节帧布局（来自官方 SDK `float_to_uint` + 位域排布）:

```
float_to_uint(x, min, max, bits):
    return int((x - min) * ((1 << bits) - 1) / (max - min))  # C 风格截断, 不四舍五入

byte 0: pos[15:8]             (16-bit)
byte 1: pos[7:0]
byte 2: vel[11:4]             (12-bit)
byte 3: (vel[3:0] << 4) | kp[11:8]
byte 4: kp[7:0]               (12-bit)
byte 5: kd[11:4]              (12-bit)
byte 6: (kd[3:0] << 4) | tau[11:8]
byte 7: tau[7:0]              (12-bit)

范围: pos ∈ [-p_max, p_max], vel ∈ [-v_max, v_max], kp ∈ [0, kp_max],
     kd ∈ [0, kd_max], tau ∈ [-t_max, t_max]
默认 kp_max=500, kd_max=5 (DM 官方 SDK 常量)
```

**测试向量推导 (p_max=12.5, v_max=30, t_max=7):**

```
pos=0:  uint = (0-(-12.5)) * 65535 / 25 = 32767.5 → 32767 = 0x7FFF
vel=0:  uint = (0-(-30))   * 4095  / 60 = 2047.5  → 2047  = 0x7FF
kp=0:   uint = 0
kd=0:   uint = 0
tau=0:  uint = (0-(-7))    * 4095  / 14 = 2047.5  → 2047  = 0x7FF

byte 0..7: 7F FF 7F F0 00 00 07 FF
```

- [ ] **Step 1: 写失败测试 `tests/test_protocol.py`**

```python
"""DM v4 协议帧编解码测试 (纯位操作, 无硬件)。

测试向量按官方 SDK float_to_uint (C 风格截断) 推导, 细节见 device.py 注释。
"""
import pytest
from device import float_to_uint, uint_to_float, pack_mit_cmd


def test_float_to_uint_mid_point_truncates():
    # pos=0, p_max=12.5, 16-bit: 应为 0x7FFF (截断非四舍五入)
    assert float_to_uint(0.0, -12.5, 12.5, 16) == 0x7FFF


def test_float_to_uint_max_endpoint():
    assert float_to_uint(12.5, -12.5, 12.5, 16) == 0xFFFF


def test_float_to_uint_min_endpoint():
    assert float_to_uint(-12.5, -12.5, 12.5, 16) == 0


def test_float_to_uint_clips_above_max():
    # 超过 max 截到最大值 (保险不溢出)
    assert float_to_uint(20.0, -12.5, 12.5, 16) == 0xFFFF


def test_float_to_uint_clips_below_min():
    assert float_to_uint(-20.0, -12.5, 12.5, 16) == 0


def test_uint_to_float_roundtrip_endpoints():
    assert uint_to_float(0xFFFF, -12.5, 12.5, 16) == pytest.approx(12.5, rel=1e-4)
    assert uint_to_float(0, -12.5, 12.5, 16) == pytest.approx(-12.5, rel=1e-4)


def test_pack_mit_cmd_all_zero_mid():
    # 全零输入 (pos=vel=kp=kd=tau=0) 期望: 7F FF 7F F0 00 00 07 FF
    data = pack_mit_cmd(pos=0.0, vel=0.0, kp=0.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data == bytes([0x7F, 0xFF, 0x7F, 0xF0, 0x00, 0x00, 0x07, 0xFF])


def test_pack_mit_cmd_max_pos():
    # pos=12.5 → pos_int=0xFFFF, 其余零
    data = pack_mit_cmd(pos=12.5, vel=0.0, kp=0.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data[0] == 0xFF  # pos_high
    assert data[1] == 0xFF  # pos_low


def test_pack_mit_cmd_min_pos():
    data = pack_mit_cmd(pos=-12.5, vel=0.0, kp=0.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data[0] == 0x00
    assert data[1] == 0x00


def test_pack_mit_cmd_kp_max_500():
    # kp=500 → kp_int=0xFFF; byte 3 低 4 bit = kp_int[11:8] = 0xF
    data = pack_mit_cmd(pos=0.0, vel=0.0, kp=500.0, kd=0.0, tau=0.0,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert data[3] & 0x0F == 0x0F
    assert data[4] == 0xFF


def test_pack_mit_cmd_returns_8_bytes():
    data = pack_mit_cmd(pos=1.0, vel=0.5, kp=10.0, kd=0.5, tau=0.2,
                        p_max=12.5, v_max=30.0, t_max=7.0)
    assert len(data) == 8
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd damiao && uv run pytest tests/test_protocol.py -v
```

Expected: `ImportError: cannot import name 'float_to_uint'`.

- [ ] **Step 3: 在 `damiao/device.py` 追加协议函数**

追加到 `device.py` 末尾:

```python
# --- DM v4 协议: 位域打包/解包 ---

KP_MAX_DEFAULT = 500.0   # 官方 SDK 常量
KD_MAX_DEFAULT = 5.0


def float_to_uint(x: float, x_min: float, x_max: float, bits: int) -> int:
    """官方 SDK float_to_uint 的 Python 等价实现 (C 风格截断)。

    超出 [x_min, x_max] 的输入会截断到 [0, 2^bits - 1] 保险避免溢出。
    """
    span = x_max - x_min
    if span <= 0:
        raise ValueError(f"x_max ({x_max}) 必须大于 x_min ({x_min})")
    max_uint = (1 << bits) - 1
    if x >= x_max:
        return max_uint
    if x <= x_min:
        return 0
    return int((x - x_min) * max_uint / span)


def uint_to_float(u: int, x_min: float, x_max: float, bits: int) -> float:
    max_uint = (1 << bits) - 1
    return u * (x_max - x_min) / max_uint + x_min


def pack_mit_cmd(pos: float, vel: float, kp: float, kd: float, tau: float,
                 p_max: float, v_max: float, t_max: float,
                 kp_max: float = KP_MAX_DEFAULT,
                 kd_max: float = KD_MAX_DEFAULT) -> bytes:
    """打包 MIT 模式 8 字节控制帧。CAN ID = motor_id, DLC = 8。"""
    pos_i = float_to_uint(pos, -p_max, p_max, 16)
    vel_i = float_to_uint(vel, -v_max, v_max, 12)
    kp_i  = float_to_uint(kp, 0.0, kp_max, 12)
    kd_i  = float_to_uint(kd, 0.0, kd_max, 12)
    tau_i = float_to_uint(tau, -t_max, t_max, 12)

    return bytes([
        (pos_i >> 8) & 0xFF,
        pos_i & 0xFF,
        (vel_i >> 4) & 0xFF,
        ((vel_i & 0x0F) << 4) | ((kp_i >> 8) & 0x0F),
        kp_i & 0xFF,
        (kd_i >> 4) & 0xFF,
        ((kd_i & 0x0F) << 4) | ((tau_i >> 8) & 0x0F),
        tau_i & 0xFF,
    ])
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd damiao && uv run pytest tests/test_protocol.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add damiao/device.py damiao/tests/test_protocol.py
git commit -m "Add DM v4 MIT command frame packer with test vectors"
```

---

## Task 4: device.py — MIT 反馈帧解析

**背景:** DM v4 MIT 反馈帧（电机→主机，CAN ID = master_id）:

```
byte 0: (err[7:4] << 4) | motor_id[3:0]   # 错误码 + 电机 ID 回显
byte 1: pos[15:8]
byte 2: pos[7:0]
byte 3: vel[11:4]
byte 4: (vel[3:0] << 4) | tau[11:8]
byte 5: tau[7:0]
byte 6: T_mos   (°C, uint8)
byte 7: T_rotor (°C, uint8)

错误码 (err 4-bit): 0=Disable, 1=Enable, 8=Overvoltage, 9=Undervoltage,
                   A=Overcurrent, B=MOS 过温, C=电机过温, D=通讯丢失, E=过载
```

**Files:**
- Modify: `damiao/device.py`
- Modify: `damiao/tests/test_protocol.py`

- [ ] **Step 1: 追加失败测试**

追加到 `tests/test_protocol.py`:

```python
from device import MotorState, parse_mit_feedback


def test_parse_mit_feedback_zero_mid():
    # 对应 pack 全零的反馈逆过程: 7F FF 7F F? ?? T_mos T_rotor
    # byte 0: err=1(Enable), id=0x01 → 0x11
    # pos=0x7FFF, vel=0x7FF, tau=0x7FF
    data = bytes([0x11, 0x7F, 0xFF, 0x7F, 0xF7, 0xFF, 0x19, 0x23])  # T_mos=25, T_rotor=35
    state = parse_mit_feedback(data, p_max=12.5, v_max=30.0, t_max=7.0)
    assert state.motor_id == 0x01
    assert state.err_code == 1
    assert state.pos == pytest.approx(0.0, abs=1e-3)
    assert state.vel == pytest.approx(0.0, abs=1e-2)
    assert state.tau == pytest.approx(0.0, abs=1e-2)
    assert state.t_mos == 25
    assert state.t_rotor == 35


def test_parse_mit_feedback_err_code_extracted():
    # err=0xA (Overcurrent), id=0x02 → byte0 = 0xA2
    data = bytes([0xA2, 0x80, 0x00, 0x80, 0x08, 0x00, 0x00, 0x00])
    state = parse_mit_feedback(data, p_max=12.5, v_max=30.0, t_max=7.0)
    assert state.motor_id == 0x02
    assert state.err_code == 0xA


def test_parse_mit_feedback_wrong_length():
    with pytest.raises(ValueError):
        parse_mit_feedback(bytes(7), p_max=12.5, v_max=30.0, t_max=7.0)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd damiao && uv run pytest tests/test_protocol.py -v
```

Expected: `ImportError: cannot import name 'MotorState'`.

- [ ] **Step 3: 在 `device.py` 追加 `MotorState` + 解析函数**

```python
@dataclass(frozen=True)
class MotorState:
    motor_id: int
    err_code: int
    pos: float      # rad
    vel: float      # rad/s
    tau: float      # N·m
    t_mos: int      # °C
    t_rotor: int    # °C


# 错误码人类可读
ERR_NAMES = {
    0: "Disable",
    1: "Enable",
    8: "Overvoltage",
    9: "Undervoltage",
    0xA: "Overcurrent",
    0xB: "MOS 过温",
    0xC: "电机过温",
    0xD: "通讯丢失",
    0xE: "过载",
}


def parse_mit_feedback(data: bytes, p_max: float, v_max: float, t_max: float) -> MotorState:
    """解析 MIT 模式反馈帧 (CAN ID = master_id, DLC = 8)。"""
    if len(data) != 8:
        raise ValueError(f"MIT 反馈帧应为 8 字节, 实际 {len(data)}")

    motor_id = data[0] & 0x0F
    err_code = (data[0] >> 4) & 0x0F
    pos_i = (data[1] << 8) | data[2]
    vel_i = (data[3] << 4) | (data[4] >> 4)
    tau_i = ((data[4] & 0x0F) << 8) | data[5]
    t_mos = data[6]
    t_rotor = data[7]

    return MotorState(
        motor_id=motor_id,
        err_code=err_code,
        pos=uint_to_float(pos_i, -p_max, p_max, 16),
        vel=uint_to_float(vel_i, -v_max, v_max, 12),
        tau=uint_to_float(tau_i, -t_max, t_max, 12),
        t_mos=t_mos,
        t_rotor=t_rotor,
    )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd damiao && uv run pytest tests/test_protocol.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add damiao/device.py damiao/tests/test_protocol.py
git commit -m "Add DM v4 MIT feedback frame parser"
```

---

## Task 5: device.py — 控制命令帧 (enable/disable/zero/clear)

**背景:** DM v4 特殊控制命令均用 `motor_id` 作为 CAN ID，8 字节填 `FF×7 + <op_byte>`:

| 命令 | op_byte |
|------|---------|
| enable       | 0xFC |
| disable      | 0xFD |
| set_zero     | 0xFE |
| clear_error  | 0xFB |

- [ ] **Step 1: 追加失败测试**

追加到 `tests/test_protocol.py`:

```python
from device import CMD_ENABLE, CMD_DISABLE, CMD_SET_ZERO, CMD_CLEAR_ERROR


def test_cmd_enable_bytes():
    assert CMD_ENABLE == bytes([0xFF]*7 + [0xFC])


def test_cmd_disable_bytes():
    assert CMD_DISABLE == bytes([0xFF]*7 + [0xFD])


def test_cmd_set_zero_bytes():
    assert CMD_SET_ZERO == bytes([0xFF]*7 + [0xFE])


def test_cmd_clear_error_bytes():
    assert CMD_CLEAR_ERROR == bytes([0xFF]*7 + [0xFB])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd damiao && uv run pytest tests/test_protocol.py::test_cmd_enable_bytes -v
```

Expected: `ImportError`.

- [ ] **Step 3: 在 `device.py` 追加控制命令常量**

```python
# --- MIT 特殊控制命令 (CAN ID = motor_id, DLC = 8) ---

CMD_ENABLE      = bytes([0xFF]*7 + [0xFC])
CMD_DISABLE     = bytes([0xFF]*7 + [0xFD])
CMD_SET_ZERO    = bytes([0xFF]*7 + [0xFE])
CMD_CLEAR_ERROR = bytes([0xFF]*7 + [0xFB])
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd damiao && uv run pytest tests/test_protocol.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add damiao/device.py damiao/tests/test_protocol.py
git commit -m "Add DM v4 enable/disable/zero/clear command constants"
```

---

## Task 6: device.py — Servo 模式帧 + 参数读写帧

**背景:** DM v4 Servo 模式 CAN ID 偏移 + 纯二进制 float32:

| 模式 | CAN ID | Payload |
|------|--------|---------|
| MIT | `motor_id` | 8B 位域 |
| POS_VEL | `0x100 + motor_id` | pos(float32 LE) + vel(float32 LE), 8B |
| SPEED | `0x200 + motor_id` | vel(float32 LE), 4B |

**参数读写:** CAN ID `0x7FF`, 8 字节:
- byte 0-1: motor_id (little-endian, 16-bit, 高字节当前总为 0)
- byte 2: 命令字 (0x33=读, 0x55=写, 0xAA=保存到 Flash)
- byte 3: 寄存器 ID (reg_id)
- byte 4-7: float32 LE 值 (读时 0x00×4)

**Files:**
- Modify: `damiao/device.py`
- Modify: `damiao/tests/test_protocol.py`

- [ ] **Step 1: 追加失败测试**

追加到 `tests/test_protocol.py`:

```python
import struct
from device import (
    servo_pos_frame, servo_speed_frame,
    param_read_frame, param_write_frame, param_save_frame,
)


def test_servo_pos_frame():
    can_id, data = servo_pos_frame(motor_id=0x01, pos=1.5, vel=2.0)
    assert can_id == 0x101
    expected = struct.pack("<ff", 1.5, 2.0)
    assert data == expected


def test_servo_speed_frame():
    can_id, data = servo_speed_frame(motor_id=0x02, vel=3.14)
    assert can_id == 0x202
    assert data == struct.pack("<f", 3.14)


def test_param_read_frame():
    can_id, data = param_read_frame(motor_id=0x01, reg_id=0x07)  # 0x07 = PMAX
    assert can_id == 0x7FF
    assert data[0] == 0x01  # motor_id lo
    assert data[1] == 0x00  # motor_id hi
    assert data[2] == 0x33  # 读
    assert data[3] == 0x07
    assert data[4:8] == bytes(4)


def test_param_write_frame_float():
    can_id, data = param_write_frame(motor_id=0x01, reg_id=0x07, value=12.5)
    assert can_id == 0x7FF
    assert data[2] == 0x55  # 写
    assert data[3] == 0x07
    assert data[4:8] == struct.pack("<f", 12.5)


def test_param_save_frame():
    can_id, data = param_save_frame(motor_id=0x01)
    assert can_id == 0x7FF
    assert data[2] == 0xAA  # 保存
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd damiao && uv run pytest tests/test_protocol.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: 在 `device.py` 追加 Servo + 参数帧**

```python
import struct as _struct

# --- Servo 模式 (POS_VEL / SPEED) ---

def servo_pos_frame(motor_id: int, pos: float, vel: float) -> tuple[int, bytes]:
    """Servo 位置+前馈速度模式帧。CAN ID = 0x100 + motor_id, DLC = 8。"""
    return 0x100 + motor_id, _struct.pack("<ff", pos, vel)


def servo_speed_frame(motor_id: int, vel: float) -> tuple[int, bytes]:
    """Servo 速度模式帧。CAN ID = 0x200 + motor_id, DLC = 4。"""
    return 0x200 + motor_id, _struct.pack("<f", vel)


# --- 参数寄存器读写 (CAN ID = 0x7FF) ---

PARAM_READ  = 0x33
PARAM_WRITE = 0x55
PARAM_SAVE  = 0xAA


def param_read_frame(motor_id: int, reg_id: int) -> tuple[int, bytes]:
    data = bytes([motor_id & 0xFF, (motor_id >> 8) & 0xFF, PARAM_READ, reg_id, 0, 0, 0, 0])
    return 0x7FF, data


def param_write_frame(motor_id: int, reg_id: int, value: float) -> tuple[int, bytes]:
    data = bytes([motor_id & 0xFF, (motor_id >> 8) & 0xFF, PARAM_WRITE, reg_id]) + _struct.pack("<f", value)
    return 0x7FF, data


def param_save_frame(motor_id: int) -> tuple[int, bytes]:
    data = bytes([motor_id & 0xFF, (motor_id >> 8) & 0xFF, PARAM_SAVE, 0, 0, 0, 0, 0])
    return 0x7FF, data
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd damiao && uv run pytest tests/test_protocol.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add damiao/device.py damiao/tests/test_protocol.py
git commit -m "Add DM v4 servo mode and parameter register frames"
```

---

## Task 7: device.py — DMMotor 类 + 总线打开 + 启停纪律

**背景:** 最后组装上下文管理器。测试用 python-can 的 `interface='virtual'` 虚拟总线，不依赖真硬件。

**Files:**
- Modify: `damiao/device.py`
- Create: `damiao/tests/test_motor.py`

- [ ] **Step 1: 写失败测试 `tests/test_motor.py`**

```python
"""DMMotor 类测试 (使用 python-can virtual bus, 无物理 CAN)。"""
import pytest
import can
from device import DMMotor, SAFE_DEFAULTS, CMD_ENABLE, CMD_DISABLE


@pytest.fixture
def virtual_bus():
    bus = can.Bus(interface="virtual", channel="test", receive_own_messages=False)
    yield bus
    bus.shutdown()


@pytest.fixture
def listener_bus():
    bus = can.Bus(interface="virtual", channel="test", receive_own_messages=False)
    yield bus
    bus.shutdown()


def test_enable_sends_correct_frame(virtual_bus, listener_bus):
    motor = DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                    auto_enable=False)
    motor.enable()
    msg = listener_bus.recv(timeout=1.0)
    assert msg is not None
    assert msg.arbitration_id == 0x01
    assert msg.data == CMD_ENABLE


def test_disable_sends_correct_frame(virtual_bus, listener_bus):
    motor = DMMotor(virtual_bus, motor_id=0x02, master_id=0x12,
                    auto_enable=False)
    motor.disable()
    msg = listener_bus.recv(timeout=1.0)
    assert msg is not None
    assert msg.arbitration_id == 0x02
    assert msg.data == CMD_DISABLE


def test_mit_cmd_clamps_to_safety(virtual_bus, listener_bus):
    motor = DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                    auto_enable=False, safety=SAFE_DEFAULTS)
    # 请求 tau=10, 但 SAFE_DEFAULTS.tau=1.0, 应该被钳制
    motor.mit_cmd(pos=0, vel=0, kp=0, kd=0, tau=10.0)
    msg = listener_bus.recv(timeout=1.0)
    assert msg is not None
    # tau 字段 (最后 12 bit) 应 ≤ 钳制后的最大值 (tau=1.0, t_max=7.0)
    # tau_int = (1.0 - (-7)) * 4095 / 14 = 2340 = 0x924
    tau_int = ((msg.data[6] & 0x0F) << 8) | msg.data[7]
    assert tau_int == 0x924


def test_context_manager_disables_on_exit(virtual_bus, listener_bus):
    with DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                 auto_enable=True, ping_on_enter=False) as motor:
        pass
    # 退出后应收到 disable 帧 (最后一条)
    msgs = []
    while True:
        m = listener_bus.recv(timeout=0.1)
        if m is None:
            break
        msgs.append(m)
    assert any(m.data == CMD_DISABLE for m in msgs)


def test_context_manager_disables_on_exception(virtual_bus, listener_bus):
    with pytest.raises(RuntimeError):
        with DMMotor(virtual_bus, motor_id=0x01, master_id=0x11,
                     auto_enable=True, ping_on_enter=False):
            raise RuntimeError("test crash")
    msgs = []
    while True:
        m = listener_bus.recv(timeout=0.1)
        if m is None:
            break
        msgs.append(m)
    assert any(m.data == CMD_DISABLE for m in msgs)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd damiao && uv run pytest tests/test_motor.py -v
```

Expected: `ImportError: cannot import name 'DMMotor'`.

- [ ] **Step 3: 在 `device.py` 追加 `DMMotor` 类 + `open_bus` 辅助**

```python
# --- 总线打开 (socketcan 优先, slcan 降级) ---

def open_bus(channel: str = "can0",
             bitrate: int = 1_000_000,
             slcan_fallback: str | None = "/dev/ttyACM0"):
    """优先尝试 SocketCAN (candleLight 固件), 失败且 slcan_fallback 非 None 时
    回退到 slcan (normaldotcom slcan 固件)。

    返回 can.BusABC 实例, 调用方负责 shutdown()。
    """
    import can

    try:
        return can.Bus(interface="socketcan", channel=channel, bitrate=bitrate)
    except (OSError, can.CanInitializationError) as e:
        if slcan_fallback is None:
            raise
        print(f"[info] SocketCAN 打开失败 ({e}), 尝试 slcan {slcan_fallback}...",
              file=sys.stderr)
        return can.Bus(interface="slcan", channel=slcan_fallback, bitrate=bitrate)


# --- DMMotor 类 ---

class DMMotor:
    """达妙电机 DM v4 上下文管理器。

    进入: (ping_on_enter) 发一次 enable 并等待反馈确认 → auto_enable 则持续
    退出: 无条件发 disable (最多重试一次, 即使 bus 异常也尽力而为)
    """

    def __init__(self, bus, motor_id: int = 0x01, master_id: int = 0x11,
                 p_max: float = 12.5, v_max: float = 30.0, t_max: float = 7.0,
                 safety: SafetyLimits = SAFE_DEFAULTS,
                 auto_enable: bool = True,
                 ping_on_enter: bool = True):
        self.bus = bus
        self.motor_id = motor_id
        self.master_id = master_id
        self.p_max = p_max
        self.v_max = v_max
        self.t_max = t_max
        self.safety = safety
        self.auto_enable = auto_enable
        self.ping_on_enter = ping_on_enter

    # --- 原始帧发送 ---

    def _send(self, can_id: int, data: bytes, is_extended: bool = False):
        import can
        msg = can.Message(arbitration_id=can_id, data=data,
                          is_extended_id=is_extended)
        self.bus.send(msg)

    # --- 控制命令 ---

    def enable(self):       self._send(self.motor_id, CMD_ENABLE)
    def disable(self):      self._send(self.motor_id, CMD_DISABLE)
    def set_zero(self):     self._send(self.motor_id, CMD_SET_ZERO)
    def clear_error(self):  self._send(self.motor_id, CMD_CLEAR_ERROR)

    def mit_cmd(self, pos: float, vel: float, kp: float, kd: float, tau: float):
        pos = self.safety.clamp_pos(pos)
        vel = self.safety.clamp_vel(vel)
        kp  = self.safety.clamp_kp(kp)
        kd  = self.safety.clamp_kd(kd)
        tau = self.safety.clamp_tau(tau)
        data = pack_mit_cmd(pos, vel, kp, kd, tau,
                            self.p_max, self.v_max, self.t_max)
        self._send(self.motor_id, data)

    def servo_pos(self, pos: float, vel: float):
        pos = self.safety.clamp_pos(pos)
        vel = self.safety.clamp_vel(vel)
        can_id, data = servo_pos_frame(self.motor_id, pos, vel)
        self._send(can_id, data)

    def servo_speed(self, vel: float):
        vel = self.safety.clamp_vel(vel)
        can_id, data = servo_speed_frame(self.motor_id, vel)
        self._send(can_id, data)

    # --- 反馈读取 ---

    def read_state(self, timeout: float = 0.05) -> MotorState | None:
        """收一帧反馈 (CAN ID = master_id), 超时返回 None。"""
        import can
        deadline_end = False
        while not deadline_end:
            msg = self.bus.recv(timeout=timeout)
            if msg is None:
                return None
            if msg.arbitration_id == self.master_id and len(msg.data) == 8:
                return parse_mit_feedback(msg.data, self.p_max, self.v_max, self.t_max)
            # 其他帧: 继续等同一窗口内是否还有目标帧 (超时即退出)
            deadline_end = True
        return None

    # --- 参数读写 ---

    def read_param(self, reg_id: int, timeout: float = 0.2) -> float | None:
        can_id, data = param_read_frame(self.motor_id, reg_id)
        self._send(can_id, data)
        # 响应也在 0x7FF, byte 2 = 0x33, byte 3 = reg_id, byte 4-7 = float32
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=deadline - time.monotonic())
            if msg is None:
                return None
            if msg.arbitration_id == 0x7FF and len(msg.data) == 8 \
               and msg.data[2] == PARAM_READ and msg.data[3] == reg_id:
                return _struct.unpack("<f", msg.data[4:8])[0]
        return None

    def write_param(self, reg_id: int, value: float):
        can_id, data = param_write_frame(self.motor_id, reg_id, value)
        self._send(can_id, data)

    def save_to_flash(self):
        can_id, data = param_save_frame(self.motor_id)
        self._send(can_id, data)

    # --- 上下文管理 ---

    def __enter__(self):
        try:
            self.clear_error()
            if self.ping_on_enter:
                state = self.read_state(timeout=0.2)
                if state is None:
                    raise RuntimeError(
                        f"电机 0x{self.motor_id:02X} 无反馈 (master_id=0x{self.master_id:02X}); "
                        "检查 CAN 接线 / bitrate / motor_id / master_id"
                    )
            if self.auto_enable:
                self.enable()
        except Exception:
            self._safe_disable()
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._safe_disable()
        return False

    def _safe_disable(self):
        for _ in range(2):  # 最多重试一次
            try:
                self.disable()
                return
            except Exception:
                continue
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd damiao && uv run pytest tests/test_motor.py -v
```

Expected: 全部 PASS。再跑一次全量 `uv run pytest -v` 确认之前的测试没破坏。

- [ ] **Step 5: Commit**

```bash
git add damiao/device.py damiao/tests/test_motor.py
git commit -m "Add DMMotor context manager with safe enable/disable lifecycle"
```

---

## Task 8: setup.sh — udev + systemd unit 安装

**Files:**
- Create: `damiao/setup.sh`

- [ ] **Step 1: 写 `damiao/setup.sh`**

```bash
#!/usr/bin/env bash
# 达妙电机调试一次性环境安装: udev 规则 + can0 systemd unit。
# 需要 sudo; 幂等 (已存在则跳过)。
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "请用 sudo 运行: sudo bash setup.sh" >&2
    exit 1
fi

UDEV_RULE=/etc/udev/rules.d/99-canable.rules
SERVICE=/etc/systemd/system/can0-up.service

# --- udev 规则 ---
if [[ -f "$UDEV_RULE" ]]; then
    echo "[skip] $UDEV_RULE 已存在"
else
    cat > "$UDEV_RULE" <<'EOF'
# Makerbase CANable 2.0 (normaldotcom fork)
# slcan 固件
SUBSYSTEM=="usb", ATTR{idVendor}=="16d0", ATTR{idProduct}=="117e", MODE="0666"
# candleLight 固件 (gs_usb)
SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666"
EOF
    echo "[ok]   写入 $UDEV_RULE"
fi

# --- systemd unit ---
if [[ -f "$SERVICE" ]]; then
    echo "[skip] $SERVICE 已存在"
else
    cat > "$SERVICE" <<'EOF'
[Unit]
Description=Bring up can0 at 1 Mbps (DaMiao motor bus)
BindsTo=sys-subsystem-net-devices-can0.device
After=sys-subsystem-net-devices-can0.device

[Service]
Type=oneshot
ExecStart=/usr/sbin/ip link set can0 up type can bitrate 1000000
ExecStop=/usr/sbin/ip link set can0 down
RemainAfterExit=yes

[Install]
WantedBy=sys-subsystem-net-devices-can0.device
EOF
    echo "[ok]   写入 $SERVICE"
fi

# --- 生效 ---
echo "[..]   重载 udev 与 systemd"
udevadm control --reload-rules
udevadm trigger
systemctl daemon-reload
systemctl enable can0-up.service || true

echo ""
echo "完成。下一步:"
echo "  1. 确认 CANable 2.0 已烧 candleLight 固件 (VID 1d50:606f)"
echo "     如仍是 slcan (16d0:117e), 先跑 uv run fw_update.py"
echo "  2. 插 USB, 应自动触发 can0 起来"
echo "  3. 检查: ip -details link show can0"
```

- [ ] **Step 2: chmod +x**

```bash
chmod +x damiao/setup.sh
```

- [ ] **Step 3: 语法自检 (不执行)**

```bash
bash -n damiao/setup.sh
```

Expected: 无输出 (语法正确)。

- [ ] **Step 4: 人工验收 (有 sudo 的 Linux 主机上)**

```bash
sudo bash damiao/setup.sh
ls -l /etc/udev/rules.d/99-canable.rules /etc/systemd/system/can0-up.service
```

Expected: 两个文件存在, `systemctl status can0-up.service` 显示 enabled。再跑一遍应全打 `[skip]`。

- [ ] **Step 5: Commit**

```bash
git add damiao/setup.sh
git commit -m "Add setup.sh for CANable udev rules and can0 systemd unit"
```

---

## Task 9: detect.py — USB + can0 + 电机探活

**Files:**
- Create: `damiao/detect.py`

- [ ] **Step 1: 写 `damiao/detect.py`**

```python
"""检测 CANable 2.0 USB 设备、can0 链路状态、探活达妙电机。

显示:
- USB 层 (lsusb): 找 16d0:117e (slcan) 或 1d50:606f (candleLight)
- 网络层: can0 接口是否 UP, bitrate
- 协议层: 对 motor_id 发一次控制帧, 等反馈
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

from device import DMMotor, open_bus

CANABLE_USB_IDS = {
    "16d0:117e": "slcan (normaldotcom fork)",
    "1d50:606f": "candleLight (gs_usb)",
}


def detect_usb() -> list[dict]:
    if sys.platform != "linux":
        print(f"  不支持的平台: {sys.platform}")
        return []
    result = subprocess.run(["lsusb"], capture_output=True, text=True)
    devices = []
    for line in result.stdout.splitlines():
        m = re.search(r"ID ([0-9a-f]{4}:[0-9a-f]{4})", line)
        if not m:
            continue
        vid_pid = m.group(1)
        if vid_pid in CANABLE_USB_IDS:
            devices.append({
                "id": vid_pid,
                "firmware": CANABLE_USB_IDS[vid_pid],
                "header": line.strip(),
            })
    return devices


def detect_can0() -> dict | None:
    """读取 can0 接口详情 (ip -details link show can0)。未找到返回 None。"""
    result = subprocess.run(
        ["ip", "-details", "link", "show", "can0"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    info = {"raw": result.stdout.strip()}
    m = re.search(r"state (\w+)", result.stdout)
    if m:
        info["state"] = m.group(1)
    m = re.search(r"bitrate (\d+)", result.stdout)
    if m:
        info["bitrate"] = int(m.group(1))
    return info


def ping_motor(motor_id: int, master_id: int) -> tuple[bool, str]:
    """对电机发 clear_error 并等反馈。返回 (ok, 说明)。"""
    try:
        bus = open_bus(channel="can0", bitrate=1_000_000)
    except Exception as e:
        return False, f"打开 CAN 总线失败: {e}"
    try:
        motor = DMMotor(bus, motor_id=motor_id, master_id=master_id, auto_enable=False)
        motor.clear_error()
        state = motor.read_state(timeout=0.3)
        if state is None:
            return False, f"未收到 master_id=0x{master_id:02X} 的反馈"
        return True, (f"pos={state.pos:+.3f} rad  vel={state.vel:+.3f} rad/s  "
                      f"tau={state.tau:+.3f} N·m  err={state.err_code}  "
                      f"T_mos={state.t_mos}°C  T_rotor={state.t_rotor}°C")
    finally:
        bus.shutdown()


def main():
    p = argparse.ArgumentParser(description="检测 CANable 2.0 + can0 + 达妙电机")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)
    p.add_argument("--skip-motor", action="store_true", help="只做 USB + can0 检测")
    args = p.parse_args()

    print("=== USB 设备检测 (CANable 2.0) ===")
    usb = detect_usb()
    if not usb:
        print("  未检测到 CANable 2.0 USB 设备")
    for d in usb:
        print(f"  {d['header']}")
        print(f"    固件: {d['firmware']}")

    print("\n=== can0 链路 ===")
    c = detect_can0()
    if c is None:
        print("  can0 不存在")
        print("  → 如已烧 candleLight 固件, 跑 setup.sh 装 systemd unit")
        print("  → 如仍是 slcan 固件, 跑 fw_update.py 烧 candleLight")
    else:
        print(f"  state: {c.get('state', '?')}")
        if "bitrate" in c:
            print(f"  bitrate: {c['bitrate']}")

    if args.skip_motor:
        return
    if c is None or c.get("state") != "UP":
        print("\n=== 电机探活 === (跳过, can0 未就绪)")
        return

    print(f"\n=== 电机探活 (motor_id=0x{args.motor_id:02X}, "
          f"master_id=0x{args.master_id:02X}) ===")
    ok, msg = ping_motor(args.motor_id, args.master_id)
    print(f"  {'[OK]' if ok else '[FAIL]'} {msg}")
    if not ok:
        print("  常见原因: motor_id/master_id 不匹配, bitrate 不是 1 Mbps, "
              "CAN_H/L 反接, 电源未接")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 人工验收（需硬件）**

```bash
cd damiao
uv run detect.py --skip-motor   # 只看 USB + can0
uv run detect.py                # 完整流程
```

Expected:
- USB 段: 打印 CANable 2.0 信息（slcan 或 candleLight）
- can0 段: 若已烧 candleLight 且 setup.sh 跑过，显示 UP + bitrate 1000000
- 电机探活: `[OK]` + 实时状态行

- [ ] **Step 3: Commit**

```bash
git add damiao/detect.py
git commit -m "Add detect.py: USB + can0 + motor probe"
```

---

## Task 10: fw_update.py — CANable 2.0 DFU 烧录

**Files:**
- Create: `damiao/fw_update.py`

- [ ] **Step 1: 写 `damiao/fw_update.py`**

```python
"""Makerbase CANable 2.0 固件烧录: slcan → candleLight。

流程:
  1. 读当前 USB ID (lsusb) 判断固件
  2. 提示用户: 短接 BOOT 跳线 (或按住 BOOT 按钮) 后重插 USB 进 DFU
  3. 轮询 0483:df11 DFU 设备出现 (30s)
  4. 调用 dfu-util 烧录 .bin
  5. 轮询新 USB ID 出现 (10s), 提示下一步

候选固件来源:
  - 官方:   https://github.com/candle-usb/candleLight_fw  (make CANABLE2=1)
  - Fork:   https://github.com/normaldotcom/candleLight_fw/releases
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time

DFU_ID = "0483:df11"
SLCAN_ID = "16d0:117e"
CANDLELIGHT_ID = "1d50:606f"


def lsusb_ids() -> list[str]:
    result = subprocess.run(["lsusb"], capture_output=True, text=True, check=True)
    return re.findall(r"ID ([0-9a-f]{4}:[0-9a-f]{4})", result.stdout)


def wait_for_usb_id(target: str, timeout: float, label: str) -> bool:
    deadline = time.monotonic() + timeout
    last_report = 0.0
    while time.monotonic() < deadline:
        if target in lsusb_ids():
            print(f"[ok]   检测到 {label} ({target})")
            return True
        now = time.monotonic()
        if now - last_report >= 1.0:
            remain = deadline - now
            print(f"  等待 {label} ({target})... 剩 {remain:.0f}s", end="\r")
            last_report = now
        time.sleep(0.2)
    print()
    return False


def main():
    p = argparse.ArgumentParser(description="CANable 2.0 DFU 烧录")
    p.add_argument("bin", nargs="?", help="candleLight_fw.bin 路径 (省略则只 --info)")
    p.add_argument("--info", action="store_true", help="只查当前状态")
    p.add_argument("-y", "--yes", action="store_true", help="跳过交互式确认")
    args = p.parse_args()

    print("=== 当前 USB 设备 ===")
    ids = lsusb_ids()
    if SLCAN_ID in ids:
        print(f"  当前: slcan 固件 ({SLCAN_ID})")
    elif CANDLELIGHT_ID in ids:
        print(f"  当前: candleLight 固件 ({CANDLELIGHT_ID}) — 已是目标固件")
    elif DFU_ID in ids:
        print(f"  当前: DFU 模式 ({DFU_ID})")
    else:
        print("  未检测到 CANable 2.0")

    if args.info or not args.bin:
        return

    if not shutil.which("dfu-util"):
        print("\n[错误] 未安装 dfu-util. 请 sudo apt install dfu-util", file=sys.stderr)
        sys.exit(1)

    print()
    print("=== 烧录准备 ===")
    print(f"  目标固件: {args.bin}")
    print("  操作步骤:")
    print("    1. 拔掉 CANable 2.0 USB")
    print("    2. 短接板上 BOOT 跳线 (或按住 BOOT 按钮)")
    print("    3. 插回 USB (保持 BOOT 短接/按住到插入为止)")
    print("    4. 回车继续")
    if not args.yes:
        input("  回车后开始等待 DFU 设备...")

    if not wait_for_usb_id(DFU_ID, timeout=30.0, label="DFU 设备"):
        print("[错误] 30s 内未检测到 DFU 设备. 检查 BOOT 跳线是否短接到位.",
              file=sys.stderr)
        sys.exit(1)

    print("\n=== dfu-util 烧录 ===")
    cmd = ["dfu-util", "-a", "0", "-s", "0x08000000:leave", "-D", args.bin]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[错误] dfu-util 退出码 {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    print("\n=== 等待固件重新枚举 ===")
    print("  现在可以松开 BOOT 跳线 (如之前用了按钮式, 按一次 RESET)")
    if wait_for_usb_id(CANDLELIGHT_ID, timeout=10.0, label="candleLight"):
        print("\n[完成] 固件烧录成功. 下一步:")
        print("  sudo bash setup.sh    # 若还没装 systemd unit")
        print("  ip -details link show can0")
        print("  uv run detect.py")
    else:
        print("[警告] 10s 内未检测到 candleLight. 手动拔插一次再查 lsusb.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: `--info` 验收（无硬件也能跑）**

```bash
cd damiao && uv run fw_update.py --info
```

Expected: 打印当前 USB 状态。

- [ ] **Step 3: 人工验收（有硬件 + 已下载 `.bin`）**

```bash
# 先下载 candleLight_fw.bin
sudo apt install dfu-util
uv run fw_update.py /path/to/candleLight_fw.bin
```

按提示 BOOT 跳线，完成烧录，最终 `lsusb` 看到 `1d50:606f`。

- [ ] **Step 4: Commit**

```bash
git add damiao/fw_update.py
git commit -m "Add fw_update.py: DFU flash CANable 2.0 slcan to candleLight"
```

---

## Task 11: enable.py — 使能/读状态/失能

**Files:**
- Create: `damiao/enable.py`

- [ ] **Step 1: 写 `damiao/enable.py`**

```python
"""达妙电机使能/失能/状态读取。

默认单次使能 → 读 3 帧状态 → 失能。
--hold N 保持使能 N 秒, 每 100ms 打印一帧状态 (测反馈连续性)。
"""
from __future__ import annotations

import argparse
import time

from device import DMMotor, open_bus, ERR_NAMES


def main():
    p = argparse.ArgumentParser(description="达妙电机使能/读状态/失能")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)
    p.add_argument("--hold", type=float, default=0.0,
                   help="保持使能秒数 (默认 0 = 单次使能后立即失能)")
    p.add_argument("--p-max", type=float, default=12.5)
    p.add_argument("--v-max", type=float, default=30.0)
    p.add_argument("--t-max", type=float, default=7.0)
    args = p.parse_args()

    bus = open_bus(channel="can0", bitrate=1_000_000)
    try:
        with DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                     p_max=args.p_max, v_max=args.v_max, t_max=args.t_max,
                     auto_enable=True) as motor:
            print(f"[ok] 已使能 motor_id=0x{args.motor_id:02X}")
            end = time.monotonic() + max(args.hold, 0.3)
            while time.monotonic() < end:
                state = motor.read_state(timeout=0.15)
                if state is None:
                    print("  (无反馈帧)")
                else:
                    err_name = ERR_NAMES.get(state.err_code, f"未知(0x{state.err_code:X})")
                    print(f"  pos={state.pos:+.4f} rad  vel={state.vel:+.4f} rad/s  "
                          f"tau={state.tau:+.4f} N·m  err={err_name}  "
                          f"T_mos={state.t_mos}°C  T_rotor={state.t_rotor}°C")
                time.sleep(0.1)
    finally:
        bus.shutdown()
    print("[ok] 已失能")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 人工验收**

```bash
cd damiao
uv run enable.py               # 瞬时: 使能→读几帧→失能
uv run enable.py --hold 5      # 保持 5 秒, 期间可手指拨动轴, 观察 pos 变化
```

Expected:
- `[ok] 已使能` → 持续打印 pos/vel/tau/err=Enable → `[ok] 已失能`
- 手拨电机轴应看到 pos 实时变化

- [ ] **Step 3: Commit**

```bash
git add damiao/enable.py
git commit -m "Add enable.py: motor enable/state/disable smoke test"
```

---

## Task 12: mit.py — MIT 模式点控 + 录波 + --live

**Files:**
- Create: `damiao/mit.py`

- [ ] **Step 1: 写 `damiao/mit.py`**

```python
"""MIT 模式点控测试。

profiles:
  step  — 0 → target 阶跃
  sine  — pos = amp * sin(2π f t), 默认 amp=0.5 rad, f=0.5 Hz
  hold  — 保持初始位置, 观察扰动响应 (手指拨动轴)

安全默认 (SAFE_DEFAULTS): tau≤1 N·m, vel≤5 rad/s, pos≤±π, kp≤20, kd≤1
--unsafe 放开到硬件上限 (p_max/v_max/t_max/500/5)

输出:
  out/mit_<profile>_<ts>.csv   t, pos, vel, tau, pos_cmd, vel_cmd, tau_cmd, err
  out/mit_<profile>_<ts>.png   4 子图 (pos, vel, tau vs 时间, err 码)
  --live 弹 matplotlib 实时窗, 关窗后同时落 CSV+PNG; 无 DISPLAY 自动降级
"""
from __future__ import annotations

import argparse
import csv
import math
import time
from dataclasses import dataclass, field

import numpy as np

from device import (
    DMMotor, open_bus, output_dir, timestamped,
    SafetyLimits, SAFE_DEFAULTS, has_display, ERR_NAMES,
)


@dataclass
class Sample:
    t: float
    pos: float
    vel: float
    tau: float
    pos_cmd: float
    vel_cmd: float
    tau_cmd: float
    err: int


@dataclass
class Trace:
    samples: list[Sample] = field(default_factory=list)

    def add(self, s: Sample): self.samples.append(s)

    def arrays(self):
        t = np.array([s.t for s in self.samples])
        return {
            "t": t,
            "pos": np.array([s.pos for s in self.samples]),
            "vel": np.array([s.vel for s in self.samples]),
            "tau": np.array([s.tau for s in self.samples]),
            "pos_cmd": np.array([s.pos_cmd for s in self.samples]),
            "vel_cmd": np.array([s.vel_cmd for s in self.samples]),
            "tau_cmd": np.array([s.tau_cmd for s in self.samples]),
            "err": np.array([s.err for s in self.samples]),
        }


def profile_step(t: float, pos0: float, target: float, t_step: float = 0.5):
    return (pos0 if t < t_step else target), 0.0, 0.0


def profile_sine(t: float, pos0: float, amp: float, freq: float):
    pos = pos0 + amp * math.sin(2 * math.pi * freq * t)
    vel = amp * 2 * math.pi * freq * math.cos(2 * math.pi * freq * t)
    return pos, vel, 0.0


def profile_hold(t: float, pos0: float):
    return pos0, 0.0, 0.0


def run_control_loop(motor: DMMotor, profile_fn, duration: float,
                     kp: float, kd: float, rate_hz: float = 200.0,
                     live_callback=None) -> Trace:
    """控制循环: rate_hz 发命令, 每次循环读一帧反馈。"""
    trace = Trace()
    dt = 1.0 / rate_hz
    t0 = time.monotonic()
    state0 = motor.read_state(timeout=0.2)
    pos0 = state0.pos if state0 else 0.0
    print(f"  起始 pos = {pos0:+.4f} rad")

    next_t = t0
    while True:
        now = time.monotonic()
        t_rel = now - t0
        if t_rel > duration:
            break
        pos_cmd, vel_cmd, tau_cmd = profile_fn(t_rel, pos0)
        motor.mit_cmd(pos=pos_cmd, vel=vel_cmd, kp=kp, kd=kd, tau=tau_cmd)
        state = motor.read_state(timeout=dt * 0.5)
        if state is not None:
            s = Sample(
                t=t_rel, pos=state.pos, vel=state.vel, tau=state.tau,
                pos_cmd=pos_cmd, vel_cmd=vel_cmd, tau_cmd=tau_cmd,
                err=state.err_code,
            )
            trace.add(s)
            if live_callback is not None:
                live_callback(s)
        next_t += dt
        sleep_for = next_t - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
    return trace


def save_csv(trace: Trace, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "pos", "vel", "tau", "pos_cmd", "vel_cmd", "tau_cmd", "err"])
        for s in trace.samples:
            w.writerow([f"{s.t:.4f}", f"{s.pos:.6f}", f"{s.vel:.6f}", f"{s.tau:.6f}",
                        f"{s.pos_cmd:.6f}", f"{s.vel_cmd:.6f}", f"{s.tau_cmd:.6f}", s.err])


def save_png(trace: Trace, path, title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    a = trace.arrays()
    fig, axes = plt.subplots(4, 1, figsize=(10, 10), sharex=True)
    axes[0].plot(a["t"], a["pos_cmd"], label="cmd", linestyle="--")
    axes[0].plot(a["t"], a["pos"], label="actual")
    axes[0].set_ylabel("pos (rad)"); axes[0].legend(); axes[0].grid()
    axes[1].plot(a["t"], a["vel_cmd"], label="cmd", linestyle="--")
    axes[1].plot(a["t"], a["vel"], label="actual")
    axes[1].set_ylabel("vel (rad/s)"); axes[1].legend(); axes[1].grid()
    axes[2].plot(a["t"], a["tau_cmd"], label="cmd", linestyle="--")
    axes[2].plot(a["t"], a["tau"], label="actual")
    axes[2].set_ylabel("tau (N·m)"); axes[2].legend(); axes[2].grid()
    axes[3].step(a["t"], a["err"], where="post")
    axes[3].set_ylabel("err code"); axes[3].set_xlabel("t (s)"); axes[3].grid()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run_live(profile_fn, duration, motor, kp, kd, rate_hz) -> Trace:
    """matplotlib FuncAnimation 实时窗 + 数据落盘。"""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    trace = Trace()
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    lines = {
        "pos_cmd": axes[0].plot([], [], "--", label="cmd")[0],
        "pos":     axes[0].plot([], [], label="actual")[0],
        "vel_cmd": axes[1].plot([], [], "--", label="cmd")[0],
        "vel":     axes[1].plot([], [], label="actual")[0],
        "tau_cmd": axes[2].plot([], [], "--", label="cmd")[0],
        "tau":     axes[2].plot([], [], label="actual")[0],
    }
    for ax, name in zip(axes, ("pos (rad)", "vel (rad/s)", "tau (N·m)")):
        ax.set_ylabel(name); ax.legend(); ax.grid()
    axes[-1].set_xlabel("t (s)")

    stop = {"v": False}

    def on_close(_event):
        stop["v"] = True
    fig.canvas.mpl_connect("close_event", on_close)

    import threading
    def worker():
        run_control_loop(motor, profile_fn, duration, kp, kd, rate_hz,
                         live_callback=trace.add)
        stop["v"] = True

    th = threading.Thread(target=worker, daemon=True)
    th.start()

    def update(_frame):
        a = trace.arrays() if trace.samples else None
        if a is not None:
            for key, line in lines.items():
                line.set_data(a["t"], a[key])
            for ax in axes:
                ax.relim(); ax.autoscale_view()
        if stop["v"]:
            plt.close(fig)
        return list(lines.values())

    _anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    plt.show()
    th.join(timeout=1.0)
    return trace


def main():
    p = argparse.ArgumentParser(description="MIT 模式点控测试")
    p.add_argument("--profile", choices=["step", "sine", "hold"], default="sine")
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--rate-hz", type=float, default=200.0)
    p.add_argument("--kp", type=float, default=10.0)
    p.add_argument("--kd", type=float, default=0.5)
    p.add_argument("--target", type=float, default=0.5, help="step 目标 pos (rad)")
    p.add_argument("--amp", type=float, default=0.5, help="sine 幅值 (rad)")
    p.add_argument("--freq", type=float, default=0.5, help="sine 频率 (Hz)")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)
    p.add_argument("--p-max", type=float, default=12.5)
    p.add_argument("--v-max", type=float, default=30.0)
    p.add_argument("--t-max", type=float, default=7.0)
    p.add_argument("--unsafe", action="store_true",
                   help="放开软限幅到硬件上限")
    p.add_argument("--live", action="store_true",
                   help="弹实时 matplotlib 窗口 (无 DISPLAY 自动降级)")
    args = p.parse_args()

    if args.unsafe:
        safety = SafetyLimits(tau=args.t_max, vel=args.v_max, pos=args.p_max,
                              kp=500.0, kd=5.0)
    else:
        safety = SAFE_DEFAULTS

    kp = safety.clamp_kp(args.kp)
    kd = safety.clamp_kd(args.kd)
    if (kp, kd) != (args.kp, args.kd):
        print(f"[info] kp/kd 被安全限幅钳制: ({args.kp}, {args.kd}) → ({kp}, {kd})")

    def profile_fn(t, pos0):
        if args.profile == "step":  return profile_step(t, pos0, pos0 + args.target)
        if args.profile == "sine":  return profile_sine(t, pos0, args.amp, args.freq)
        return profile_hold(t, pos0)

    use_live = args.live and has_display()
    if args.live and not use_live:
        print("[info] --live 请求但无 DISPLAY, 降级为静态输出")

    bus = open_bus(channel="can0", bitrate=1_000_000)
    try:
        with DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                     p_max=args.p_max, v_max=args.v_max, t_max=args.t_max,
                     safety=safety) as motor:
            if use_live:
                trace = run_live(profile_fn, args.duration, motor, kp, kd, args.rate_hz)
            else:
                trace = run_control_loop(motor, profile_fn, args.duration, kp, kd,
                                         args.rate_hz)
    finally:
        bus.shutdown()

    if not trace.samples:
        print("[warn] 无数据样本, 不落盘")
        return

    out = output_dir()
    csv_name = timestamped(f"mit_{args.profile}", "csv")
    png_name = timestamped(f"mit_{args.profile}", "png")
    csv_path = out / csv_name
    png_path = out / png_name
    save_csv(trace, csv_path)
    save_png(trace, png_path, title=f"MIT {args.profile} kp={kp} kd={kd}")
    print(f"[ok] {csv_path}")
    print(f"[ok] {png_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 人工验收 (无 DISPLAY 路径)**

```bash
cd damiao
uv run mit.py --profile sine --duration 3 --kp 10 --kd 0.5
uv run mit.py --profile step --duration 2 --target 0.3
uv run mit.py --profile hold --duration 3   # 跑的过程手拨电机, 看 tau 跟上
ls out/
```

Expected: `out/mit_<profile>_<ts>.csv` + `.png`，打开 PNG 看位置/速度/扭矩曲线合理。

- [ ] **Step 3: 人工验收 (`--live` 在有 X/Wayland 的桌面)**

```bash
uv run mit.py --profile sine --duration 10 --live
```

Expected: 弹 matplotlib 窗口实时画，关窗后同时落 CSV + PNG。

- [ ] **Step 4: Commit**

```bash
git add damiao/mit.py
git commit -m "Add mit.py: MIT mode step/sine/hold with CSV+PNG and --live"
```

---

## Task 13: servo.py — Servo POS / SPEED 模式

**Files:**
- Create: `damiao/servo.py`

- [ ] **Step 1: 写 `damiao/servo.py`**

```python
"""Servo 模式点控 (POS 或 SPEED)。

注意: 使用前电机需处于 Servo 模式 (通过 params.py 写 CTRL_MODE 寄存器, 或上位机配置)。
MIT 模式下发 Servo 帧电机会忽略。

--mode pos:    发 (pos, vel_feedforward) 到 0x100+motor_id
--mode speed:  发 vel 到 0x200+motor_id
"""
from __future__ import annotations

import argparse
import csv
import time

from device import (
    DMMotor, open_bus, output_dir, timestamped,
    SafetyLimits, SAFE_DEFAULTS, ERR_NAMES,
)


def main():
    p = argparse.ArgumentParser(description="Servo 模式点控")
    p.add_argument("--mode", choices=["pos", "speed"], required=True)
    p.add_argument("--target", type=float, required=True,
                   help="pos 模式: 目标 rad; speed 模式: 目标 rad/s")
    p.add_argument("--vel-ff", type=float, default=0.0,
                   help="pos 模式前馈速度 rad/s")
    p.add_argument("--duration", type=float, default=3.0)
    p.add_argument("--rate-hz", type=float, default=100.0)
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)
    p.add_argument("--p-max", type=float, default=12.5)
    p.add_argument("--v-max", type=float, default=30.0)
    p.add_argument("--t-max", type=float, default=7.0)
    p.add_argument("--unsafe", action="store_true")
    args = p.parse_args()

    safety = (SafetyLimits(tau=args.t_max, vel=args.v_max, pos=args.p_max,
                           kp=500.0, kd=5.0) if args.unsafe else SAFE_DEFAULTS)

    bus = open_bus(channel="can0", bitrate=1_000_000)
    samples = []
    try:
        with DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                     p_max=args.p_max, v_max=args.v_max, t_max=args.t_max,
                     safety=safety) as motor:
            state0 = motor.read_state(timeout=0.2)
            pos0 = state0.pos if state0 else 0.0
            target_pos = pos0 + args.target  # 相对起始位
            print(f"  起始 pos = {pos0:+.4f} rad, 目标 = "
                  f"{target_pos:+.4f} rad" if args.mode == "pos" else
                  f"  目标速度 = {args.target:+.4f} rad/s")

            dt = 1.0 / args.rate_hz
            t0 = time.monotonic()
            next_t = t0
            while True:
                now = time.monotonic()
                t_rel = now - t0
                if t_rel > args.duration:
                    break
                if args.mode == "pos":
                    motor.servo_pos(pos=target_pos, vel=args.vel_ff)
                else:
                    motor.servo_speed(vel=args.target)
                state = motor.read_state(timeout=dt * 0.5)
                if state is not None:
                    samples.append((t_rel, state.pos, state.vel, state.tau, state.err_code))
                next_t += dt
                sleep_for = next_t - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
    finally:
        bus.shutdown()

    if not samples:
        print("[warn] 无反馈样本")
        return

    out = output_dir()
    csv_path = out / timestamped(f"servo_{args.mode}", "csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "pos", "vel", "tau", "err"])
        for s in samples:
            w.writerow([f"{s[0]:.4f}"] + [f"{v:.6f}" if isinstance(v, float) else v for v in s[1:]])
    print(f"[ok] {csv_path}  ({len(samples)} 样本)")
    last = samples[-1]
    print(f"  末态: pos={last[1]:+.4f} vel={last[2]:+.4f} tau={last[3]:+.4f} "
          f"err={ERR_NAMES.get(last[4], '?')}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 人工验收 (前置: 电机在 Servo 模式)**

```bash
cd damiao
# 先把电机切到 Servo (POS) 模式 — 第一次用 params.py 之前可用上位机先切
uv run servo.py --mode pos --target 1.0 --duration 3
uv run servo.py --mode speed --target 2.0 --duration 3
```

Expected: 电机转到 +1 rad 并保持 (或以 2 rad/s 持续转)，CSV 中 pos/vel 与目标吻合。

- [ ] **Step 3: Commit**

```bash
git add damiao/servo.py
git commit -m "Add servo.py: position/speed mode point control with CSV log"
```

---

## Task 14: params.py — 寄存器读写 + 改 ID + 保存

**背景:** DM v4 常用寄存器 ID（官方手册，实现时以最新版为准，这里给最常用的几个）:

| reg_id | 名称 | 类型 | 说明 |
|--------|------|------|------|
| 0x00 | UV_Value | float | 欠压阈值 V |
| 0x01 | KT_Value | float | 扭矩系数 |
| 0x02 | OT_Value | float | 过温阈值 °C |
| 0x03 | OC_Value | float | 过流阈值 A |
| 0x07 | PMAX | float | 位置上限 rad |
| 0x08 | VMAX | float | 速度上限 rad/s |
| 0x09 | TMAX | float | 扭矩上限 N·m |
| 0x0A | I_BW | float | 电流环带宽 |
| 0x10 | CAN_ID | uint(float) | 电机 CAN ID |
| 0x11 | MST_ID | uint(float) | 主机 CAN ID (master_id) |
| 0x12 | TIMEOUT | float | 通讯超时 ms |
| 0x13 | CTRL_MODE | uint(float) | 1=MIT, 2=POS_VEL, 3=SPEED |
| 0x17 | KP_APR | float | 位置环 KP |
| 0x18 | KI_APR | float | 位置环 KI |
| 0x19 | KP_ASR | float | 速度环 KP |
| 0x1A | KI_ASR | float | 速度环 KI |

**Files:**
- Create: `damiao/params.py`

- [ ] **Step 1: 写 `damiao/params.py`**

```python
"""达妙电机参数寄存器读写 + 改 ID + 零点 + 清错 + 保存到 Flash。

敏感操作:
  --change-id: 改完立即失联, 必须拔电重上; 需要 --confirm-id-change flag
  --save:      写入 Flash 永久生效
"""
from __future__ import annotations

import argparse
import sys

from device import DMMotor, open_bus

REG_TABLE = {
    # reg_id: (name, is_float)
    0x00: ("UV_Value", True),
    0x01: ("KT_Value", True),
    0x02: ("OT_Value", True),
    0x03: ("OC_Value", True),
    0x07: ("PMAX", True),
    0x08: ("VMAX", True),
    0x09: ("TMAX", True),
    0x0A: ("I_BW", True),
    0x10: ("CAN_ID", False),
    0x11: ("MST_ID", False),
    0x12: ("TIMEOUT", True),
    0x13: ("CTRL_MODE", False),   # 1=MIT, 2=POS_VEL, 3=SPEED
    0x17: ("KP_APR", True),
    0x18: ("KI_APR", True),
    0x19: ("KP_ASR", True),
    0x1A: ("KI_ASR", True),
}


def parse_reg(s: str) -> int:
    """接受 reg_id (0x10) 或名字 (CAN_ID)。"""
    try:
        return int(s, 0)
    except ValueError:
        pass
    for reg_id, (name, _) in REG_TABLE.items():
        if name.upper() == s.upper():
            return reg_id
    raise argparse.ArgumentTypeError(f"未知寄存器: {s}")


def fmt_value(reg_id: int, value: float) -> str:
    if reg_id in REG_TABLE and not REG_TABLE[reg_id][1]:
        return f"{int(value)} (0x{int(value):02X})"
    return f"{value:.6f}"


def main():
    p = argparse.ArgumentParser(description="达妙电机参数读写")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)

    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="列出可识别寄存器")
    g.add_argument("--get", type=parse_reg, metavar="REG",
                   help="读寄存器 (ID 或名字)")
    g.add_argument("--set", nargs=2, metavar=("REG", "VAL"),
                   help="写寄存器")
    g.add_argument("--set-zero", action="store_true", help="设置当前位置为零点")
    g.add_argument("--clear-error", action="store_true", help="清除错误")
    g.add_argument("--save", action="store_true", help="保存参数到 Flash")
    g.add_argument("--change-id", nargs=2, type=lambda x: int(x, 0),
                   metavar=("NEW_CAN_ID", "NEW_MST_ID"),
                   help="改电机 ID 和 master ID (需 --confirm-id-change)")

    p.add_argument("--confirm-id-change", action="store_true")
    args = p.parse_args()

    if args.list:
        print(f"{'REG':>5}  {'NAME':<12}  TYPE")
        for reg_id, (name, is_float) in sorted(REG_TABLE.items()):
            print(f"  0x{reg_id:02X}  {name:<12}  {'float' if is_float else 'uint'}")
        return

    bus = open_bus(channel="can0", bitrate=1_000_000)
    try:
        motor = DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                        auto_enable=False)
        if args.get is not None:
            val = motor.read_param(args.get, timeout=0.3)
            if val is None:
                print(f"[fail] 读 0x{args.get:02X} 超时"); sys.exit(1)
            name = REG_TABLE.get(args.get, (f"REG_{args.get:02X}",))[0]
            print(f"  {name} (0x{args.get:02X}) = {fmt_value(args.get, val)}")

        elif args.set is not None:
            reg = parse_reg(args.set[0])
            val = float(args.set[1])
            motor.write_param(reg, val)
            print(f"  写 0x{reg:02X} = {val} (未保存到 Flash, 跑 --save 固化)")

        elif args.set_zero:
            motor.set_zero()
            print("  [ok] 当前位置已置零 (未固化, --save 保存)")

        elif args.clear_error:
            motor.clear_error()
            print("  [ok] 清错指令已发送")

        elif args.save:
            motor.save_to_flash()
            print("  [ok] 保存到 Flash 指令已发送")

        elif args.change_id is not None:
            if not args.confirm_id_change:
                print("[错误] --change-id 需同时加 --confirm-id-change 显式确认",
                      file=sys.stderr)
                print("  改 ID 后立即失联, 必须拔电重上, 用新 ID 重连.",
                      file=sys.stderr)
                sys.exit(2)
            new_can, new_mst = args.change_id
            print(f"  写 CAN_ID = 0x{new_can:02X}")
            motor.write_param(0x10, float(new_can))
            print(f"  写 MST_ID = 0x{new_mst:02X}")
            motor.write_param(0x11, float(new_mst))
            print("  保存到 Flash")
            motor.save_to_flash()
            print(f"  [ok] 请拔电重上, 新参数: --motor-id 0x{new_can:02X} "
                  f"--master-id 0x{new_mst:02X}")

    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 人工验收 (基础读写)**

```bash
cd damiao
uv run params.py --list
uv run params.py --get PMAX
uv run params.py --get CAN_ID
uv run params.py --clear-error
```

Expected: 读回 PMAX ≈ 12.5，CAN_ID 与出厂一致。

- [ ] **Step 3: 人工验收 (改 ID 流程 — 仅当准备接第二颗电机时再做)**

```bash
# 举例: 把 4310P 的 CAN_ID 从 0x01 改到 0x05, MST_ID 从 0x11 改到 0x15
uv run params.py --change-id 0x05 0x15             # 应报错拒绝
uv run params.py --change-id 0x05 0x15 --confirm-id-change
# 拔电重上
uv run detect.py --motor-id 0x05 --master-id 0x15  # 用新 ID 探活
```

- [ ] **Step 4: Commit**

```bash
git add damiao/params.py
git commit -m "Add params.py: register read/write/save and ID change"
```

---

## Task 15: main.py — HTTP 文件浏览

**Files:**
- Create: `damiao/main.py`

- [ ] **Step 1: 复用 realsense 同款 (完整复制, 不作共享模块)**

照抄 `realsense/main.py` 内容到 `damiao/main.py`, 仅 docstring 顶部改成 "达妙电机 out/ 局域网预览":

```python
"""LAN 文件浏览 (HTTP). 从当前目录起服务, 方便远程看 out/ 下 CSV/PNG.

默认 0.0.0.0:8001, 浏览器打开 http://<本机IP>:8001/ 即可.
用法:
    uv run main.py                  # 默认 0.0.0.0:8001
    uv run main.py -p 8080
    uv run main.py -b 127.0.0.1     # 仅本机
"""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer, test


def main():
    p = argparse.ArgumentParser(description="LAN 文件浏览")
    p.add_argument("-p", "--port", type=int, default=8001)
    p.add_argument("-b", "--bind", default="0.0.0.0")
    args = p.parse_args()
    test(
        HandlerClass=SimpleHTTPRequestHandler,
        ServerClass=ThreadingHTTPServer,
        port=args.port,
        bind=args.bind,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 人工验收**

```bash
cd damiao && uv run main.py &
curl -s http://localhost:8001/out/ | head
kill %1
```

Expected: 目录列表返回。

- [ ] **Step 3: Commit**

```bash
git add damiao/main.py
git commit -m "Add main.py: LAN HTTP browser for damiao/out"
```

---

## Task 16: damiao/README.md — 完整文档

**Files:**
- Create: `damiao/README.md`

- [ ] **Step 1: 写 `damiao/README.md`**

内容包含（全部为中文，按 respeaker/realsense 惯例）:

1. **设备信息** — 4310P 与 4340 的电压/扭矩/速度/位置上限对照表
2. **硬件台架** — 下面这张 ASCII 图 + 通电顺序 + XT60→保险丝→XT30 适配线自制说明
3. **安全章节** — 默认软限幅表格 + 急停规程 + 自制保险丝线图
4. **CAN 终端电阻** — CANable 2.0 跳线位置, 电机侧何时加 120Ω
5. **Linux 环境** — `sudo bash setup.sh` + udev + systemd unit 说明
6. **固件烧录** — `fw_update.py` 用法 + BOOT 跳线位置
7. **使用** — detect/enable/mit/servo/params/main 各脚本用法
8. **Roadmap (C scope)** — 多电机支持 / CAN 协议固件升级 / 高频 benchmark / 故障码表
9. **故障排查**

关键 ASCII 图（原样抄到 README 硬件章节）:

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

安全默认值表（直接抄到 README）:

```
| 项目  | 默认 | 硬件上限 |
|-------|------|----------|
| tau   | 1.0 N·m  | 7.0 |
| vel   | 5.0 rad/s | 30.0 |
| pos   | ±π rad   | ±12.5 |
| kp    | 20       | 500 |
| kd    | 1.0      | 5 |

放开到硬件上限: --unsafe
```

故障排查表（抄自 spec 第 7 节）。

参考链接段:
- 达妙官网手册: https://www.damiaoyeah.com/
- python-can: https://python-can.readthedocs.io/
- CANable 2.0 (normaldotcom fork): https://github.com/normaldotcom/canable2
- candleLight_fw: https://github.com/candle-usb/candleLight_fw

- [ ] **Step 2: 本地渲染检查**

```bash
head -60 damiao/README.md   # 扫一眼格式
```

- [ ] **Step 3: Commit**

```bash
git add damiao/README.md
git commit -m "Add damiao/README: wiring, safety, firmware, usage, troubleshooting"
```

---

## Task 17: 根 README.md — 设备清单追加

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 追加 damiao 行**

`README.md` "项目结构" 代码块里加一行:

```
damiao/          # 达妙电机 DM4310-P / DM4340 调试 (CAN via CANable 2.0)
```

"设备清单" 表格末尾加一行:

```
| 达妙电机 DM4310-P / DM4340 | `damiao/` | 基础调试 (使能/MIT/Servo/参数/录波, 多电机+固件升级规划中) |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Add damiao entry to repo device manifest"
```

---

## 验收清单 (全部完成后跑一遍)

- [ ] `cd damiao && uv run pytest -v` 全部通过
- [ ] `uv run detect.py` USB + can0 + 电机探活三段都绿
- [ ] `uv run enable.py --hold 3` 使能期间能看到反馈帧连续、手拨轴 pos 实时变
- [ ] `uv run mit.py --profile sine --duration 3` 生成 CSV + PNG, 曲线跟命令合理
- [ ] `uv run mit.py --profile sine --duration 3 --live` 弹窗实时画图 (本地 GUI)
- [ ] `uv run servo.py --mode pos --target 0.5 --duration 2` 执行前先确认电机在 Servo 模式
- [ ] `uv run params.py --get PMAX` 读回 ~12.5
- [ ] `uv run main.py` 浏览器可看 `out/`
- [ ] 根 README 设备清单已含 damiao 行
