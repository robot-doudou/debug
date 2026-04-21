"""BMI088 IMU 测试: 采样率 / 重力模长 / 陀螺零偏 / 姿态 — 对齐 realsense/imu.py。

静置设备几秒钟，脚本判断:
    - 加速度模长 ≈ 9.81 m/s² (容差 ±0.5)
    - 陀螺仪模长 < 1 dps
    - 加速度主导轴 / 相对重力倾角 (粗略姿态)
"""

import argparse
import math
import sys
import time

import numpy as np

from device import Bmi088, GRAVITY, require_spidev


def parse_args():
    p = argparse.ArgumentParser(description="BMI088 IMU 全面测试")
    p.add_argument("--duration", type=float, default=5.0, help="采集时长 (秒)")
    p.add_argument("--spi-hz", type=int, default=1_000_000, help="SPI 时钟")
    p.add_argument("--acc-range", type=int, choices=[3, 6, 12, 24], default=6)
    p.add_argument("--gyr-range", type=int, choices=[2000, 1000, 500, 250, 125],
                   default=500)
    p.add_argument("--gyr-odr", type=int, choices=[2000, 1000, 400, 200, 100],
                   default=400,
                   help="GYR ODR/带宽预设 (Hz)。对应内部滤波: "
                        "2000→532BW, 1000→116BW, 400→47BW ⭐, 200→23BW, 100→12BW")
    p.add_argument("--bus", type=int, default=0)
    p.add_argument("--acc-cs", type=int, default=0)
    p.add_argument("--gyr-cs", type=int, default=1)
    return p.parse_args()


def collect(imu: Bmi088, duration: float) -> tuple[np.ndarray, np.ndarray]:
    accel: list[tuple[float, float, float, float]] = []
    gyro: list[tuple[float, float, float, float]] = []
    t0 = time.monotonic()
    while True:
        t = time.monotonic() - t0
        if t >= duration:
            break
        ax, ay, az = imu.read_accel_m_s2()
        gx, gy, gz = imu.read_gyro_dps()
        accel.append((t, ax, ay, az))
        gyro.append((t, gx, gy, gz))
    return np.asarray(accel), np.asarray(gyro)


def report(name: str, samples: np.ndarray, unit: str) -> None:
    if samples.size == 0:
        print(f"[{name}] 未收到样本")
        return
    ts = samples[:, 0]
    xyz = samples[:, 1:]
    dur = ts[-1] - ts[0] if len(ts) > 1 else 0.0
    rate = (len(ts) - 1) / dur if dur > 0 else 0.0
    mean = xyz.mean(axis=0)
    std = xyz.std(axis=0)
    mag = np.linalg.norm(xyz, axis=1).mean()

    print(f"\n--- {name} ---")
    print(f"  样本数     : {len(ts)}")
    print(f"  时长       : {dur:.3f} s")
    print(f"  循环速率   : {rate:.1f} Hz")
    print(f"  均值 (xyz) : [{mean[0]:+7.4f}, {mean[1]:+7.4f}, {mean[2]:+7.4f}] {unit}")
    print(f"  标准差     : [{std[0]:.4f}, {std[1]:.4f}, {std[2]:.4f}] {unit}")
    print(f"  向量模长均值: {mag:.4f} {unit}")


def orientation_from_accel(a: np.ndarray) -> str:
    """根据静止时 ACC 三轴均值估计主导轴和倾角。

    BMI088 坐标系由模块丝印箭头确定 (参考芯片 datasheet)。
    主导轴符号 + 绝对值最大者，粗略反映"哪个面朝下"。
    """
    mag = float(np.linalg.norm(a))
    if mag < 1.0:
        return "(信号过小，无法估算)"
    idx = int(np.argmax(np.abs(a)))
    sign = "+" if a[idx] > 0 else "-"
    axis = "XYZ"[idx]
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, abs(a[idx]) / mag))))
    return f"主导轴 {sign}{axis}，偏离该轴 {tilt:.1f}°  (静置时该轴应接近 ±g)"


def main():
    args = parse_args()
    require_spidev(bus=args.bus, cs_list=(args.acc_cs, args.gyr_cs))

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
        print(f"[BMI088] ACC CHIP_ID=0x{info.acc_chip_id:02X} (期望 0x1E)  "
              f"GYR CHIP_ID=0x{info.gyr_chip_id:02X} (期望 0x0F)")
        print(f"         量程 ±{info.acc_range_g}g  /  ±{info.gyr_range_dps} dps   "
              f"GYR {info.gyr_odr_hz} Hz/{info.gyr_bw_hz} BW   "
              f"SPI {info.spi_hz/1e6:.2f} MHz")
        if info.acc_chip_id != 0x1E or info.gyr_chip_id != 0x0F:
            print("[错误] CHIP_ID 不匹配，检查接线/拨动开关 (见 README)", file=sys.stderr)
            sys.exit(1)

        print(f"[采集] 时长 {args.duration}s，保持设备静止 ...")
        accel, gyro = collect(imu, args.duration)

    report("Accel (m/s²)", accel, "m/s²")
    report("Gyro (dps)", gyro, "dps")

    if accel.size > 0:
        mean = accel[:, 1:].mean(axis=0)
        mag = float(np.linalg.norm(mean))
        drift = abs(mag - GRAVITY)
        print("\n--- 重力检查 ---")
        print(f"  期望模长 : {GRAVITY:.4f} m/s²")
        print(f"  实测模长 : {mag:.4f} m/s²  (偏差 {drift:.4f})")
        print("  [OK] 在容差内" if drift <= 0.5
              else "  [警告] 偏差 >0.5，检查是否静止 / 量程配置")
        print(f"\n--- 姿态估计 ---\n  {orientation_from_accel(mean)}")

    if gyro.size > 0:
        gyr_mean = gyro[:, 1:].mean(axis=0)
        gyr_bias = float(np.linalg.norm(gyr_mean))
        print("\n--- 陀螺零偏 (静止) ---")
        print(f"  均值 (xyz) : [{gyr_mean[0]:+7.4f}, {gyr_mean[1]:+7.4f}, "
              f"{gyr_mean[2]:+7.4f}] dps")
        print(f"  模长       : {gyr_bias:.4f} dps")
        print("  [OK] 零偏正常" if gyr_bias < 1.0
              else "  [警告] 零偏 >1 dps，静置几秒再测或做标定")


if __name__ == "__main__":
    main()
