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


def param_write_frame_uint(motor_id: int, reg_id: int, value: int) -> tuple[int, bytes]:
    """uint32 寄存器写帧 (ESC_ID / MST_ID / CTRL_MODE 等)。"""
    data = bytes([motor_id & 0xFF, (motor_id >> 8) & 0xFF, PARAM_WRITE, reg_id]) + _struct.pack("<I", value)
    return 0x7FF, data


def param_save_frame(motor_id: int) -> tuple[int, bytes]:
    data = bytes([motor_id & 0xFF, (motor_id >> 8) & 0xFF, PARAM_SAVE, 0, 0, 0, 0, 0])
    return 0x7FF, data


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

    def __init__(self, bus, motor_id: int = 0x01, master_id: int = 0x00,
                 p_max: float = 12.5, v_max: float = 30.0, t_max: float = 10.0,
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

    def read_state(self, timeout: float = 0.05):
        """收一帧反馈 (CAN ID = master_id), 超时返回 None。"""
        msg = self.bus.recv(timeout=timeout)
        if msg is None:
            return None
        if msg.arbitration_id == self.master_id and len(msg.data) == 8:
            return parse_mit_feedback(msg.data, self.p_max, self.v_max, self.t_max)
        return None

    # --- 参数读写 ---

    def read_param_raw(self, reg_id: int, timeout: float = 0.2) -> bytes | None:
        """读寄存器, 返回 4 字节原始数据 (调用方按寄存器类型自行解 float32 或 uint32)。

        DM v4 响应帧 CAN ID = master_id (同 MIT 状态帧),
        data 格式: [motor_id_lo, motor_id_hi, cmd=0x33, reg_id, b0, b1, b2, b3]
        """
        can_id, data = param_read_frame(self.motor_id, reg_id)
        self._send(can_id, data)
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            msg = self.bus.recv(timeout=remaining)
            if msg is None:
                return None
            if msg.arbitration_id == self.master_id and len(msg.data) == 8 \
               and msg.data[2] == PARAM_READ and msg.data[3] == reg_id:
                return bytes(msg.data[4:8])
        return None

    def read_param(self, reg_id: int, timeout: float = 0.2) -> float | None:
        """读 float32 寄存器的便捷封装。uint 类型寄存器请用 read_param_raw 再 unpack。"""
        raw = self.read_param_raw(reg_id, timeout)
        return _struct.unpack("<f", raw)[0] if raw is not None else None

    def write_param(self, reg_id: int, value: float):
        """写 float32 寄存器 (DM v4 常见). uint 寄存器用 write_param_uint."""
        can_id, data = param_write_frame(self.motor_id, reg_id, value)
        self._send(can_id, data)

    def write_param_uint(self, reg_id: int, value: int):
        """写 uint32 寄存器 (如 ESC_ID / MST_ID / CTRL_MODE)."""
        can_id, data = param_write_frame_uint(self.motor_id, reg_id, value)
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
        last_err = None
        for _ in range(2):  # 最多重试一次
            try:
                self.disable()
                return
            except Exception as e:
                last_err = e
                continue
        # 两次都失败: 向 stderr 打印警告, 电机可能仍处于使能状态
        print(
            f"[严重] 电机 0x{self.motor_id:02X} disable 两次都失败 ({last_err}); "
            f"电机可能仍然使能, 立即拔掉电池 XT60 确认断电!",
            file=sys.stderr,
            flush=True,
        )
