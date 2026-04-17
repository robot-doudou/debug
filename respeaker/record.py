"""从 ReSpeaker XVF3800 录制音频。

用法:
    uv run record.py              # 录制 5 秒
    uv run record.py --duration 10  # 录制 10 秒
    uv run record.py --gain 8     # 放大 8 倍 (XVF3800 输出电平较低)
    uv run record.py --list       # 列出所有输入设备
"""

import argparse
import struct
import wave

import pyaudio

import device

RATE = 16000
CHANNELS = 2
FORMAT = pyaudio.paInt16
CHUNK = 1024


def apply_gain(data: bytes, gain: float) -> bytes:
    """对 16-bit PCM 数据应用增益，带削波保护。"""
    if gain == 1.0:
        return data
    n = len(data) // 2
    samples = struct.unpack(f"<{n}h", data)
    amped = [max(-32768, min(32767, int(s * gain))) for s in samples]
    return struct.pack(f"<{n}h", *amped)


def analyze(frames: list[bytes]) -> tuple[int, float]:
    """返回 (峰值, RMS)，用于提示录音电平。"""
    import math
    all_data = b"".join(frames)
    samples = struct.unpack(f"<{len(all_data) // 2}h", all_data)
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return peak, rms


def record(duration: int, output: str, gain: float):
    """录制音频并保存为 WAV 文件。"""
    pa = pyaudio.PyAudio()
    try:
        pa, idx = device.find_input(pa)
        if idx is None:
            print("错误: 未找到 XVF3800 输入设备")
            device.list_inputs(pa)
            return

        info = pa.get_device_info_by_index(idx)
        print(f"使用设备: [{idx}] {info['name']}")
        gain_str = f", 增益 {gain}x" if gain != 1.0 else ""
        print(f"参数: {CHANNELS}ch, {RATE}Hz, {duration}s{gain_str}")

        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=idx,
            frames_per_buffer=CHUNK,
        )

        print("录制中...")
        frames = []
        for i in range(0, RATE // CHUNK * duration):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(apply_gain(data, gain))

        stream.stop_stream()
        stream.close()

        with wave.open(output, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(pa.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))

        peak, rms = analyze(frames)
        peak_pct = peak / 32767 * 100
        print(f"已保存: {output} (峰值={peak} {peak_pct:.1f}%, RMS={rms:.0f})")
        if peak_pct < 20:
            print(f"  提示: 录音电平偏低，可尝试 --gain {max(2, int(50 / peak_pct))}")
    finally:
        pa.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReSpeaker XVF3800 录音测试")
    parser.add_argument("--duration", type=int, default=5, help="录制时长(秒)")
    parser.add_argument("--output", default="test_record.wav", help="输出文件名")
    parser.add_argument("--gain", type=float, default=1.0, help="软件增益倍数 (默认 1.0)")
    parser.add_argument("--list", action="store_true", help="列出所有输入设备")
    args = parser.parse_args()

    pa = pyaudio.PyAudio()
    if args.list:
        device.list_inputs(pa)
        pa.terminate()
    else:
        record(args.duration, args.output, args.gain)
