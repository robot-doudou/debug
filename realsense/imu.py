"""D435i IMU 测试: 读取 accel / gyro，检查采样率、重力大小、姿态。

D435i IMU 是 Bosch BMI055，通常支持:
    accel: 63 Hz / 250 Hz
    gyro : 200 Hz / 400 Hz

原始数据单位:
    accel: m/s² (静止时应接近 9.8)
    gyro : rad/s
"""

import argparse
import math
import sys
import time

import numpy as np
import pyrealsense2 as rs

from device import clean_exit, require_device

GRAVITY = 9.80665


def parse_args():
    p = argparse.ArgumentParser(description="RealSense D435i IMU 测试")
    p.add_argument("--duration", type=float, default=5.0, help="采集时长(秒)")
    p.add_argument("--accel-rate", type=int, default=250, help="accel 采样率 (63 或 250)")
    p.add_argument("--gyro-rate", type=int, default=200, help="gyro 采样率 (200 或 400)")
    return p.parse_args()


def collect(pipeline: rs.pipeline, duration: float):
    accel_samples = []  # (t, x, y, z)
    gyro_samples = []
    t_start = time.time()

    while time.time() - t_start < duration:
        frames = pipeline.wait_for_frames()
        for f in frames:
            prof = f.get_profile()
            if not f.is_motion_frame():
                continue
            mf = f.as_motion_frame()
            v = mf.get_motion_data()
            ts = mf.get_timestamp() / 1000.0  # ms -> s
            sample = (ts, v.x, v.y, v.z)
            if prof.stream_type() == rs.stream.accel:
                accel_samples.append(sample)
            elif prof.stream_type() == rs.stream.gyro:
                gyro_samples.append(sample)

    return np.array(accel_samples), np.array(gyro_samples)


def report(name: str, samples: np.ndarray, unit: str, expected_rate: int):
    if samples.size == 0:
        print(f"[{name}] 未收到任何样本")
        return
    ts = samples[:, 0]
    xyz = samples[:, 1:]
    duration = ts[-1] - ts[0] if len(ts) > 1 else 0.0
    rate = (len(ts) - 1) / duration if duration > 0 else 0.0
    mean = xyz.mean(axis=0)
    std = xyz.std(axis=0)
    mag = np.linalg.norm(xyz, axis=1).mean()

    print(f"\n--- {name} ---")
    print(f"  样本数     : {len(ts)}")
    print(f"  时长       : {duration:.3f} s")
    print(f"  实测采样率 : {rate:.1f} Hz   (期望 ~{expected_rate} Hz)")
    print(f"  均值 (xyz) : [{mean[0]:+7.4f}, {mean[1]:+7.4f}, {mean[2]:+7.4f}] {unit}")
    print(f"  标准差     : [{std[0]:.4f}, {std[1]:.4f}, {std[2]:.4f}] {unit}")
    print(f"  向量模长均值: {mag:.4f} {unit}")


def orientation_from_accel(accel_mean: np.ndarray) -> str:
    """从 accel 均值估算相机相对重力的粗略姿态。

    RealSense IMU 坐标系 (官方文档):
        X 向右, Y 向下, Z 向前
    静止平放时重力分量应集中在 +Y 方向 (约 +9.8 m/s²)。
    """
    ax, ay, az = accel_mean
    mag = math.sqrt(ax * ax + ay * ay + az * az)
    if mag < 1.0:
        return "(信号过小，无法估算)"

    # 与重力向量 (0, g, 0) 的夹角
    tilt_deg = math.degrees(math.acos(max(-1.0, min(1.0, ay / mag))))

    direction = "未知"
    dominant = np.argmax(np.abs(accel_mean))
    sign = "+" if accel_mean[dominant] > 0 else "-"
    axis = "XYZ"[dominant]
    direction = f"{sign}{axis}"

    hint = {
        "+Y": "平放 (镜头朝前，正常姿态)",
        "-Y": "倒置",
        "+X": "左侧朝下",
        "-X": "右侧朝下",
        "+Z": "镜头朝上",
        "-Z": "镜头朝下",
    }.get(direction, "")

    return f"主方向 {direction}，相对重力倾角 {tilt_deg:.1f}°  {hint}"


def main():
    args = parse_args()
    _, dev_info = require_device()
    print(f"[设备] {dev_info['name']} (SN: {dev_info['serial']})")

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.accel, rs.format.motion_xyz32f, args.accel_rate)
    config.enable_stream(rs.stream.gyro, rs.format.motion_xyz32f, args.gyro_rate)

    try:
        pipeline.start(config)
    except RuntimeError as e:
        print(f"[错误] IMU 流启动失败: {e}", file=sys.stderr)
        print("  - 确认设备是 D435i (D435 无 IMU)", file=sys.stderr)
        print("  - 尝试 --accel-rate 63 / --gyro-rate 400", file=sys.stderr)
        sys.exit(1)

    try:
        print(f"[采集] 时长 {args.duration}s，保持设备静止...")
        accel, gyro = collect(pipeline, args.duration)
    finally:
        pipeline.stop()

    report("Accel (m/s²)", accel, "m/s²", args.accel_rate)
    report("Gyro (rad/s)", gyro, "rad/s", args.gyro_rate)

    if accel.size > 0:
        mean = accel[:, 1:].mean(axis=0)
        mag = np.linalg.norm(mean)
        drift = abs(mag - GRAVITY)
        print("\n--- 重力检查 ---")
        print(f"  期望模长 : {GRAVITY:.4f} m/s²")
        print(f"  实测模长 : {mag:.4f} m/s²  (偏差 {drift:.4f})")
        if drift > 0.5:
            print("  [警告] 偏差较大，检查设备是否静止或需要标定")
        else:
            print("  [OK] 重力模长正常")
        print(f"\n--- 姿态估计 ---\n  {orientation_from_accel(mean)}")

    if gyro.size > 0:
        gyro_mag = np.linalg.norm(gyro[:, 1:].mean(axis=0))
        print("\n--- 陀螺零偏 ---")
        print(f"  静止时 gyro 均值模长: {gyro_mag:.5f} rad/s")
        if gyro_mag > 0.05:
            print("  [警告] 零偏较大 (>0.05 rad/s)，若静止则可能需要标定")
        else:
            print("  [OK] 零偏在正常范围")


if __name__ == "__main__":
    main()
    clean_exit(0)
