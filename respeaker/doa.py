"""DOA 声源方向检测测试。

通过 USB vendor control transfer 读取 XVF3800 的 DOA 数据，
实时显示声源角度和语音活动状态。

用法:
    uv run doa.py                 # 实时显示 DOA (默认 30 秒)
    uv run doa.py --duration 60   # 运行 60 秒
    uv run doa.py --mode azimuth  # 使用 AEC_AZIMUTH_VALUES 模式
"""

import argparse
import math
import struct
import time

import usb.core
import usb.util

VID = 0x2886
PID = 0x001A

# USB control transfer 参数
CTRL_IN = usb.util.CTRL_IN
CTRL_TYPE_VENDOR = usb.util.CTRL_TYPE_VENDOR
CTRL_RECIPIENT_DEVICE = usb.util.CTRL_RECIPIENT_DEVICE
REQUEST_DIRECTION = CTRL_IN | CTRL_TYPE_VENDOR | CTRL_RECIPIENT_DEVICE

# DOA_VALUE: resid=20, cmdid=18, 返回 2 x uint16
DOA_RESID = 20
DOA_CMDID = 18
DOA_LENGTH = 4 + 1  # 2 x uint16 (4 bytes) + 1 status byte

# AEC_AZIMUTH_VALUES: resid=33, cmdid=75, 返回 4 x float
AZ_RESID = 33
AZ_CMDID = 75
AZ_LENGTH = 16 + 1  # 4 x float (16 bytes) + 1 status byte


def find_device():
    """查找 XVF3800 USB 设备。"""
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print(f"错误: 未找到 XVF3800 设备 (VID={VID:#06x}, PID={PID:#06x})")
        return None
    return dev


def read_control(dev, resid, cmdid, length):
    """通过 USB vendor control transfer 读取数据。"""
    wValue = 0x80 | cmdid
    wIndex = resid
    try:
        data = dev.ctrl_transfer(REQUEST_DIRECTION, 0, wValue, wIndex, length)
        if len(data) < 1:
            return None
        status = data[0]
        if status == 64:  # retry
            return None
        if status != 0:
            return None
        return bytes(data[1:])
    except usb.core.USBError:
        return None


def read_doa(dev):
    """读取 DOA_VALUE: 角度(0-359) + 是否有语音(0/1)。"""
    data = read_control(dev, DOA_RESID, DOA_CMDID, DOA_LENGTH)
    if data is None or len(data) < 4:
        return None, None
    angle, voice = struct.unpack("<HH", data[:4])
    return angle, bool(voice)


def read_azimuth(dev):
    """读取 AEC_AZIMUTH_VALUES: 4 x float(弧度)。"""
    data = read_control(dev, AZ_RESID, AZ_CMDID, AZ_LENGTH)
    if data is None or len(data) < 16:
        return None
    values = struct.unpack("<4f", data[:16])
    return values


def angle_bar(angle, has_voice):
    """生成方向指示条。"""
    if angle is None:
        return "---"
    # 将 0-359 映射到 36 格的条形图
    pos = int(angle / 10)
    bar = ["."] * 36
    bar[pos] = "^"
    color = "\033[92m" if has_voice else "\033[90m"
    reset = "\033[0m"
    return f"{color}{''.join(bar)}{reset}"


def run_doa(duration, mode):
    dev = find_device()
    if dev is None:
        return

    try:
        product_name = usb.util.get_string(dev, dev.iProduct)
    except (ValueError, usb.core.USBError):
        product_name = f"VID={VID:#06x} PID={PID:#06x}"
    print(f"设备: {product_name}")
    print(f"模式: {'DOA_VALUE' if mode == 'doa' else 'AEC_AZIMUTH_VALUES'}")
    print(f"时长: {duration}s")
    print(f"{'时间':>6s}  {'角度':>5s}  {'语音':<4s}  方向 (0°=正前方)")
    print("-" * 65)

    start = time.time()
    while time.time() - start < duration:
        if mode == "doa":
            angle, has_voice = read_doa(dev)
            if angle is not None:
                status = "说话" if has_voice else "静音"
                color = "\033[92m" if has_voice else "\033[90m"
                reset = "\033[0m"
                t = time.time() - start
                bar = angle_bar(angle, has_voice)
                print(
                    f"\r{t:5.1f}s  {angle:4d}°  "
                    f"{color}{status:<4s}{reset}  {bar}",
                    end="", flush=True,
                )
        else:
            values = read_azimuth(dev)
            if values is not None:
                t = time.time() - start
                labels = ["beam1", "beam2", "扫描 ", "自动 "]
                parts = []
                for label, v in zip(labels, values):
                    if math.isnan(v):
                        parts.append(f"{label}=  N/A")
                    else:
                        deg = math.degrees(v)
                        parts.append(f"{label}={deg:5.1f}°")
                print(f"\r{t:5.1f}s  {' | '.join(parts)}", end="", flush=True)

        time.sleep(0.1)

    print("\n检测结束")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReSpeaker XVF3800 DOA 声源方向测试")
    parser.add_argument("--duration", type=int, default=30, help="运行时长秒 (默认 30)")
    parser.add_argument(
        "--mode",
        choices=["doa", "azimuth"],
        default="doa",
        help="读取模式: doa=DOA_VALUE, azimuth=AEC_AZIMUTH_VALUES (默认 doa)",
    )
    args = parser.parse_args()

    run_doa(args.duration, args.mode)
