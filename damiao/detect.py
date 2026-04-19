"""检测 CANable 2.0 USB 设备、can0 链路状态、探活达妙电机。

显示:
- USB 层 (lsusb): 找 16d0:117e (slcan) 或 1d50:606f (candleLight)
- 网络层: can0 接口是否 UP, bitrate
- 协议层: 对 motor_id 发一次控制帧, 等反馈
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

from device import DMMotor, open_bus

CANABLE_USB_IDS = {
    "16d0:117e": "slcan (normaldotcom fork)",
    "1d50:606f": "candleLight (gs_usb)",
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


def detect_can0() -> dict | None:
    """读取 can0 接口详情 (ip -details link show can0)。未找到返回 None。"""
    result = subprocess.run(
        ["ip", "-details", "link", "show", "can0"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    info = {"raw": result.stdout.strip()}
    m = re.search(r"state (\w+)", result.stdout)
    if m:
        info["state"] = m.group(1)
    m = re.search(r"bitrate (\d+)", result.stdout)
    if m:
        info["bitrate"] = int(m.group(1))
    return info


def ping_motor(motor_id: int, master_id: int) -> tuple[bool, str]:
    """对电机发 clear_error 并等反馈。返回 (ok, 说明)。"""
    try:
        bus = open_bus(channel="can0", bitrate=1_000_000)
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
    p = argparse.ArgumentParser(description="检测 CANable 2.0 + can0 + 达妙电机")
    p.add_argument("--motor-id", type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--master-id", type=lambda x: int(x, 0), default=0x00)
    p.add_argument("--skip-motor", action="store_true", help="只做 USB + can0 检测")
    args = p.parse_args()

    print("=== USB 设备检测 (CANable 2.0) ===")
    usb = detect_usb()
    if not usb:
        print("  未检测到 CANable 2.0 USB 设备")
    for d in usb:
        print(f"  {d['header']}")
        print(f"    固件: {d['firmware']}")

    print("\n=== can0 链路 ===")
    c = detect_can0()
    if c is None:
        print("  can0 不存在")
        print("  → 如已烧 candleLight 固件, 跑 setup.sh 装 systemd unit")
        print("  → 如仍是 slcan 固件, 跑 fw_update.py 烧 candleLight")
    else:
        print(f"  state: {c.get('state', '?')}")
        if "bitrate" in c:
            print(f"  bitrate: {c['bitrate']}")

    if args.skip_motor:
        return
    if c is None or c.get("state") != "UP":
        print("\n=== 电机探活 === (跳过, can0 未就绪)")
        return

    print(f"\n=== 电机探活 (motor_id=0x{args.motor_id:02X}, "
          f"master_id=0x{args.master_id:02X}) ===")
    ok, msg = ping_motor(args.motor_id, args.master_id)
    print(f"  {'[OK]' if ok else '[FAIL]'} {msg}")
    if not ok:
        print("  常见原因: motor_id/master_id 不匹配, bitrate 不是 1 Mbps, "
              "CAN_H/L 反接, 电源未接")


if __name__ == "__main__":
    main()
