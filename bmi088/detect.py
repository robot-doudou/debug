"""检测 Jetson SPI 环境 + BMI088 CHIP_ID 验证。

步骤:
    1. 枚举 /dev/spidev* 节点并打印权限
    2. 对 ACC (CS0) / GYR (CS1) 各发一次 CHIP_ID 读
    3. 判断 ACC=0x1E / GYR=0x0F 是否匹配
"""

import argparse
import os
import pathlib
import stat
import sys

from device import (
    ACC_CHIP_ID,
    ACC_CHIP_ID_VALUE,
    GYR_CHIP_ID,
    GYR_CHIP_ID_VALUE,
    AccSpi,
    GyrSpi,
    spidev_nodes,
)


def parse_args():
    p = argparse.ArgumentParser(description="BMI088 / SPI 环境检测")
    p.add_argument("--bus", type=int, default=0)
    p.add_argument("--acc-cs", type=int, default=0)
    p.add_argument("--gyr-cs", type=int, default=1)
    p.add_argument("--spi-hz", type=int, default=1_000_000)
    return p.parse_args()


def _format_mode(st_mode: int) -> str:
    return stat.filemode(st_mode) + f" ({oct(st_mode & 0o777)})"


def dump_nodes(bus: int) -> list[pathlib.Path]:
    print("=== /dev/spidev 节点 ===")
    nodes = spidev_nodes(bus)
    if not nodes:
        # 列出全部 spidev*，给排错线索
        all_nodes = sorted(pathlib.Path("/dev").glob("spidev*"))
        if all_nodes:
            print(f"  bus {bus} 无节点；当前存在的 spidev:")
            for n in all_nodes:
                print(f"    {n}")
        else:
            print("  未发现任何 /dev/spidev*")
        print("  → sudo /opt/nvidia/jetson-io.py 启用 SPI 并重启")
        return []
    for n in nodes:
        st = n.stat()
        can_rw = os.access(n, os.R_OK | os.W_OK)
        tag = "可读写" if can_rw else "无权限"
        print(f"  {n}  {_format_mode(st.st_mode)}  uid={st.st_uid} gid={st.st_gid}  [{tag}]")
    return nodes


def probe_chip(name: str, cls, bus: int, cs: int, spi_hz: int, reg: int, expected: int) -> bool:
    path = f"/dev/spidev{bus}.{cs}"
    print(f"\n=== {name}  ({path}) CHIP_ID ===")
    if not pathlib.Path(path).exists():
        print(f"  节点不存在，跳过")
        return False
    if not os.access(path, os.R_OK | os.W_OK):
        print(f"  无权读写，跳过 (试试 sudo uv run detect.py)")
        return False
    try:
        dev = cls(bus=bus, cs=cs, max_hz=spi_hz)
        cid = dev.read(reg, 1)[0]
        dev.close()
    except Exception as e:
        print(f"  SPI 读失败: {e}")
        return False
    ok = cid == expected
    tag = "OK" if ok else "不匹配！检查拨动开关在 SPI 档 / CS 接线 / VCC"
    print(f"  读出: 0x{cid:02X}   期望: 0x{expected:02X}   [{tag}]")
    return ok


def main():
    args = parse_args()
    nodes = dump_nodes(args.bus)
    if not nodes:
        sys.exit(1)

    acc_ok = probe_chip(
        "ACC (加速度计)", AccSpi, args.bus, args.acc_cs, args.spi_hz,
        ACC_CHIP_ID, ACC_CHIP_ID_VALUE,
    )
    gyr_ok = probe_chip(
        "GYR (陀螺仪)", GyrSpi, args.bus, args.gyr_cs, args.spi_hz,
        GYR_CHIP_ID, GYR_CHIP_ID_VALUE,
    )

    print("\n=== 汇总 ===")
    print(f"  ACC: {'OK' if acc_ok else 'FAIL'}")
    print(f"  GYR: {'OK' if gyr_ok else 'FAIL'}")
    sys.exit(0 if (acc_ok and gyr_ok) else 1)


if __name__ == "__main__":
    main()
