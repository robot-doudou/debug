"""Servo 模式点控 (POS 或 SPEED)。

注意: 使用前电机需处于 Servo 模式 (通过 params.py 写 CTRL_MODE 寄存器, 或上位机配置)。
MIT 模式下发 Servo 帧电机会忽略。

--mode pos:    发 (pos, vel_feedforward) 到 0x100+motor_id
--mode speed:  发 vel 到 0x200+motor_id
"""
from __future__ import annotations

import argparse
import csv
import time

from device import (
    DMMotor, open_bus, output_dir, timestamped,
    SafetyLimits, SAFE_DEFAULTS, ERR_NAMES,
)


def main():
    p = argparse.ArgumentParser(description="Servo 模式点控")
    p.add_argument("--mode", choices=["pos", "speed"], required=True)
    p.add_argument("--target", type=float, required=True,
                   help="pos 模式: 目标 rad; speed 模式: 目标 rad/s")
    p.add_argument("--vel-ff", type=float, default=0.0,
                   help="pos 模式前馈速度 rad/s")
    p.add_argument("--duration", type=float, default=3.0)
    p.add_argument("--rate-hz", type=float, default=100.0)
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x00)
    p.add_argument("--p-max", type=float, default=12.5)
    p.add_argument("--v-max", type=float, default=30.0)
    p.add_argument("--t-max", type=float, default=10.0)
    p.add_argument("--unsafe", action="store_true")
    args = p.parse_args()

    safety = (SafetyLimits(tau=args.t_max, vel=args.v_max, pos=args.p_max,
                           kp=500.0, kd=5.0) if args.unsafe else SAFE_DEFAULTS)

    bus = open_bus(channel="can0", bitrate=1_000_000)
    samples = []
    try:
        with DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                     p_max=args.p_max, v_max=args.v_max, t_max=args.t_max,
                     safety=safety) as motor:
            state0 = motor.read_state(timeout=0.2)
            pos0 = state0.pos if state0 else 0.0
            target_pos = pos0 + args.target  # 相对起始位
            print(f"  起始 pos = {pos0:+.4f} rad, 目标 = "
                  f"{target_pos:+.4f} rad" if args.mode == "pos" else
                  f"  目标速度 = {args.target:+.4f} rad/s")

            dt = 1.0 / args.rate_hz
            t0 = time.monotonic()
            next_t = t0
            while True:
                now = time.monotonic()
                t_rel = now - t0
                if t_rel > args.duration:
                    break
                if args.mode == "pos":
                    motor.servo_pos(pos=target_pos, vel=args.vel_ff)
                else:
                    motor.servo_speed(vel=args.target)
                state = motor.read_state(timeout=dt * 0.5)
                if state is not None:
                    samples.append((t_rel, state.pos, state.vel, state.tau, state.err_code))
                next_t += dt
                sleep_for = next_t - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
    finally:
        bus.shutdown()

    if not samples:
        print("[warn] 无反馈样本")
        return

    out = output_dir()
    csv_path = out / timestamped(f"servo_{args.mode}", "csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "pos", "vel", "tau", "err"])
        for s in samples:
            w.writerow([f"{s[0]:.4f}"] + [f"{v:.6f}" if isinstance(v, float) else v for v in s[1:]])
    print(f"[ok] {csv_path}  ({len(samples)} 样本)")
    last = samples[-1]
    print(f"  末态: pos={last[1]:+.4f} vel={last[2]:+.4f} tau={last[3]:+.4f} "
          f"err={ERR_NAMES.get(last[4], '?')}")


if __name__ == "__main__":
    main()
