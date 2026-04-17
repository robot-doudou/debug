"""Makerbase CANable 2.0 固件烧录: slcan → candleLight。

流程:
  1. 读当前 USB ID (lsusb) 判断固件
  2. 提示用户: 短接 BOOT 跳线 (或按住 BOOT 按钮) 后重插 USB 进 DFU
  3. 轮询 0483:df11 DFU 设备出现 (30s)
  4. 调用 dfu-util 烧录 .bin
  5. 轮询新 USB ID 出现 (10s), 提示下一步

候选固件来源:
  - 官方:   https://github.com/candle-usb/candleLight_fw  (make CANABLE2=1)
  - Fork:   https://github.com/normaldotcom/candleLight_fw/releases
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time

DFU_ID = "0483:df11"
SLCAN_ID = "16d0:117e"
CANDLELIGHT_ID = "1d50:606f"


def lsusb_ids() -> list[str]:
    result = subprocess.run(["lsusb"], capture_output=True, text=True, check=True)
    return re.findall(r"ID ([0-9a-f]{4}:[0-9a-f]{4})", result.stdout)


def wait_for_usb_id(target: str, timeout: float, label: str) -> bool:
    deadline = time.monotonic() + timeout
    last_report = 0.0
    while time.monotonic() < deadline:
        if target in lsusb_ids():
            print(f"[ok]   检测到 {label} ({target})")
            return True
        now = time.monotonic()
        if now - last_report >= 1.0:
            remain = deadline - now
            print(f"  等待 {label} ({target})... 剩 {remain:.0f}s", end="\r")
            last_report = now
        time.sleep(0.2)
    print()
    return False


def main():
    p = argparse.ArgumentParser(description="CANable 2.0 DFU 烧录")
    p.add_argument("bin", nargs="?", help="candleLight_fw.bin 路径 (省略则只 --info)")
    p.add_argument("--info", action="store_true", help="只查当前状态")
    p.add_argument("-y", "--yes", action="store_true", help="跳过交互式确认")
    args = p.parse_args()

    print("=== 当前 USB 设备 ===")
    ids = lsusb_ids()
    if SLCAN_ID in ids:
        print(f"  当前: slcan 固件 ({SLCAN_ID})")
    elif CANDLELIGHT_ID in ids:
        print(f"  当前: candleLight 固件 ({CANDLELIGHT_ID}) — 已是目标固件")
    elif DFU_ID in ids:
        print(f"  当前: DFU 模式 ({DFU_ID})")
    else:
        print("  未检测到 CANable 2.0")

    if args.info or not args.bin:
        return

    if not shutil.which("dfu-util"):
        print("\n[错误] 未安装 dfu-util. 请 sudo apt install dfu-util", file=sys.stderr)
        sys.exit(1)

    print()
    print("=== 烧录准备 ===")
    print(f"  目标固件: {args.bin}")
    print("  操作步骤:")
    print("    1. 拔掉 CANable 2.0 USB")
    print("    2. 短接板上 BOOT 跳线 (或按住 BOOT 按钮)")
    print("    3. 插回 USB (保持 BOOT 短接/按住到插入为止)")
    print("    4. 回车继续")
    if not args.yes:
        input("  回车后开始等待 DFU 设备...")

    if not wait_for_usb_id(DFU_ID, timeout=30.0, label="DFU 设备"):
        print("[错误] 30s 内未检测到 DFU 设备. 检查 BOOT 跳线是否短接到位.",
              file=sys.stderr)
        sys.exit(1)

    print("\n=== dfu-util 烧录 ===")
    cmd = ["dfu-util", "-a", "0", "-s", "0x08000000:leave", "-D", args.bin]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    # 透传 dfu-util 的 stdout/stderr, 方便用户看进度和诊断
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    # STM32 DFU bootloader 的 :leave 步骤常常失败 (exit 74), 但 bin 其实已写入.
    # 判定成功: 输出里有 "File downloaded successfully"; 其他退出码按真实失败处理.
    if "File downloaded successfully" in result.stdout:
        if result.returncode != 0:
            print(f"[警告] dfu-util 退出码 {result.returncode} (常见: 'leave' 步骤失败),",
                  file=sys.stderr)
            print("       但 Flash 写入已完成. 手动拔 USB + 松 BOOT + 插回即可.",
                  file=sys.stderr)
    elif result.returncode != 0:
        print(f"[错误] dfu-util 退出码 {result.returncode}, Flash 未写入",
              file=sys.stderr)
        sys.exit(result.returncode)

    print("\n=== 等待固件重新枚举 ===")
    print("  拔 USB, 松开 BOOT 跳线, 插回 USB")
    if wait_for_usb_id(CANDLELIGHT_ID, timeout=10.0, label="candleLight"):
        print("\n[完成] 固件烧录成功. 下一步:")
        print("  sudo bash setup.sh    # 若还没装 systemd unit")
        print("  ip -details link show can0")
        print("  uv run detect.py")
    else:
        print("[警告] 10s 内未检测到 candleLight. 手动拔插一次再查 lsusb.")


if __name__ == "__main__":
    main()
