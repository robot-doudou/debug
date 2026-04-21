"""检测 Jetson I²C 环境 + INA228 存在性验证。

步骤:
    1. 列出 /dev/i2c-* 节点
    2. 在指定 bus 上扫描地址 (相当于 i2cdetect)
    3. 对目标地址读 MANUFACTURER_ID / DEVICE_ID
"""

import argparse
import os
import pathlib
import stat
import sys

from smbus2 import SMBus

from device import (
    DEVICE_ID,
    DEVICE_ID_HIGH,
    MANUFACTURER_ID,
    MANUFACTURER_ID_VALUE,
    require_i2c,
)


def parse_args():
    p = argparse.ArgumentParser(description="INA228 / I²C 环境检测")
    p.add_argument("--bus", type=int, default=7)
    p.add_argument("--addr", type=lambda x: int(x, 0), default=0x40)
    return p.parse_args()


def dump_nodes() -> list[pathlib.Path]:
    print("=== /dev/i2c-* 节点 ===")
    nodes = sorted(pathlib.Path("/dev").glob("i2c-*"))
    if not nodes:
        print("  (未发现 I²C 节点) → 检查 jetson-io / kernel driver")
        return []
    for n in nodes:
        st = n.stat()
        can_rw = os.access(n, os.R_OK | os.W_OK)
        tag = "可读写" if can_rw else "无权限"
        print(f"  {n}  {stat.filemode(st.st_mode)} ({oct(st.st_mode & 0o777)})  "
              f"uid={st.st_uid} gid={st.st_gid}  [{tag}]")
    return nodes


def scan_bus(bus_num: int) -> list[int]:
    """扫 7-bit 地址 (0x03-0x77)，返回响应的列表。"""
    found = []
    try:
        with SMBus(bus_num) as bus:
            for addr in range(0x03, 0x78):
                try:
                    bus.read_byte(addr)
                    found.append(addr)
                except OSError:
                    pass
    except Exception as e:
        print(f"  无法打开 bus {bus_num}: {e}", file=sys.stderr)
    return found


def probe_ina228(bus_num: int, addr: int) -> bool:
    print(f"\n=== INA228 (bus {bus_num}, addr 0x{addr:02X}) ===")
    try:
        with SMBus(bus_num) as bus:
            mfg = bus.read_i2c_block_data(addr, MANUFACTURER_ID, 2)
            dev = bus.read_i2c_block_data(addr, DEVICE_ID, 2)
    except OSError as e:
        print(f"  I²C 读失败: {e}")
        return False

    mfg_val = (mfg[0] << 8) | mfg[1]
    dev_val = (dev[0] << 8) | dev[1]
    dev_high = dev_val >> 4
    dev_rev = dev_val & 0xF

    mfg_ok = mfg_val == MANUFACTURER_ID_VALUE
    dev_ok = dev_high == DEVICE_ID_HIGH

    print(f"  MANUFACTURER_ID: 0x{mfg_val:04X}  "
          f"期望 0x{MANUFACTURER_ID_VALUE:04X} ('TI')   "
          f"[{'OK' if mfg_ok else 'FAIL'}]")
    print(f"  DEVICE_ID      : 0x{dev_val:04X}  "
          f"(dev=0x{dev_high:03X}, rev={dev_rev})  "
          f"期望 dev=0x{DEVICE_ID_HIGH:03X}   "
          f"[{'OK' if dev_ok else 'FAIL'}]")

    return mfg_ok and dev_ok


def main():
    args = parse_args()
    dump_nodes()
    require_i2c(args.bus)

    print(f"\n=== bus {args.bus} 地址扫描 ===")
    found = scan_bus(args.bus)
    if not found:
        print("  (无设备响应)")
    else:
        print(f"  发现 {len(found)} 个地址: "
              f"{', '.join(f'0x{a:02X}' for a in found)}")
    if args.addr not in found:
        print(f"  ⚠ 目标地址 0x{args.addr:02X} 未在扫描结果中")

    ok = probe_ina228(args.bus, args.addr)

    print("\n=== 汇总 ===")
    print(f"  INA228 @ bus {args.bus} / 0x{args.addr:02X}: "
          f"{'OK' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
