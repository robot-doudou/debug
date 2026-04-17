"""达妙电机 DM4310-P / DM4340 共享层: CAN 总线 / DM v4 协议 / 安全限幅 / 输出路径。

DM 电机 USB 适配器标识 (CANable 2.0):
    slcan:        VID 0x16D0, PID 0x117E  (normaldotcom fork)
    candleLight:  VID 0x1D50, PID 0x606F  (gs_usb 内核驱动)
"""

from __future__ import annotations

import os
import pathlib
import struct as _struct
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


# --- DM v4 MIT 反馈帧解析 ---

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


# --- MIT 特殊控制命令 (CAN ID = motor_id, DLC = 8) ---

CMD_ENABLE      = bytes([0xFF]*7 + [0xFC])
CMD_DISABLE     = bytes([0xFF]*7 + [0xFD])
CMD_SET_ZERO    = bytes([0xFF]*7 + [0xFE])
CMD_CLEAR_ERROR = bytes([0xFF]*7 + [0xFB])


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
