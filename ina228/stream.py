"""INA228 连续流: 实时打印 V/I/P/T + 统计采样率，可选保存 CSV。"""

import argparse
import csv
import pathlib
import sys
import time

from device import Ina228, output_dir, require_i2c, timestamped


def parse_args():
    p = argparse.ArgumentParser(description="INA228 连续遥测 / CSV 日志")
    p.add_argument("--duration", type=float, default=10.0, help="采集时长 (秒)")
    p.add_argument("--rate-hz", type=float, default=5.0,
                   help="目标采样率 (Hz)，默认 5 Hz")
    p.add_argument("--print-every", type=float, default=1.0,
                   help="终端打印间隔 (秒)，0 = 每个样本都打印")
    p.add_argument("--save", type=str, default="",
                   help="CSV 路径；空=不保存；'auto'=out/stream_TS.csv")
    p.add_argument("--bus", type=int, default=7)
    p.add_argument("--addr", type=lambda x: int(x, 0), default=0x40)
    p.add_argument("--r-shunt", type=float, default=0.002)
    p.add_argument("--i-max", type=float, default=100.0)
    p.add_argument("--adcrange", type=int, choices=[0, 1], default=0)
    return p.parse_args()


def main():
    args = parse_args()
    require_i2c(args.bus)

    csv_path: pathlib.Path | None = None
    csv_file = None
    writer = None
    if args.save:
        csv_path = (output_dir() / timestamped("stream", "csv")
                    if args.save == "auto"
                    else pathlib.Path(args.save))
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_file = open(csv_path, "w", newline="")
        writer = csv.writer(csv_file)
        writer.writerow(["t_s", "vbus_v", "current_a", "power_w",
                         "dietemp_c", "energy_j", "charge_c"])

    dt_target = 1.0 / args.rate_hz if args.rate_hz > 0 else 0.0

    try:
        with Ina228(
            bus=args.bus,
            address=args.addr,
            r_shunt_ohm=args.r_shunt,
            i_max_a=args.i_max,
            adcrange=args.adcrange,
        ) as ina:
            info = ina.probe()
            if info.manufacturer_id != 0x5449:
                print(f"[错误] MANUFACTURER_ID=0x{info.manufacturer_id:04X}",
                      file=sys.stderr)
                sys.exit(1)

            print(f"[INA228] bus={info.bus} addr=0x{info.address:02X}  "
                  f"R={info.r_shunt_ohm*1000:.3f} mΩ  "
                  f"CURRENT_LSB={info.current_lsb_a*1e6:.1f}µA  "
                  f"ADCRANGE={info.adcrange} "
                  f"(I_max={info.max_measurable_a:.1f}A)")
            print(f"[采集] 时长 {args.duration}s  目标 {args.rate_hz} Hz")

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

                vbus = ina.read_vbus_v()
                current = ina.read_current_a()
                power = ina.read_power_w()
                temp = ina.read_dietemp_c()
                energy = ina.read_energy_j()
                charge = ina.read_charge_c()
                t_rel = now - t0
                n += 1

                if writer is not None:
                    writer.writerow([f"{t_rel:.4f}", f"{vbus:.4f}",
                                     f"{current:.4f}", f"{power:.4f}",
                                     f"{temp:.3f}", f"{energy:.4f}",
                                     f"{charge:.4f}"])

                if args.print_every == 0 or (now - t_print) >= args.print_every:
                    print(f"  t={t_rel:6.2f}s  "
                          f"V={vbus:6.3f}V  "
                          f"I={current:+7.2f}A  "
                          f"P={power:7.2f}W  "
                          f"T={temp:5.1f}°C  "
                          f"E={energy:.2f}J",
                          flush=True)
                    t_print = now

                if dt_target > 0:
                    t_next += dt_target

            dt = time.monotonic() - t0
            rate = n / dt if dt > 0 else 0.0
            print(f"\n[统计] {n} 样本 / {dt:.2f}s = {rate:.2f} Hz")
            if csv_path is not None:
                print(f"[CSV ] {csv_path}")
    finally:
        if csv_file is not None:
            csv_file.close()


if __name__ == "__main__":
    main()
