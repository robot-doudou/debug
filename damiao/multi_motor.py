"""多电机扫描 / 调试 (12 电机四足配置)。

ID 映射（与 README "多电机配置" 章节一致）:
    leg ∈ {FL, FR, RL, RR},  joint ∈ {HAA, HFE, KFE}
    motor_id  = leg_idx * 3 + joint_idx + 1     →  0x01..0x0C
    master_id = motor_id + 0x10                 →  0x11..0x1C

用法:
    # 探活: 对每颗电机发 clear_error, 等回复, 报告 alive/dead
    uv run multi_motor.py --scan

    # 限定腿: --leg FL,FR (默认 ALL)
    uv run multi_motor.py --scan --leg FL

    # 限定关节: --joint HAA (默认 ALL)
    uv run multi_motor.py --scan --joint HAA

    # 读状态: 对每颗电机短暂使能 + poll 一次 + 失能 (使能用 SAFE_DEFAULTS, 零力矩)
    uv run multi_motor.py --read

    # 持续读: 全部使能 N 秒, 每 100ms 轮询一遍, 退出时全部失能
    uv run multi_motor.py --read --hold 5
"""
from __future__ import annotations

import argparse
import sys
import time

from device import DMMotor, open_bus, ERR_NAMES

LEGS = ["FL", "FR", "RL", "RR"]
JOINTS = ["HAA", "HFE", "KFE"]


def motor_map(legs: list[str], joints: list[str]) -> list[tuple[str, str, int, int]]:
    """返回 [(leg, joint, motor_id, master_id), ...] 按腿 × 关节展开。"""
    out = []
    for leg_idx, leg in enumerate(LEGS):
        if leg not in legs:
            continue
        for joint_idx, joint in enumerate(JOINTS):
            if joint not in joints:
                continue
            mid = leg_idx * 3 + joint_idx + 1
            out.append((leg, joint, mid, mid + 0x10))
    return out


def scan(bus, motors: list[tuple[str, str, int, int]]) -> dict[tuple[str, str], dict | None]:
    """对每颗电机发 clear_error 等反馈, 返回 {(leg,joint): state_dict 或 None}。"""
    results = {}
    for leg, joint, mid, master in motors:
        m = DMMotor(bus, motor_id=mid, master_id=master, auto_enable=False)
        m.clear_error()
        st = m.read_state(timeout=0.2)
        results[(leg, joint)] = (
            None
            if st is None
            else {
                "pos": st.pos, "vel": st.vel, "tau": st.tau,
                "err": st.err_code,
                "t_mos": st.t_mos, "t_rotor": st.t_rotor,
            }
        )
    return results


def print_scan_report(motors: list[tuple[str, str, int, int]],
                      results: dict[tuple[str, str], dict | None]):
    print(f"{'name':<8}  {'mot_id':>6}  {'mst_id':>6}  status")
    print("-" * 70)
    n_alive = 0
    for leg, joint, mid, master in motors:
        key = (leg, joint)
        st = results.get(key)
        name = f"{leg}_{joint}"
        if st is None:
            line = f"  [DEAD]"
        else:
            err_name = ERR_NAMES.get(st["err"], f"未知(0x{st['err']:X})")
            line = (f"  [OK] pos={st['pos']:+.3f}  vel={st['vel']:+.3f}  "
                    f"tau={st['tau']:+.3f}  err={err_name}  "
                    f"T_mos={st['t_mos']}°C  T_rotor={st['t_rotor']}°C")
            n_alive += 1
        print(f"{name:<8}  0x{mid:02X}    0x{master:02X}  {line}")
    print("-" * 70)
    print(f"  {n_alive}/{len(motors)} 颗活")


def read_loop(bus, motors: list[tuple[str, str, int, int]], hold: float, rate_hz: float = 10.0):
    """全部使能, 持续 hold 秒每周期 poll 一遍 state, 退出时全部失能。

    使用 with-block 顺序进出, 异常或 Ctrl-C 时无条件 disable 所有已使能电机。
    """
    objs = []
    try:
        # 顺序使能 (clear_error → enable)
        for leg, joint, mid, master in motors:
            m = DMMotor(bus, motor_id=mid, master_id=master, auto_enable=False)
            m.clear_error()
            # 先 ping 一下确认存活, 不存活就跳过 (不计入 enable 列表)
            ping = m.read_state(timeout=0.15)
            if ping is None:
                print(f"  [skip] {leg}_{joint} (0x{mid:02X}) 无反馈, 跳过")
                continue
            m.enable()
            objs.append((leg, joint, m))
            print(f"  [enable] {leg}_{joint} (0x{mid:02X})")
        if not objs:
            print("[warn] 没有活的电机, 退出")
            return

        print(f"\n=== poll {len(objs)} 颗电机 {hold} 秒, {rate_hz} Hz ===")
        end = time.monotonic() + hold
        dt = 1.0 / rate_hz
        next_t = time.monotonic()
        cycle = 0
        while time.monotonic() < end:
            cycle += 1
            print(f"\n[cycle {cycle:>3} t={time.monotonic()-next_t+dt:.2f}s]")
            for leg, joint, m in objs:
                # no-force MIT poll → 拿一帧 state
                m.mit_cmd(pos=0, vel=0, kp=0, kd=0, tau=0)
                st = m.read_state(timeout=0.03)
                tag = f"{leg}_{joint}"
                if st is None:
                    print(f"  {tag:<8} (无帧)")
                else:
                    err_name = ERR_NAMES.get(st.err_code, f"0x{st.err_code:X}")
                    print(f"  {tag:<8} pos={st.pos:+7.3f}  vel={st.vel:+7.3f}  "
                          f"tau={st.tau:+6.3f}  err={err_name}")
            next_t += dt
            sleep_for = next_t - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        # 无条件 disable 所有已使能电机
        print("\n=== 失能 ===")
        for leg, joint, m in objs:
            try:
                m.disable()
                print(f"  [disable] {leg}_{joint}")
            except Exception as e:
                print(f"  [警告] {leg}_{joint} disable 失败: {e}", file=sys.stderr)


def parse_csv(s: str, valid: list[str], name: str) -> list[str]:
    if s.upper() == "ALL":
        return list(valid)
    out = [x.strip().upper() for x in s.split(",") if x.strip()]
    bad = [x for x in out if x not in valid]
    if bad:
        raise argparse.ArgumentTypeError(f"未知 {name}: {bad} (合法值: {valid})")
    return out


def main():
    p = argparse.ArgumentParser(
        description="多电机扫描/调试 (12 电机四足配置)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法:", 1)[1] if "用法:" in __doc__ else "",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scan", action="store_true",
                   help="探活: clear_error → 读一帧 → 报告")
    g.add_argument("--read", action="store_true",
                   help="使能 + poll N 秒 (--hold) → 失能")

    p.add_argument("--leg", type=lambda s: parse_csv(s, LEGS, "leg"),
                   default=LEGS, metavar="FL[,FR,RL,RR]",
                   help=f"限定腿 (默认 ALL = {','.join(LEGS)})")
    p.add_argument("--joint", type=lambda s: parse_csv(s, JOINTS, "joint"),
                   default=JOINTS, metavar="HAA[,HFE,KFE]",
                   help=f"限定关节 (默认 ALL = {','.join(JOINTS)})")
    p.add_argument("--hold", type=float, default=3.0,
                   help="--read 模式下的 poll 秒数 (默认 3)")
    p.add_argument("--rate-hz", type=float, default=10.0,
                   help="--read 模式下的 poll 频率 (默认 10 Hz)")
    args = p.parse_args()

    motors = motor_map(args.leg, args.joint)
    if not motors:
        print("[错误] 选定的 leg × joint 没有电机", file=sys.stderr)
        sys.exit(1)

    print(f"=== 配置: {len(motors)} 颗电机 ({','.join(args.leg)} × {','.join(args.joint)}) ===")

    bus = open_bus(channel="can0", bitrate=1_000_000)
    try:
        if args.scan:
            results = scan(bus, motors)
            print_scan_report(motors, results)
        elif args.read:
            read_loop(bus, motors, hold=args.hold, rate_hz=args.rate_hz)
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
