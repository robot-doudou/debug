"""MIT 模式点控测试。

profiles:
  step  — 0 → target 阶跃
  sine  — pos = amp * sin(2π f t), 默认 amp=0.5 rad, f=0.5 Hz
  hold  — 保持初始位置, 观察扰动响应 (手指拨动轴)

安全默认 (SAFE_DEFAULTS): tau≤1 N·m, vel≤5 rad/s, pos≤±π, kp≤20, kd≤1
--unsafe 放开到硬件上限 (p_max/v_max/t_max/500/5)

输出:
  out/mit_<profile>_<ts>.csv   t, pos, vel, tau, pos_cmd, vel_cmd, tau_cmd, err
  out/mit_<profile>_<ts>.png   4 子图 (pos, vel, tau vs 时间, err 码)
  --live 弹 matplotlib 实时窗, 关窗后同时落 CSV+PNG; 无 DISPLAY 自动降级
"""
from __future__ import annotations

import argparse
import csv
import math
import time
from dataclasses import dataclass, field

import numpy as np

from device import (
    DMMotor, open_bus, output_dir, timestamped,
    SafetyLimits, SAFE_DEFAULTS, has_display, ERR_NAMES,
)


@dataclass
class Sample:
    t: float
    pos: float
    vel: float
    tau: float
    pos_cmd: float
    vel_cmd: float
    tau_cmd: float
    err: int


@dataclass
class Trace:
    samples: list[Sample] = field(default_factory=list)

    def add(self, s: Sample): self.samples.append(s)

    def arrays(self):
        t = np.array([s.t for s in self.samples])
        return {
            "t": t,
            "pos": np.array([s.pos for s in self.samples]),
            "vel": np.array([s.vel for s in self.samples]),
            "tau": np.array([s.tau for s in self.samples]),
            "pos_cmd": np.array([s.pos_cmd for s in self.samples]),
            "vel_cmd": np.array([s.vel_cmd for s in self.samples]),
            "tau_cmd": np.array([s.tau_cmd for s in self.samples]),
            "err": np.array([s.err for s in self.samples]),
        }


def profile_step(t: float, pos0: float, target: float, t_step: float = 0.5):
    return (pos0 if t < t_step else target), 0.0, 0.0


def profile_sine(t: float, pos0: float, amp: float, freq: float):
    pos = pos0 + amp * math.sin(2 * math.pi * freq * t)
    vel = amp * 2 * math.pi * freq * math.cos(2 * math.pi * freq * t)
    return pos, vel, 0.0


def profile_hold(t: float, pos0: float):
    return pos0, 0.0, 0.0


def run_control_loop(motor: DMMotor, profile_fn, duration: float,
                     kp: float, kd: float, rate_hz: float = 200.0,
                     live_callback=None) -> Trace:
    """控制循环: rate_hz 发命令, 每次循环读一帧反馈。"""
    trace = Trace()
    dt = 1.0 / rate_hz
    t0 = time.monotonic()
    state0 = motor.read_state(timeout=0.2)
    pos0 = state0.pos if state0 else 0.0
    print(f"  起始 pos = {pos0:+.4f} rad")

    next_t = t0
    while True:
        now = time.monotonic()
        t_rel = now - t0
        if t_rel > duration:
            break
        pos_cmd, vel_cmd, tau_cmd = profile_fn(t_rel, pos0)
        motor.mit_cmd(pos=pos_cmd, vel=vel_cmd, kp=kp, kd=kd, tau=tau_cmd)
        state = motor.read_state(timeout=dt * 0.5)
        if state is not None:
            s = Sample(
                t=t_rel, pos=state.pos, vel=state.vel, tau=state.tau,
                pos_cmd=pos_cmd, vel_cmd=vel_cmd, tau_cmd=tau_cmd,
                err=state.err_code,
            )
            trace.add(s)
            if live_callback is not None:
                live_callback(s)
        next_t += dt
        sleep_for = next_t - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
    return trace


def save_csv(trace: Trace, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "pos", "vel", "tau", "pos_cmd", "vel_cmd", "tau_cmd", "err"])
        for s in trace.samples:
            w.writerow([f"{s.t:.4f}", f"{s.pos:.6f}", f"{s.vel:.6f}", f"{s.tau:.6f}",
                        f"{s.pos_cmd:.6f}", f"{s.vel_cmd:.6f}", f"{s.tau_cmd:.6f}", s.err])


def save_png(trace: Trace, path, title: str):
    import matplotlib.pyplot as plt
    a = trace.arrays()
    fig, axes = plt.subplots(4, 1, figsize=(10, 10), sharex=True)
    axes[0].plot(a["t"], a["pos_cmd"], label="cmd", linestyle="--")
    axes[0].plot(a["t"], a["pos"], label="actual")
    axes[0].set_ylabel("pos (rad)"); axes[0].legend(); axes[0].grid()
    axes[1].plot(a["t"], a["vel_cmd"], label="cmd", linestyle="--")
    axes[1].plot(a["t"], a["vel"], label="actual")
    axes[1].set_ylabel("vel (rad/s)"); axes[1].legend(); axes[1].grid()
    axes[2].plot(a["t"], a["tau_cmd"], label="cmd", linestyle="--")
    axes[2].plot(a["t"], a["tau"], label="actual")
    axes[2].set_ylabel("tau (N·m)"); axes[2].legend(); axes[2].grid()
    axes[3].step(a["t"], a["err"], where="post")
    axes[3].set_ylabel("err code"); axes[3].set_xlabel("t (s)"); axes[3].grid()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run_live(profile_fn, duration, motor, kp, kd, rate_hz) -> Trace:
    """matplotlib FuncAnimation 实时窗 + 数据落盘。"""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    trace = Trace()
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    lines = {
        "pos_cmd": axes[0].plot([], [], "--", label="cmd")[0],
        "pos":     axes[0].plot([], [], label="actual")[0],
        "vel_cmd": axes[1].plot([], [], "--", label="cmd")[0],
        "vel":     axes[1].plot([], [], label="actual")[0],
        "tau_cmd": axes[2].plot([], [], "--", label="cmd")[0],
        "tau":     axes[2].plot([], [], label="actual")[0],
    }
    for ax, name in zip(axes, ("pos (rad)", "vel (rad/s)", "tau (N·m)")):
        ax.set_ylabel(name); ax.legend(); ax.grid()
    axes[-1].set_xlabel("t (s)")

    stop = {"v": False}

    def on_close(_event):
        stop["v"] = True
    fig.canvas.mpl_connect("close_event", on_close)

    import threading
    def worker():
        run_control_loop(motor, profile_fn, duration, kp, kd, rate_hz,
                         live_callback=trace.add)
        stop["v"] = True

    th = threading.Thread(target=worker, daemon=True)
    th.start()

    def update(_frame):
        a = trace.arrays() if trace.samples else None
        if a is not None:
            for key, line in lines.items():
                line.set_data(a["t"], a[key])
            for ax in axes:
                ax.relim(); ax.autoscale_view()
        if stop["v"]:
            plt.close(fig)
        return list(lines.values())

    _anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    plt.show()
    th.join(timeout=1.0)
    return trace


def main():
    p = argparse.ArgumentParser(description="MIT 模式点控测试")
    p.add_argument("--profile", choices=["step", "sine", "hold"], default="sine")
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--rate-hz", type=float, default=200.0)
    p.add_argument("--kp", type=float, default=10.0)
    p.add_argument("--kd", type=float, default=0.5)
    p.add_argument("--target", type=float, default=0.5, help="step 目标 pos (rad)")
    p.add_argument("--amp", type=float, default=0.5, help="sine 幅值 (rad)")
    p.add_argument("--freq", type=float, default=0.5, help="sine 频率 (Hz)")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x11)
    p.add_argument("--p-max", type=float, default=12.5)
    p.add_argument("--v-max", type=float, default=30.0)
    p.add_argument("--t-max", type=float, default=7.0)
    p.add_argument("--unsafe", action="store_true",
                   help="放开软限幅到硬件上限")
    p.add_argument("--live", action="store_true",
                   help="弹实时 matplotlib 窗口 (无 DISPLAY 自动降级)")
    args = p.parse_args()

    if args.unsafe:
        safety = SafetyLimits(tau=args.t_max, vel=args.v_max, pos=args.p_max,
                              kp=500.0, kd=5.0)
    else:
        safety = SAFE_DEFAULTS

    kp = safety.clamp_kp(args.kp)
    kd = safety.clamp_kd(args.kd)
    if (kp, kd) != (args.kp, args.kd):
        print(f"[info] kp/kd 被安全限幅钳制: ({args.kp}, {args.kd}) → ({kp}, {kd})")

    def profile_fn(t, pos0):
        if args.profile == "step":  return profile_step(t, pos0, pos0 + args.target)
        if args.profile == "sine":  return profile_sine(t, pos0, args.amp, args.freq)
        return profile_hold(t, pos0)

    use_live = args.live and has_display()
    if args.live and not use_live:
        print("[info] --live 请求但无 DISPLAY, 降级为静态输出")

    bus = open_bus(channel="can0", bitrate=1_000_000)
    try:
        with DMMotor(bus, motor_id=args.motor_id, master_id=args.master_id,
                     p_max=args.p_max, v_max=args.v_max, t_max=args.t_max,
                     safety=safety) as motor:
            if use_live:
                trace = run_live(profile_fn, args.duration, motor, kp, kd, args.rate_hz)
            else:
                trace = run_control_loop(motor, profile_fn, args.duration, kp, kd,
                                         args.rate_hz)
    finally:
        bus.shutdown()

    if not trace.samples:
        print("[warn] 无数据样本, 不落盘")
        return

    out = output_dir()
    csv_name = timestamped(f"mit_{args.profile}", "csv")
    png_name = timestamped(f"mit_{args.profile}", "png")
    csv_path = out / csv_name
    png_path = out / png_name
    save_csv(trace, csv_path)
    save_png(trace, png_path, title=f"MIT {args.profile} kp={kp} kd={kd}")
    print(f"[ok] {csv_path}")
    print(f"[ok] {png_path}")


if __name__ == "__main__":
    main()
