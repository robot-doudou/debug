"""实时 VAD 语音活动检测。

基于 XVF3800 处理后信号的能量进行检测，实时显示能量条和语音/静音状态。

用法:
    uv run vad.py                 # 默认阈值
    uv run vad.py --threshold 500 # 自定义阈值
    uv run vad.py --duration 10   # 运行 10 秒
"""

import argparse
import struct
import math

import pyaudio

import device

RATE = 16000
CHANNELS = 2
FORMAT = pyaudio.paInt16
CHUNK = 1600  # 100ms per chunk at 16kHz


def rms(data: bytes, channels: int) -> float:
    """计算 RMS 能量（取第一通道）。"""
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    # 取第一通道
    ch0 = samples[0::channels]
    if not ch0:
        return 0.0
    return math.sqrt(sum(s * s for s in ch0) / len(ch0))


def run_vad(threshold: float, duration: int):
    pa = pyaudio.PyAudio()
    try:
        pa, idx = device.find_input(pa)
        if idx is None:
            print("错误: 未找到 XVF3800 输入设备")
            return

        info = pa.get_device_info_by_index(idx)
        print(f"使用设备: [{idx}] {info['name']}")
        print(f"VAD 阈值: {threshold:.0f}  时长: {duration}s")
        print(f"{'时间':>6s}  {'能量':>6s}  {'状态':<4s}  能量条")
        print("-" * 60)

        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=idx,
            frames_per_buffer=CHUNK,
        )

        chunks_total = RATE // CHUNK * duration
        for i in range(chunks_total):
            data = stream.read(CHUNK, exception_on_overflow=False)
            energy = rms(data, CHANNELS)
            is_speech = energy > threshold
            t = (i + 1) * CHUNK / RATE

            bar_len = int(min(energy / 50, 40))
            bar = "█" * bar_len
            status = "说话" if is_speech else "静音"
            color = "\033[92m" if is_speech else "\033[90m"
            reset = "\033[0m"

            print(f"\r{t:5.1f}s  {energy:6.0f}  {color}{status:<4s}{reset}  {color}{bar:<40s}{reset}", end="", flush=True)

        print()
        stream.stop_stream()
        stream.close()
        print("检测结束")
    finally:
        pa.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReSpeaker XVF3800 VAD 测试")
    parser.add_argument("--threshold", type=float, default=300, help="能量阈值 (默认 300)")
    parser.add_argument("--duration", type=int, default=15, help="运行时长秒 (默认 15)")
    args = parser.parse_args()

    run_vad(args.threshold, args.duration)
