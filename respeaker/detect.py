"""检测 ReSpeaker XVF3800 USB 设备信息。"""

import subprocess
import re


def detect_usb():
    """通过 ioreg 检测 XVF3800 USB 设备。"""
    result = subprocess.run(
        ["ioreg", "-p", "IOUSB", "-l"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    device_info = {}
    in_device = False
    for line in lines:
        if "XVF3800" in line:
            in_device = True
            device_info["name"] = line.strip()
        if in_device:
            for key in [
                "USB Product Name",
                "USB Vendor Name",
                "USB Serial Number",
                "idVendor",
                "idProduct",
                "Device Speed",
            ]:
                pattern = r'"' + re.escape(key) + r'"\s*=\s*"?([^"}\n]+)"?'
                m = re.search(pattern, line)
                if m:
                    device_info[key] = m.group(1).strip()
            if "}" in line and in_device and len(device_info) > 3:
                break
    return device_info


def detect_audio():
    """通过 system_profiler 检测音频设备。"""
    result = subprocess.run(
        ["system_profiler", "SPAudioDataType"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    devices = []
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith(("Audio", "Devices")):
            if current:
                devices.append(current)
            current = {"name": stripped.rstrip(":")}
        elif current and ":" in stripped:
            k, v = stripped.split(":", 1)
            current[k.strip()] = v.strip()
    if current:
        devices.append(current)
    return devices


if __name__ == "__main__":
    print("=== USB 设备检测 ===")
    usb = detect_usb()
    if usb:
        for k, v in usb.items():
            print(f"  {k}: {v}")
    else:
        print("  未检测到 XVF3800 设备！")

    print("\n=== 音频设备检测 ===")
    for dev in detect_audio():
        print(f"\n  [{dev['name']}]")
        for k, v in dev.items():
            if k != "name":
                print(f"    {k}: {v}")
