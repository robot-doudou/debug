"""BMI088 六轴 IMU SPI 驱动 (Jetson spidev).

BMI088 内部是两颗独立 die (ACC + GYR)，当两个 SPI 从设备访问：
    /dev/spidev0.0 → ACC (CSB1)
    /dev/spidev0.1 → GYR (CSB2)

SPI 模式 3 (CPOL=1, CPHA=1)，最高 10 MHz。

ACC 的 SPI 读响应首字节是 dummy byte，必须丢弃 (GYR 无此问题)。
ACC 软复位后接口回到 I2C 模式，必须先做一次 dummy read 才会切回 SPI。
"""

from __future__ import annotations

import math
import os
import pathlib
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import spidev

GRAVITY = 9.80665

# ACC 寄存器
ACC_CHIP_ID = 0x00
ACC_X_LSB = 0x12
ACC_CONF = 0x40
ACC_RANGE = 0x41
ACC_PWR_CONF = 0x7C
ACC_PWR_CTRL = 0x7D
ACC_SOFTRESET = 0x7E

ACC_CHIP_ID_VALUE = 0x1E
ACC_SOFTRESET_CMD = 0xB6
ACC_PWR_CTRL_ON = 0x04
ACC_PWR_CONF_ACTIVE = 0x00
ACC_CONF_100HZ_NORMAL = 0xA8

# GYR 寄存器
GYR_CHIP_ID = 0x00
GYR_X_LSB = 0x02
GYR_RANGE_REG = 0x0F
GYR_BANDWIDTH = 0x10

GYR_CHIP_ID_VALUE = 0x0F

# ±g (ACC_RANGE 寄存器编码)
ACC_RANGE_G = {0x00: 3, 0x01: 6, 0x02: 12, 0x03: 24}
ACC_RANGE_G_TO_REG = {v: k for k, v in ACC_RANGE_G.items()}

# ±dps (GYR_RANGE 寄存器编码)
GYR_RANGE_DPS = {0x00: 2000, 0x01: 1000, 0x02: 500, 0x03: 250, 0x04: 125}
GYR_RANGE_DPS_TO_REG = {v: k for k, v in GYR_RANGE_DPS.items()}

# GYR_BANDWIDTH 寄存器 (0x10): (ODR_Hz, filter_BW_Hz) → 寄存器值
# 同一 ODR 有宽 / 窄带宽两种选择，窄带宽噪声低、响应慢；机器人姿态优选窄带宽那一档。
GYR_ODR_BW = {
    # 寄存器值     ODR    BW
    0x00:       (2000,  532),   # datasheet 默认 (上电后)
    0x01:       (2000,  230),
    0x02:       (1000,  116),
    0x03:       ( 400,   47),   # ⭐ 足式机器人典型选择
    0x04:       ( 200,   23),
    0x05:       ( 100,   12),
    0x06:       ( 200,   64),
    0x07:       ( 100,   32),
}
# 简化 API: 按 ODR 选，每个 ODR 默认取窄 BW 那档
GYR_ODR_TO_REG = {
    2000: 0x00,  # 只有宽带宽一档
    1000: 0x02,
     400: 0x03,
     200: 0x04,  # 23 Hz (窄)；想要 64 Hz BW 走 0x06
     100: 0x05,  # 12 Hz (窄)；想要 32 Hz BW 走 0x07
}


def _open_spi(bus: int, cs: int, max_hz: int) -> spidev.SpiDev:
    dev = spidev.SpiDev()
    dev.open(bus, cs)
    dev.mode = 0b11  # CPOL=1, CPHA=1
    dev.max_speed_hz = max_hz
    dev.bits_per_word = 8
    return dev


class AccSpi:
    """加速度计 SPI 从设备。读操作首字节是 dummy byte，必须丢弃。

    上电后 BMI088 ACC 接口默认 I2C；**首次 SPI 通信的 CSB 翻转把接口锁到 SPI，
    但该次读的响应数据是未定义**。构造时发一次任意读做 warmup，后续才能读到真值。
    """

    def __init__(self, bus: int = 0, cs: int = 0, max_hz: int = 1_000_000):
        self.bus = bus
        self.cs = cs
        self._dev = _open_spi(bus, cs, max_hz)
        # warmup: 触发 CSB 翻转把接口切到 SPI，响应丢弃
        try:
            self._dev.xfer2([ACC_CHIP_ID | 0x80, 0x00, 0x00])
            time.sleep(0.001)
        except Exception:
            pass

    def read(self, reg: int, n: int = 1) -> bytes:
        tx = [reg | 0x80, 0x00] + [0x00] * n
        rx = self._dev.xfer2(tx)
        return bytes(rx[2:])

    def write(self, reg: int, val: int) -> None:
        self._dev.xfer2([reg & 0x7F, val & 0xFF])

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:
            pass


class GyrSpi:
    """陀螺仪 SPI 从设备。标准 SPI 读（无 BMI088 dummy byte）。"""

    def __init__(self, bus: int = 0, cs: int = 1, max_hz: int = 1_000_000):
        self.bus = bus
        self.cs = cs
        self._dev = _open_spi(bus, cs, max_hz)

    def read(self, reg: int, n: int = 1) -> bytes:
        tx = [reg | 0x80] + [0x00] * n
        rx = self._dev.xfer2(tx)
        return bytes(rx[1:])

    def write(self, reg: int, val: int) -> None:
        self._dev.xfer2([reg & 0x7F, val & 0xFF])

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:
            pass


def _s16_le(buf: bytes, off: int) -> int:
    v = buf[off] | (buf[off + 1] << 8)
    return v - 0x10000 if v & 0x8000 else v


@dataclass
class Bmi088Info:
    acc_chip_id: int
    gyr_chip_id: int
    acc_range_g: int
    gyr_range_dps: int
    gyr_odr_hz: int
    gyr_bw_hz: int
    spi_hz: int


class Bmi088:
    """BMI088 双 die 组合封装。

    用法:
        with Bmi088() as imu:
            info = imu.probe()
            ax, ay, az = imu.read_accel_m_s2()
            gx, gy, gz = imu.read_gyro_dps()
    """

    def __init__(
        self,
        bus: int = 0,
        acc_cs: int = 0,
        gyr_cs: int = 1,
        spi_hz: int = 1_000_000,
        acc_range_g: int = 6,
        gyr_range_dps: int = 500,
        gyr_odr_hz: int = 400,
        acc_conf: int = ACC_CONF_100HZ_NORMAL,
    ):
        if acc_range_g not in ACC_RANGE_G_TO_REG:
            raise ValueError(f"acc_range_g 必须在 {list(ACC_RANGE_G_TO_REG)}")
        if gyr_range_dps not in GYR_RANGE_DPS_TO_REG:
            raise ValueError(f"gyr_range_dps 必须在 {list(GYR_RANGE_DPS_TO_REG)}")
        if gyr_odr_hz not in GYR_ODR_TO_REG:
            raise ValueError(f"gyr_odr_hz 必须在 {list(GYR_ODR_TO_REG)}")
        self.spi_hz = spi_hz
        self.acc_range_g = acc_range_g
        self.gyr_range_dps = gyr_range_dps
        gyr_bw_reg = GYR_ODR_TO_REG[gyr_odr_hz]
        self.gyr_odr_hz, self.gyr_bw_hz = GYR_ODR_BW[gyr_bw_reg]
        self._acc_scale_m_s2 = acc_range_g * GRAVITY / 32768.0
        self._gyr_scale_dps = gyr_range_dps / 32768.0
        self._gyr_scale_rad = self._gyr_scale_dps * math.pi / 180.0

        self.acc = AccSpi(bus, acc_cs, spi_hz)  # 构造函数已做 warmup dummy read
        self.gyr = GyrSpi(bus, gyr_cs, spi_hz)

        self._init_acc(ACC_RANGE_G_TO_REG[acc_range_g], acc_conf)
        self._init_gyr(GYR_RANGE_DPS_TO_REG[gyr_range_dps], gyr_bw_reg)

    def _init_acc(self, range_reg: int, acc_conf: int) -> None:
        # 启动序列 (datasheet "Power modes" + SPI note)
        #   1. 软复位
        #   2. 软复位后做一次 dummy read 切回 SPI
        #   3. PWR_CTRL → on
        #   4. PWR_CONF → active (关 suspend)
        #   5. 配置 ODR / 量程
        self.acc.write(ACC_SOFTRESET, ACC_SOFTRESET_CMD)
        time.sleep(0.05)
        try:
            self.acc.read(ACC_CHIP_ID, 1)  # dummy read to re-enter SPI
        except Exception:
            pass
        time.sleep(0.05)
        self.acc.write(ACC_PWR_CTRL, ACC_PWR_CTRL_ON)
        time.sleep(0.05)
        self.acc.write(ACC_PWR_CONF, ACC_PWR_CONF_ACTIVE)
        time.sleep(0.05)
        self.acc.write(ACC_CONF, acc_conf)
        time.sleep(0.01)
        self.acc.write(ACC_RANGE, range_reg)
        time.sleep(0.01)

    def _init_gyr(self, range_reg: int, bw_reg: int) -> None:
        self.gyr.write(GYR_RANGE_REG, range_reg)
        time.sleep(0.01)
        self.gyr.write(GYR_BANDWIDTH, bw_reg)
        time.sleep(0.01)

    def probe(self) -> Bmi088Info:
        acc_id = self.acc.read(ACC_CHIP_ID, 1)[0]
        gyr_id = self.gyr.read(GYR_CHIP_ID, 1)[0]
        return Bmi088Info(
            acc_chip_id=acc_id,
            gyr_chip_id=gyr_id,
            acc_range_g=self.acc_range_g,
            gyr_range_dps=self.gyr_range_dps,
            gyr_odr_hz=self.gyr_odr_hz,
            gyr_bw_hz=self.gyr_bw_hz,
            spi_hz=self.spi_hz,
        )

    def read_accel_raw(self) -> tuple[int, int, int]:
        buf = self.acc.read(ACC_X_LSB, 6)
        return _s16_le(buf, 0), _s16_le(buf, 2), _s16_le(buf, 4)

    def read_gyro_raw(self) -> tuple[int, int, int]:
        buf = self.gyr.read(GYR_X_LSB, 6)
        return _s16_le(buf, 0), _s16_le(buf, 2), _s16_le(buf, 4)

    def read_accel_m_s2(self) -> tuple[float, float, float]:
        rx, ry, rz = self.read_accel_raw()
        s = self._acc_scale_m_s2
        return rx * s, ry * s, rz * s

    def read_gyro_dps(self) -> tuple[float, float, float]:
        rx, ry, rz = self.read_gyro_raw()
        s = self._gyr_scale_dps
        return rx * s, ry * s, rz * s

    def read_gyro_rad_s(self) -> tuple[float, float, float]:
        rx, ry, rz = self.read_gyro_raw()
        s = self._gyr_scale_rad
        return rx * s, ry * s, rz * s

    def close(self) -> None:
        self.acc.close()
        self.gyr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def spidev_nodes(bus: int = 0) -> list[pathlib.Path]:
    """当前平台上指定 bus 的 /dev/spidevN.* 节点列表 (按 CS 排序)。"""
    return sorted(pathlib.Path("/dev").glob(f"spidev{bus}.*"))


def require_spidev(bus: int = 0, cs_list: tuple[int, ...] = (0, 1)) -> None:
    """检查 spidev 节点存在且当前用户可读写，缺失 / 无权则退出。"""
    missing: list[str] = []
    no_perm: list[str] = []
    for cs in cs_list:
        p = pathlib.Path(f"/dev/spidev{bus}.{cs}")
        if not p.exists():
            missing.append(str(p))
            continue
        if not os.access(p, os.R_OK | os.W_OK):
            no_perm.append(str(p))

    if missing:
        print(f"[错误] SPI 设备节点缺失: {missing}", file=sys.stderr)
        print("  → sudo /opt/nvidia/jetson-io.py 启用 SPI0 并重启", file=sys.stderr)
        print("     然后 ls /dev/spidev0.* 应出现 spidev0.0 和 spidev0.1", file=sys.stderr)
        sys.exit(1)
    if no_perm:
        print(f"[错误] 无权读写: {no_perm}", file=sys.stderr)
        print("  → 加入 spi 组 (见 README)；或直接 sudo uv run ...", file=sys.stderr)
        sys.exit(1)


def output_dir(subdir: str = "") -> pathlib.Path:
    """返回 ./out[/subdir]，不存在则创建。"""
    base = pathlib.Path(__file__).parent / "out"
    if subdir:
        base = base / subdir
    base.mkdir(parents=True, exist_ok=True)
    return base


def timestamped(prefix: str, ext: str) -> str:
    """<prefix>_YYYYMMDD_HHMMSS.<ext>"""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
