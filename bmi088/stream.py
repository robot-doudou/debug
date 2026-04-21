"""BMI088 实时流: 打印 ACC+GYR 并统计循环采样率，可选保存 CSV。

不是硬件 ODR 本身 (ACC=100 Hz 默认由 ACC_CONF 决定)，而是应用层 polling 速率。
全速轮询可以观察到 SPI + Python 栈的上限。
"""

import argparse
import csv
import math
import pathlib
import sys
import time

from device import (
    Bmi088,
    output_dir,
    require_spidev,
    timestamped,
)


def parse_args():
    p = argparse.ArgumentParser(description="BMI088 实时流 / Hz 测试")
    p.add_argument("--duration", type=float, default=10.0, help="采集时长 (秒)")
    p.add_argument("--spi-hz", type=int, default=1_000_000,
                   help="SPI 时钟 (Hz)，BMI088 上限 10 MHz")
    p.add_argument("--acc-range", type=int, choices=[3, 6, 12, 24], default=6,
                   help="ACC 量程 ±g")
    p.add_argument("--gyr-range", type=int, choices=[2000, 1000, 500, 250, 125],
                   default=500, help="GYR 量程 ±dps")
    p.add_argument("--gyr-odr", type=int, choices=[2000, 1000, 400, 200, 100],
                   default=400,
                   help="GYR ODR/带宽预设 (Hz); 400→47BW ⭐, 100→12BW 最安静")
    p.add_argument("--rate-hz", type=float, default=0.0,
                   help="目标采样率；0 = 不限速全速轮询")
    p.add_argument("--save", type=str, default="",
                   help="保存 CSV 路径；空=不保存；'auto'=out/stream_TS.csv")
    p.add_argument("--print-every", type=float, default=0.5,
                   help="终端打印间隔 (秒)，0 = 每个样本都打印")
    p.add_argument("--bus", type=int, default=0)
    p.add_argument("--acc-cs", type=int, default=0)
    p.add_argument("--gyr-cs", type=int, default=1)
    return p.parse_args()


def main():
    args = parse_args()
    require_spidev(bus=args.bus, cs_list=(args.acc_cs, args.gyr_cs))

    csv_path: pathlib.Path | None = None
    csv_file = None
    writer = None
    if args.save:
        if args.save == "auto":
            csv_path = output_dir() / timestamped("stream", "csv")
        else:
            csv_path = pathlib.Path(args.save)
            csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_file = open(csv_path, "w", newline="")
        writer = csv.writer(csv_file)
        writer.writerow(
            ["t_s", "ax_m_s2", "ay_m_s2", "az_m_s2",
             "gx_dps", "gy_dps", "gz_dps"]
        )

    dt_target = 1.0 / args.rate_hz if args.rate_hz > 0 else 0.0

    try:
        with Bmi088(
            bus=args.bus,
            acc_cs=args.acc_cs,
            gyr_cs=args.gyr_cs,
            spi_hz=args.spi_hz,
            acc_range_g=args.acc_range,
            gyr_range_dps=args.gyr_range,
            gyr_odr_hz=args.gyr_odr,
        ) as imu:
            info = imu.probe()
            print(f"[BMI088] ACC CHIP_ID=0x{info.acc_chip_id:02X}  "
                  f"GYR CHIP_ID=0x{info.gyr_chip_id:02X}")
            print(f"         量程: ±{info.acc_range_g}g  /  ±{info.gyr_range_dps} dps")
            print(f"         GYR : {info.gyr_odr_hz} Hz ODR, {info.gyr_bw_hz} Hz BW")
            print(f"         SPI : {info.spi_hz/1e6:.2f} MHz  mode 3")
            if info.acc_chip_id != 0x1E or info.gyr_chip_id != 0x0F:
                print("[错误] CHIP_ID 不匹配，检查接线/拨动开关", file=sys.stderr)
                sys.exit(1)

            rate_desc = f"目标 {args.rate_hz:.0f} Hz" if args.rate_hz > 0 else "全速轮询"
            print(f"[采集] 时长 {args.duration}s，{rate_desc}")

            t0 = time.monotonic()
            t_next = t0
            t_print = t0
            n = 0
            while True:
                now = time.monotonic()
                if now - t0 >= args.duration:
                    break
                if dt_target > 0 and now < t_next:
                    time.sleep(max(0.0, t_next - now))
                    now = time.monotonic()
                ax, ay, az = imu.read_accel_m_s2()
                gx, gy, gz = imu.read_gyro_dps()
                t_rel = now - t0
                n += 1
                if writer is not None:
                    writer.writerow([
                        f"{t_rel:.6f}",
                        f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
                        f"{gx:.4f}", f"{gy:.4f}", f"{gz:.4f}",
                    ])
                if args.print_every == 0 or (now - t_print) >= args.print_every:
                    mag = math.sqrt(ax * ax + ay * ay + az * az)
                    print(
                        f"  t={t_rel:6.2f}s  "
                        f"acc=[{ax:+7.3f},{ay:+7.3f},{az:+7.3f}] m/s² |a|={mag:5.2f}  "
                        f"gyr=[{gx:+7.2f},{gy:+7.2f},{gz:+7.2f}] dps",
                        flush=True,
                    )
                    t_print = now
                if dt_target > 0:
                    t_next += dt_target

            dt = time.monotonic() - t0
            rate = n / dt if dt > 0 else 0.0
            print(f"\n[统计] 采样 {n} 次 / {dt:.3f}s = {rate:.1f} Hz (循环速率)")
            if csv_path is not None:
                print(f"[CSV ] {csv_path}")
    finally:
        if csv_file is not None:
            csv_file.close()


if __name__ == "__main__":
    main()
