"""INA228 单次读取: 电压 / 电流 / 功率 / 温度 / 累积能量 / 累积电量。

默认按豆豆 6S + R002 + I_MAX=100A 配置。换电阻 / 量程通过 CLI 覆盖。
"""

import argparse
import sys

from device import Ina228, require_i2c


def parse_args():
    p = argparse.ArgumentParser(description="INA228 一次性读数")
    p.add_argument("--bus", type=int, default=7)
    p.add_argument("--addr", type=lambda x: int(x, 0), default=0x40)
    p.add_argument("--r-shunt", type=float, default=0.002,
                   help="分流电阻值 Ω (默认 0.002 = R002)")
    p.add_argument("--i-max", type=float, default=100.0,
                   help="期望最大电流 A (决定 CURRENT_LSB)")
    p.add_argument("--adcrange", type=int, choices=[0, 1], default=0,
                   help="0=±163.84mV (默认), 1=±40.96mV 高精度小量程")
    p.add_argument("--no-reset", action="store_true",
                   help="不软复位 (保留已累积的 ENERGY/CHARGE)")
    return p.parse_args()


def main():
    args = parse_args()
    require_i2c(args.bus)

    with Ina228(
        bus=args.bus,
        address=args.addr,
        r_shunt_ohm=args.r_shunt,
        i_max_a=args.i_max,
        adcrange=args.adcrange,
        reset=not args.no_reset,
    ) as ina:
        info = ina.probe()
        if info.manufacturer_id != 0x5449:
            print(f"[错误] MANUFACTURER_ID=0x{info.manufacturer_id:04X} != 0x5449",
                  file=sys.stderr)
            sys.exit(1)

        print(f"[INA228] bus={info.bus}  addr=0x{info.address:02X}  "
              f"rev=0x{info.device_id & 0xF:X}")
        print(f"         R_SHUNT     : {info.r_shunt_ohm*1000:.3f} mΩ")
        print(f"         CURRENT_LSB : {info.current_lsb_a*1e6:.2f} µA/LSB")
        print(f"         SHUNT_CAL   : {info.shunt_cal} (0x{info.shunt_cal:04X})")
        print(f"         ADCRANGE    : {info.adcrange} "
              f"({'±163.84 mV' if info.adcrange == 0 else '±40.96 mV'})")
        print(f"         I 可测最大  : {info.max_measurable_a:.2f} A "
              f"(受 ADC 硬限)")

        # 给芯片一次采样的时间 (默认 ADC_CONFIG 每通道 1052 µs × 3 ≈ 3 ms)
        import time; time.sleep(0.01)

        vbus = ina.read_vbus_v()
        vshunt = ina.read_vshunt_v()
        current = ina.read_current_a()
        power = ina.read_power_w()
        temp = ina.read_dietemp_c()
        energy = ina.read_energy_j()
        charge = ina.read_charge_c()

        print()
        print(f"  VBUS         : {vbus:7.3f} V")
        print(f"  VSHUNT       : {vshunt*1000:7.3f} mV  "
              f"(= {current:+7.2f} A 算出)")
        print(f"  CURRENT      : {current:+7.3f} A")
        print(f"  POWER        : {power:7.2f} W")
        print(f"  DIETEMP      : {temp:6.2f} °C")
        print(f"  ENERGY (累积): {energy:.3f} J  (= {energy/3600:.6f} Wh)")
        print(f"  CHARGE (累积): {charge:+.3f} C  (= {charge/3.6:.6f} mAh)")

        if abs(current) >= info.max_measurable_a * 0.95:
            print(f"\n  ⚠ 电流接近 ADC 硬限幅 ({info.max_measurable_a:.1f} A)，"
                  f"读数可能被截断")


if __name__ == "__main__":
    main()
