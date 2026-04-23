"""检测 CANable 2.0 USB 设备、列举所有 CAN 接口、探活达妙电机。

显示:
- USB 层 (lsusb): 找 16d0:117e (slcan) 或 1d50:606f (candleLight)
- 网络层: 所有 CAN netdev + 其驱动 (gs_usb=CANable, mttcan=Jetson SoC 内置)
- 协议层: 对 motor_id 发一次控制帧, 等反馈

Jetson 专属坑: Orin SoC 内置 MTTCAN 控制器通常占 can0, CANable 会被分到 can1。
脚本默认按驱动 (gs_usb) 自动选 CANable 接口, 不再硬编 can0。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

from device import (DMMotor, open_bus, add_id_args, resolve_ids,
                    list_can_interfaces, find_can_interface)

CANABLE_USB_IDS = {
    "16d0:117e": "slcan (normaldotcom fork)",
    "1d50:606f": "candleLight (gs_usb)",
}

# 已知驱动 → 人类可读名
DRIVER_LABEL = {
    "gs_usb":  "CANable 2.0 / candleLight",
    "mttcan":  "Jetson SoC 内置 (不是 CANable!)",
    "slcan":   "slcan 串口仿真",
}


def detect_usb() -> list[dict]:
    if sys.platform != "linux":
        print(f"  不支持的平台: {sys.platform}")
        return []
    result = subprocess.run(["lsusb"], capture_output=True, text=True)
    devices = []
    for line in result.stdout.splitlines():
        m = re.search(r"ID ([0-9a-f]{4}:[0-9a-f]{4})", line)
        if not m:
            continue
        vid_pid = m.group(1)
        if vid_pid in CANABLE_USB_IDS:
            devices.append({
                "id": vid_pid,
                "firmware": CANABLE_USB_IDS[vid_pid],
                "header": line.strip(),
            })
    return devices


def detect_if_details(name: str) -> dict:
    """读取单个 CAN 接口的 state / bitrate。"""
    result = subprocess.run(
        ["ip", "-details", "link", "show", name],
        capture_output=True, text=True,
    )
    info: dict = {}
    if result.returncode != 0:
        return info
    m = re.search(r"state (\w+)", result.stdout)
    if m:
        info["state"] = m.group(1)
    m = re.search(r"bitrate (\d+)", result.stdout)
    if m:
        info["bitrate"] = int(m.group(1))
    return info


def ping_motor(channel: str, motor_id: int, master_id: int) -> tuple[bool, str]:
    """对电机发 clear_error 并等反馈。返回 (ok, 说明)。"""
    try:
        bus = open_bus(channel=channel, bitrate=1_000_000)
    except Exception as e:
        return False, f"打开 CAN 总线失败: {e}"
    try:
        motor = DMMotor(bus, motor_id=motor_id, master_id=master_id, auto_enable=False)
        motor.clear_error()
        state = motor.read_state(timeout=0.3)
        if state is None:
            return False, f"未收到 master_id=0x{master_id:02X} 的反馈"
        return True, (f"pos={state.pos:+.3f} rad  vel={state.vel:+.3f} rad/s  "
                      f"tau={state.tau:+.3f} N·m  err={state.err_code}  "
                      f"T_mos={state.t_mos}°C  T_rotor={state.t_rotor}°C")
    finally:
        bus.shutdown()


def main():
    p = argparse.ArgumentParser(description="检测 CANable 2.0 + CAN 接口 + 达妙电机")
    add_id_args(p)
    p.add_argument("--interface", "-i", default=None,
                   help="指定 CAN 接口 (默认自动按驱动选: gs_usb 优先)")
    p.add_argument("--skip-motor", action="store_true", help="只做 USB + CAN 接口检测")
    args = p.parse_args()
    resolve_ids(p, args)

    print("=== USB 设备检测 (CANable 2.0) ===")
    usb = detect_usb()
    if not usb:
        print("  未检测到 CANable 2.0 USB 设备")
    for d in usb:
        print(f"  {d['header']}")
        print(f"    固件: {d['firmware']}")

    print("\n=== CAN 接口列表 ===")
    ifs = list_can_interfaces()
    if not ifs:
        print("  无 CAN netdev")
        print("  → 没装 gs_usb 模块: 跑 damiao/gs_usb_mod/ 下的 build.sh")
        print("  → 或固件还是 slcan: 跑 fw_update.py 烧 candleLight")
    else:
        for name, drv in ifs:
            d = detect_if_details(name)
            label = DRIVER_LABEL.get(drv, drv)
            state = d.get("state", "?")
            br = d.get("bitrate")
            br_str = f", bitrate {br}" if br else ""
            print(f"  {name}  driver={drv} ({label})  state={state}{br_str}")

    # 选接口
    chosen = args.interface or find_can_interface()
    if args.skip_motor:
        return
    if chosen is None:
        print("\n=== 电机探活 === (跳过, 无可用 CAN 接口)")
        return
    d = detect_if_details(chosen)
    if d.get("state") != "UP":
        print(f"\n=== 电机探活 === (跳过, {chosen} 不是 UP 状态)")
        print(f"  → sudo ip link set {chosen} type can bitrate 1000000 && sudo ip link set {chosen} up")
        print(f"  → 或跑 sudo bash setup.sh 装 udev 规则让 CANable 插上自动拉起")
        return

    print(f"\n=== 电机探活 ({chosen}, motor_id=0x{args.motor_id:02X}, "
          f"master_id=0x{args.master_id:02X}) ===")
    ok, msg = ping_motor(chosen, args.motor_id, args.master_id)
    print(f"  {'[OK]' if ok else '[FAIL]'} {msg}")
    if not ok:
        print("  常见原因: motor_id/master_id 不匹配, bitrate 不是 1 Mbps, "
              "CAN_H/L 反接, 电源未接")


if __name__ == "__main__":
    main()
