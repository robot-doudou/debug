"""AEC 回声消除测试。

边播放测试音边录音，分析录音中是否残留播放信号，验证 XVF3800 的回声消除效果。

用法:
    uv run aec_test.py              # 默认 1000Hz 测试
    uv run aec_test.py --freq 500   # 用 500Hz 测试
"""

import argparse
import math
import struct
import threading
import wave

import pyaudio

import device

RATE = 16000
CHANNELS = 2
FORMAT = pyaudio.paInt16
CHUNK = 1024


def generate_tone(freq: float, duration: int, volume: float = 0.8) -> bytes:
    samples = []
    for i in range(RATE * duration):
        val = int(volume * 32767 * math.sin(2 * math.pi * freq * i / RATE))
        samples.append(struct.pack("<hh", val, val))
    return b"".join(samples)


def analyze(filename: str, freq: float):
    """分析录音文件，检测指定频率的残留能量。"""
    with wave.open(filename, "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        ch0 = list(samples[0::wf.getnchannels()])

    n = len(ch0)
    if n == 0:
        print("错误: 录音为空")
        return

    # 总体 RMS
    total_rms = math.sqrt(sum(s * s for s in ch0) / n)

    # 用 Goertzel 算法检测目标频率能量
    k = round(freq * n / RATE)
    w = 2 * math.pi * k / n
    coeff = 2 * math.cos(w)
    s0 = s1 = 0.0
    for sample in ch0:
        s2 = sample + coeff * s1 - s0
        s0 = s1
        s1 = s2
    tone_power = math.sqrt((s0 * s0 + s1 * s1 - coeff * s0 * s1) / n)
    tone_ratio = tone_power / total_rms if total_rms > 0 else 0

    print(f"\n=== AEC 分析结果 ===")
    print(f"  总体 RMS: {total_rms:.1f}")
    print(f"  {freq}Hz 能量: {tone_power:.1f}")
    print(f"  频率占比: {tone_ratio:.2%}")

    if tone_ratio < 0.1:
        print(f"  结论: AEC 效果良好，{freq}Hz 回声已基本消除")
    elif tone_ratio < 0.3:
        print(f"  结论: AEC 部分生效，{freq}Hz 有少量残留")
    else:
        print(f"  结论: AEC 效果不佳，{freq}Hz 回声明显残留")


def run_aec_test(freq: float, duration: int):
    pa = pyaudio.PyAudio()

    pa, in_idx, out_idx = device.find_both(pa)

    if in_idx is None or out_idx is None:
        print("错误: 未找到 XVF3800 的输入/输出设备")
        pa.terminate()
        return

    out_info = pa.get_device_info_by_index(out_idx)
    in_info = pa.get_device_info_by_index(in_idx)
    print(f"输出设备: [{out_idx}] {out_info['name']}")
    print(f"输入设备: [{in_idx}] {in_info['name']}")
    print(f"测试: 播放 {freq}Hz 同时录音 {duration}s\n")

    output_file = "aec_test.wav"
    recorded_frames = []

    # 录音线程
    def record():
        stream = pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE,
            input=True, input_device_index=in_idx,
            frames_per_buffer=CHUNK,
        )
        for _ in range(RATE // CHUNK * duration):
            data = stream.read(CHUNK, exception_on_overflow=False)
            recorded_frames.append(data)
        stream.stop_stream()
        stream.close()

    # 播放线程
    def play():
        stream = pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE,
            output=True, output_device_index=out_idx,
            frames_per_buffer=CHUNK,
        )
        tone = generate_tone(freq, duration)
        stream.write(tone)
        stream.stop_stream()
        stream.close()

    print("开始: 同时播放 + 录音...")
    t_rec = threading.Thread(target=record)
    t_play = threading.Thread(target=play)
    t_rec.start()
    t_play.start()
    t_rec.join()
    t_play.join()

    # 保存录音
    with wave.open(output_file, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pa.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(recorded_frames))

    print(f"录音已保存: {output_file}")
    pa.terminate()

    analyze(output_file, freq)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReSpeaker XVF3800 AEC 测试")
    parser.add_argument("--freq", type=float, default=1000, help="测试频率 Hz (默认 1000)")
    parser.add_argument("--duration", type=int, default=5, help="测试时长秒 (默认 5)")
    args = parser.parse_args()

    run_aec_test(args.freq, args.duration)
