"""INA228 6S LiPo 3000 mAh 电量 (SoC) 估算 — 全自动，无需指定充满与否.

算法:
  启动:  采 2s VBUS+I 均值。|I|<1A 静置 → OCV 查表定 SoC (IR 压降可忽略)。
         带载启动时降级到: 状态文件 < 10 min 且 CHARGE 连续则 resume，否则
         退化 OCV (负载下电压压降会低估电量，打印警告)。
  运行:  INA228 CHARGE 寄存器硬件积分 ∫I dt，SoC = SoC_init - ΔQ / 容量。
  再锚定: |I|<1A 持续 30s → OCV 查表复核；与 CC 差 >5% 才重锚 (避免抖动)。
  持久化: out/soc_state.json 每 60s 保存 + SIGINT/SIGTERM 立即保存。
  ETA:    最近 30s 电流滚动均值外推剩余时间。

用法:
  uv run soc.py                 # 持续运行直到 Ctrl+C
  uv run soc.py --duration 60   # 跑 60s 退出 (测试用)
  uv run soc.py --print-every 1 # 每秒一行输出
"""

import argparse
import collections
import json
import pathlib
import signal
import sys
import time
from dataclasses import asdict, dataclass

from device import Ina228, output_dir, require_i2c


# ---- 豆豆电池 (可改) ----
CELLS = 6
CAPACITY_MAH = 3000
CAPACITY_C = CAPACITY_MAH * 3.6  # 3000 mAh × 3.6 C/mAh = 10800 C

# LiPo per-cell OCV → SoC% (~0.2C 放电标准曲线)
OCV_CURVE = [
    (4.20, 100.0), (4.15,  95.0), (4.11,  90.0), (4.08,  85.0),
    (4.02,  80.0), (3.98,  75.0), (3.95,  70.0), (3.91,  65.0),
    (3.87,  60.0), (3.85,  55.0), (3.84,  50.0), (3.82,  45.0),
    (3.80,  40.0), (3.79,  35.0), (3.77,  30.0), (3.75,  25.0),
    (3.73,  20.0), (3.71,  15.0), (3.69,  10.0), (3.61,   5.0),
    (3.27,   0.0),
]

REST_I_A = 1.0              # |I| 低于此值算静置
REST_DURATION_S = 30.0      # 持续静置 30s 才触发再锚定
STARTUP_SAMPLE_S = 2.0      # 启动采样时长
SAVE_INTERVAL_S = 60.0      # 持久化周期
RECAL_DELTA_PCT = 5.0       # OCV vs CC 差异 >此值才接受再锚定
LOOP_DT = 0.1               # 主循环间隔


def ocv_to_soc(vbus: float) -> float:
    """6S LiPo 电压 → SoC% (线性插值查表)。"""
    v_cell = vbus / CELLS
    if v_cell >= OCV_CURVE[0][0]:
        return 100.0
    if v_cell <= OCV_CURVE[-1][0]:
        return 0.0
    for (v_hi, s_hi), (v_lo, s_lo) in zip(OCV_CURVE, OCV_CURVE[1:]):
        if v_hi >= v_cell > v_lo:
            frac = (v_cell - v_lo) / (v_hi - v_lo)
            return s_lo + frac * (s_hi - s_lo)
    return 0.0


@dataclass
class SocState:
    soc_init: float          # 锚点 SoC %
    charge_ref_c: float      # 锚点 CHARGE 寄存器值 (C)
    anchor_time: float       # unix 时间戳
    source: str              # 锚点来源标记

    def save(self, path: pathlib.Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: pathlib.Path) -> "SocState | None":
        if not path.exists():
            return None
        try:
            return cls(**json.loads(path.read_text()))
        except Exception:
            return None


def compute_soc(state: SocState, charge_now_c: float) -> float:
    consumed_c = charge_now_c - state.charge_ref_c
    return state.soc_init - consumed_c * 100.0 / CAPACITY_C


def determine_initial(ina: Ina228, state_path: pathlib.Path) -> SocState:
    """启动时决定 SoC 初值和 CHARGE 锚点。"""
    print(f"[启动] 采样 {STARTUP_SAMPLE_S}s 判断电池状态 ...")
    t0 = time.monotonic()
    v_sum = i_sum = 0.0
    n = 0
    while time.monotonic() - t0 < STARTUP_SAMPLE_S:
        v_sum += ina.read_vbus_v()
        i_sum += ina.read_current_a()
        n += 1
        time.sleep(0.05)
    vbus = v_sum / n
    i_avg = i_sum / n
    charge_now = ina.read_charge_c()

    print(f"        VBUS {vbus:.3f}V ({vbus/CELLS:.3f} V/cell)  "
          f"I {i_avg:+.3f}A")

    at_rest = abs(i_avg) < REST_I_A
    saved = SocState.load(state_path)

    if at_rest:
        soc = ocv_to_soc(vbus)
        print(f"        静置 → OCV 查表 → SoC={soc:.1f}%  (最可靠)")
        return SocState(soc, charge_now, time.time(), "ocv-startup")

    # 带载启动（不常见，比如脚本崩溃后热重启）
    if saved is not None:
        age_min = (time.time() - saved.anchor_time) / 60.0
        # 判断 INA228 是否掉电重启：CHARGE 寄存器值比保存时的小说明重置过
        charge_continuous = charge_now >= saved.charge_ref_c
        if age_min < 10 and charge_continuous:
            print(f"        带载 + 状态新鲜 ({age_min:.1f} min) + CHARGE 延续 → resume")
            return saved
        if age_min < 10:
            print(f"        带载 + 状态新鲜 ({age_min:.1f} min) + CHARGE 被重置 → "
                  f"继承 SoC 但重置锚点")
            return SocState(saved.soc_init, charge_now, time.time(),
                            "resume-after-cycle")

    # 最差情况：带载且无可用状态
    soc = ocv_to_soc(vbus)
    print(f"        带载 + 无可用状态 → OCV 退化估计 (被 IR 压降低估) = {soc:.1f}%")
    print(f"        建议: 下次充满后断电 10s 再启动脚本")
    return SocState(soc, charge_now, time.time(), "ocv-loaded-degraded")


def format_eta(seconds: float) -> str:
    if seconds > 3600:
        return f"{seconds/3600:.1f}h"
    if seconds > 60:
        return f"{seconds/60:.0f}min"
    return f"{seconds:.0f}s"


def main():
    p = argparse.ArgumentParser(
        description="INA228 6S LiPo 3000mAh 电量估算",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--duration", type=float, default=0,
                   help="运行时长 (秒)，0 = 一直运行")
    p.add_argument("--print-every", type=float, default=5.0)
    p.add_argument("--bus", type=int, default=7)
    p.add_argument("--addr", type=lambda x: int(x, 0), default=0x40)
    args = p.parse_args()

    require_i2c(args.bus)
    state_path = output_dir() / "soc_state.json"

    # reset=False 保留 CHARGE 累积跨脚本运行不丢
    with Ina228(bus=args.bus, address=args.addr,
                r_shunt_ohm=0.002, i_max_a=100.0,
                reset=False) as ina:

        info = ina.probe()
        if info.manufacturer_id != 0x5449:
            print(f"[错误] MFG_ID=0x{info.manufacturer_id:04X}，芯片不对",
                  file=sys.stderr)
            sys.exit(1)

        state = determine_initial(ina, state_path)
        state.save(state_path)

        i_history = collections.deque(maxlen=int(30.0 / LOOP_DT))  # 30s 窗口
        rest_start = None
        last_print = time.monotonic()
        last_save = time.monotonic()

        def on_exit(*_):
            state.save(state_path)
            ch = ina.read_charge_c()
            print(f"\n[退出] SoC={compute_soc(state, ch):.1f}%  "
                  f"状态存至 {state_path}")
            sys.exit(0)

        signal.signal(signal.SIGINT, on_exit)
        signal.signal(signal.SIGTERM, on_exit)

        t_loop_start = time.monotonic()
        while True:
            now = time.monotonic()
            if args.duration > 0 and now - t_loop_start >= args.duration:
                break

            vbus = ina.read_vbus_v()
            current = ina.read_current_a()
            charge = ina.read_charge_c()
            soc = compute_soc(state, charge)
            i_history.append(current)

            # 静置检测与再锚定
            if abs(current) < REST_I_A:
                if rest_start is None:
                    rest_start = now
                elif now - rest_start >= REST_DURATION_S:
                    v_soc = ocv_to_soc(vbus)
                    if abs(v_soc - soc) > RECAL_DELTA_PCT:
                        print(f"\n[再锚定] 静置 {int(now - rest_start)}s  "
                              f"OCV={v_soc:.1f}% vs CC={soc:.1f}%  "
                              f"(差 {v_soc - soc:+.1f}%) → 采 OCV")
                        state = SocState(v_soc, charge, time.time(),
                                         "ocv-recalib")
                        state.save(state_path)
                    rest_start = now  # 下一轮 30s 再检
            else:
                rest_start = None

            # 周期打印
            if now - last_print >= args.print_every:
                soc_clamped = max(soc, 0.0)
                remaining_mah = CAPACITY_MAH * soc_clamped / 100.0
                i_avg = sum(i_history) / len(i_history) if i_history else 0.0
                eta_str = ""
                if i_avg > 0.1 and soc_clamped > 0:
                    remaining_c = CAPACITY_C * soc_clamped / 100.0
                    eta_str = f"  ETA {format_eta(remaining_c / i_avg)}"
                rest_tag = (f"  静置{int(now - rest_start)}s"
                            if rest_start is not None else "")
                print(f"  V={vbus:5.2f}V  I={current:+6.2f}A  "
                      f"SoC={soc:5.1f}%  余={remaining_mah:4.0f}mAh"
                      f"{eta_str}  锚={state.source}{rest_tag}",
                      flush=True)
                last_print = now

            # 周期持久化
            if now - last_save >= SAVE_INTERVAL_S:
                state.save(state_path)
                last_save = now

            time.sleep(LOOP_DT)

        state.save(state_path)


if __name__ == "__main__":
    main()
