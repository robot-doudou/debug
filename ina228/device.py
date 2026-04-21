"""INA228 I²C 驱动 (Jetson smbus2).

使用:
    with Ina228(bus=7, address=0x40, r_shunt_ohm=0.002, i_max_a=100) as ina:
        info = ina.probe()
        vbus = ina.read_vbus_v()
        cur  = ina.read_current_a()
        pwr  = ina.read_power_w()
        t    = ina.read_dietemp_c()

INA228 寄存器是大端，smbus2 的 read_word_data 会字节交换，所以统一用
read_i2c_block_data + 手动拼字节。
"""

from __future__ import annotations

import math
import os
import pathlib
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from smbus2 import SMBus

# ========== 寄存器地址 ==========
CONFIG = 0x00
ADC_CONFIG = 0x01
SHUNT_CAL = 0x02
SHUNT_TEMPCO = 0x03
VSHUNT = 0x04
VBUS = 0x05
DIETEMP = 0x06
CURRENT = 0x07
POWER = 0x08
ENERGY = 0x09
CHARGE = 0x0A
DIAG_ALRT = 0x0B
MANUFACTURER_ID = 0x3E
DEVICE_ID = 0x3F

# ========== 期望值 / 常量 ==========
MANUFACTURER_ID_VALUE = 0x5449  # "TI"
DEVICE_ID_HIGH = 0x228  # DEVICE_ID 高 12 位；低 4 位 = die rev

# CONFIG 位
CONFIG_RST = 1 << 15
CONFIG_ADCRANGE = 1 << 4

# ADC LSB (datasheet 表 8-5)
VSHUNT_LSB_RANGE0 = 312.5e-9     # V/LSB (ADCRANGE=0, ±163.84 mV)
VSHUNT_LSB_RANGE1 = 78.125e-9    # V/LSB (ADCRANGE=1, ±40.96 mV)
VBUS_LSB = 195.3125e-6           # V/LSB
DIETEMP_LSB = 7.8125e-3          # °C/LSB (上 12 位)

# ========== 位宽 / 字节序解析 ==========

def _parse_s20_from_24(b: list[int]) -> int:
    """读 3 字节 big-endian → 24 位 → 右移 4 位 → 有符号 20 位。"""
    raw = (b[0] << 16) | (b[1] << 8) | b[2]
    v = raw >> 4
    return v - 0x100000 if v & 0x80000 else v


def _parse_u24(b: list[int]) -> int:
    return (b[0] << 16) | (b[1] << 8) | b[2]


def _parse_u40(b: list[int]) -> int:
    v = 0
    for x in b:
        v = (v << 8) | x
    return v


def _parse_s40(b: list[int]) -> int:
    v = _parse_u40(b)
    return v - (1 << 40) if v & (1 << 39) else v


def _parse_s16(hi: int, lo: int) -> int:
    """DIETEMP: 全 16 位有符号，无保留位。"""
    v = (hi << 8) | lo
    return v - 0x10000 if v & 0x8000 else v


# ========== CURRENT_LSB 自动选取 ==========

def _pick_current_lsb(i_max_a: float) -> float:
    """把 i_max_a / 2^19 向上圆整到首位有效数字 (保量程够用 + 好读)。

    例:
      I_MAX=100A → 190.7 µA ideal → 200 µA
      I_MAX= 50A →  95.4 µA ideal → 100 µA
      I_MAX=160A → 305   µA ideal → 400 µA
    """
    if i_max_a <= 0:
        raise ValueError("i_max_a 必须 > 0")
    ideal = i_max_a / (1 << 19)
    exponent = math.floor(math.log10(ideal))
    mantissa = ideal / (10 ** exponent)
    rounded_mantissa = math.ceil(mantissa)  # 向上取整保 headroom
    if rounded_mantissa == 10:
        rounded_mantissa = 1
        exponent += 1
    return rounded_mantissa * (10 ** exponent)


# ========== 主类 ==========

@dataclass
class Ina228Info:
    manufacturer_id: int
    device_id: int
    adcrange: int
    current_lsb_a: float
    shunt_cal: int
    r_shunt_ohm: float
    i_max_a: float
    max_measurable_a: float  # 受 ADC 范围硬限幅
    bus: int
    address: int


class Ina228:
    def __init__(
        self,
        bus: int = 7,
        address: int = 0x40,
        r_shunt_ohm: float = 0.002,
        i_max_a: float = 100.0,
        adcrange: int = 0,    # 0=±163.84mV (默认), 1=±40.96mV (4× 精度)
        current_lsb_a: float | None = None,
        reset: bool = True,
    ):
        if adcrange not in (0, 1):
            raise ValueError("adcrange 必须 0 或 1")
        self.bus_num = bus
        self.address = address
        self.r_shunt_ohm = r_shunt_ohm
        self.i_max_a = i_max_a
        self.adcrange = adcrange
        self._bus = SMBus(bus)

        # CURRENT_LSB: 用户显式给 or 根据 I_MAX 自动选
        self.current_lsb_a = (current_lsb_a
                              if current_lsb_a is not None
                              else _pick_current_lsb(i_max_a))

        # SHUNT_CAL 公式：
        #   ADCRANGE=0: SHUNT_CAL = 13107.2e6 × CURRENT_LSB × R_SHUNT
        #   ADCRANGE=1: 上式 × 4
        cal = 13107.2e6 * self.current_lsb_a * r_shunt_ohm
        if adcrange == 1:
            cal *= 4
        self.shunt_cal = max(0, min(int(round(cal)), 0x7FFF))  # 15-bit

        # VSHUNT ADC 硬量程
        vshunt_max = 0.16384 if adcrange == 0 else 0.04096
        self.max_measurable_a = vshunt_max / r_shunt_ohm

        # 初始化芯片
        if reset:
            self._write16(CONFIG, CONFIG_RST)
            time.sleep(0.01)
        # 配 ADCRANGE (其他位清零 = CONVDLY=0, TEMPCOMP off)
        cfg = CONFIG_ADCRANGE if adcrange == 1 else 0
        self._write16(CONFIG, cfg)
        # 写 SHUNT_CAL
        self._write16(SHUNT_CAL, self.shunt_cal)

    # ---------- I2C 基础读写 ----------

    def _write16(self, reg: int, val: int) -> None:
        hi = (val >> 8) & 0xFF
        lo = val & 0xFF
        self._bus.write_i2c_block_data(self.address, reg, [hi, lo])

    def _read16(self, reg: int) -> int:
        d = self._bus.read_i2c_block_data(self.address, reg, 2)
        return (d[0] << 8) | d[1]

    def _read24(self, reg: int) -> list[int]:
        return self._bus.read_i2c_block_data(self.address, reg, 3)

    def _read40(self, reg: int) -> list[int]:
        return self._bus.read_i2c_block_data(self.address, reg, 5)

    # ---------- 探针 ----------

    def probe(self) -> Ina228Info:
        return Ina228Info(
            manufacturer_id=self._read16(MANUFACTURER_ID),
            device_id=self._read16(DEVICE_ID),
            adcrange=self.adcrange,
            current_lsb_a=self.current_lsb_a,
            shunt_cal=self.shunt_cal,
            r_shunt_ohm=self.r_shunt_ohm,
            i_max_a=self.i_max_a,
            max_measurable_a=self.max_measurable_a,
            bus=self.bus_num,
            address=self.address,
        )

    # ---------- 单通道读取 ----------

    def read_vshunt_v(self) -> float:
        b = self._read24(VSHUNT)
        raw = _parse_s20_from_24(b)
        lsb = VSHUNT_LSB_RANGE1 if self.adcrange == 1 else VSHUNT_LSB_RANGE0
        return raw * lsb

    def read_vbus_v(self) -> float:
        b = self._read24(VBUS)
        return _parse_s20_from_24(b) * VBUS_LSB

    def read_current_a(self) -> float:
        b = self._read24(CURRENT)
        return _parse_s20_from_24(b) * self.current_lsb_a

    def read_power_w(self) -> float:
        b = self._read24(POWER)
        # POWER 是 24-bit unsigned，全 24 位有效
        return _parse_u24(b) * 3.2 * self.current_lsb_a

    def read_dietemp_c(self) -> float:
        d = self._bus.read_i2c_block_data(self.address, DIETEMP, 2)
        return _parse_s16(d[0], d[1]) * DIETEMP_LSB

    def read_energy_j(self) -> float:
        b = self._read40(ENERGY)
        # datasheet eq 7: Energy (J) = 16 × 3.2 × CURRENT_LSB × ENERGY_reg
        return _parse_u40(b) * 16 * 3.2 * self.current_lsb_a

    def read_charge_c(self) -> float:
        b = self._read40(CHARGE)
        # datasheet eq 8: Charge (C) = CURRENT_LSB × CHARGE_reg
        return _parse_s40(b) * self.current_lsb_a

    def reset_accumulators(self) -> None:
        """清零 ENERGY / CHARGE 累积寄存器 (写 CONFIG.RSTACC=1)."""
        cfg = CONFIG_ADCRANGE if self.adcrange == 1 else 0
        self._write16(CONFIG, cfg | (1 << 14))

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ========== 环境 / 文件辅助 ==========

def require_i2c(bus: int = 7) -> None:
    """检查 /dev/i2c-N 存在且可读写。"""
    p = pathlib.Path(f"/dev/i2c-{bus}")
    if not p.exists():
        print(f"[错误] {p} 不存在，可用节点: "
              f"{[str(x) for x in sorted(pathlib.Path('/dev').glob('i2c-*'))]}",
              file=sys.stderr)
        sys.exit(1)
    if not os.access(p, os.R_OK | os.W_OK):
        print(f"[错误] 无权读写 {p}", file=sys.stderr)
        print("  → Jetson 默认用户在 i2c 组；缺则 sudo usermod -aG i2c $USER",
              file=sys.stderr)
        sys.exit(1)


def output_dir(subdir: str = "") -> pathlib.Path:
    base = pathlib.Path(__file__).parent / "out"
    if subdir:
        base = base / subdir
    base.mkdir(parents=True, exist_ok=True)
    return base


def timestamped(prefix: str, ext: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
