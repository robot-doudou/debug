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
