"""达妙电机使能/失能/状态读取。

默认单次使能 → 读 3 帧状态 → 失能。
--hold N 保持使能 N 秒, 每 100ms 打印一帧状态 (测反馈连续性)。
"""
from __future__ import annotations

import argparse
import time

from device import DMMotor, open_bus, ERR_NAMES


def main():
    p = argparse.ArgumentParser(description="达妙电机使能/读状态/失能")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)
    p.add_argument("--hold", type=float, default=0.0,
                   help="保持使能秒数 (默认 0 = 单次使能后立即失能)")
    p.add_argument("--p-max", type=float, default=12.5)
    p.add_argument("--v-max", type=float, default=30.0)
    p.add_argument("--t-max", type=float, default=12.5)
    args = p.parse_args()

    bus = open_bus(channel="can0", bitrate=1_000_000)
    try:
        with DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                     p_max=args.p_max, v_max=args.v_max, t_max=args.t_max,
                     auto_enable=True) as motor:
            print(f"[ok] 已使能 motor_id=0x{args.motor_id:02X}")
            end = time.monotonic() + max(args.hold, 0.3)
            while time.monotonic() < end:
                state = motor.read_state(timeout=0.15)
                if state is None:
                    print("  (无反馈帧)")
                else:
                    err_name = ERR_NAMES.get(state.err_code, f"未知(0x{state.err_code:X})")
                    print(f"  pos={state.pos:+.4f} rad  vel={state.vel:+.4f} rad/s  "
                          f"tau={state.tau:+.4f} N·m  err={err_name}  "
                          f"T_mos={state.t_mos}°C  T_rotor={state.t_rotor}°C")
                time.sleep(0.1)
    finally:
        bus.shutdown()
    print("[ok] 已失能")


if __name__ == "__main__":
    main()
