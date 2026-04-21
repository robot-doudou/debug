"""低层 SPI 探针 — 排查 CHIP_ID 读不到时用。

对每个 CS × SPI mode × 频率组合，发一次 "读 CHIP_ID" 事务并打印完整
收到的字节 (而不是只显示去掉 dummy 后的那一个)。从 raw 字节可以看出:

    [0x00, 0x00, 0x00]  ← MISO 没连通 / 没电 / 开关不在 SPI
    [0xFF, 0xFF, 0xFF]  ← MISO 上拉但没响应 (MOSI 可能断)
    [0x??, 0x??, 0x1E]  ← ACC 响应了但 dummy byte 位置不同
    [0x??, 0x1E, 0xFF]  ← mode / dummy 搞反了

同时也试一下不带 dummy 字节 (GYR 格式) 对 ACC 读，排除代码把 dummy 算错。
"""

import argparse
import itertools

import spidev


def xfer(bus: int, cs: int, mode: int, hz: int, tx: list[int]) -> list[int]:
    d = spidev.SpiDev()
    d.open(bus, cs)
    d.mode = mode
    d.max_speed_hz = hz
    d.bits_per_word = 8
    try:
        rx = d.xfer2(list(tx))
    finally:
        d.close()
    return rx


def fmt(rx: list[int]) -> str:
    return "[" + ", ".join(f"0x{b:02X}" for b in rx) + "]"


def parse_args():
    p = argparse.ArgumentParser(description="BMI088 / SPI 低层探针")
    p.add_argument("--bus", type=int, default=0)
    p.add_argument("--cs", type=int, nargs="+", default=[0, 1])
    p.add_argument("--mode", type=int, nargs="+", default=[0, 3])
    p.add_argument("--hz", type=int, nargs="+",
                   default=[500_000, 1_000_000, 5_000_000])
    p.add_argument("--reg", type=lambda x: int(x, 0), default=0x00,
                   help="读取的寄存器 (默认 0x00 = CHIP_ID)")
    return p.parse_args()


def main():
    args = parse_args()

    # 两种读帧: ACC 式 (多一个 dummy) / GYR 式 (只跟数据)
    templates = {
        "ACC式(addr|0x80, dummy, data×3)": [args.reg | 0x80, 0x00, 0x00, 0x00, 0x00],
        "GYR式(addr|0x80, data×3)": [args.reg | 0x80, 0x00, 0x00, 0x00],
    }

    print(f"探针寄存器: 0x{args.reg:02X}")
    print(f"BMI088 期望: ACC=0x1E  GYR=0x0F  (读 0x00)\n")

    for cs, mode, hz in itertools.product(args.cs, args.mode, args.hz):
        print(f"── /dev/spidev{args.bus}.{cs}  mode={mode}  "
              f"hz={hz/1e6:.2f}M ──")
        for label, tx in templates.items():
            try:
                rx = xfer(args.bus, cs, mode, hz, tx)
                print(f"   {label:<32}  tx={fmt(tx)}  rx={fmt(rx)}")
            except Exception as e:
                print(f"   {label:<32}  ERROR: {e}")
        print()


if __name__ == "__main__":
    main()
