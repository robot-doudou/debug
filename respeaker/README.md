# ReSpeaker XVF3800 调试工具

## 设备信息

- 型号: Seeed Studio reSpeaker XVF3800 4-Mic Array
- 接口: USB
- 音频参数: 2 通道, 16000 Hz, 16 bit

## XVF3800 功能说明

### 芯片内置 DSP

| 功能 | 说明 |
|------|------|
| AEC | 声学回声消除，播放音频时不影响拾音 |
| 波束成形 | 4 麦克风阵列定向拾音，抑制非目标方向噪声 |
| DOA | 声源方向检测 (Direction of Arrival) |
| NS | 噪声抑制 |
| AGC | 自动增益控制 |
| VAD | 语音活动检测 |

### USB 多通道输出

XVF3800 支持多通道音频输出（Linux 下可见全部通道）：

- **ASR 通道** — 降噪 + 回声消除后的语音，用于语音识别
- **Comms 通道** — 处理后的通话音频
- **Raw Mic 通道** — 4 路原始麦克风信号
- **参考信号通道** — 回放参考，用于 AEC

macOS 下默认只暴露 2 进 2 出，完整多通道需在 Linux 上使用。

### 控制接口

- USB HID / I2C 可配置 DSP 参数（增益、波束方向等）
- 固件更新工具: `respeaker-usb-dfu`

## 使用

### 检测设备

```bash
uv run detect.py
```

### 录音测试

```bash
# 默认录制 5 秒
uv run record.py

# 指定时长和输出文件
uv run record.py --duration 10 --output my_record.wav

# 列出所有输入设备
uv run record.py --list
```

### 播放测试音

```bash
# 默认播放 1000Hz 测试音 3 秒
uv run play.py

# 指定频率、时长和音量
uv run play.py --freq 440 --duration 5 --volume 0.5

# 列出所有输出设备
uv run play.py --list
```

### 播放 WAV 文件

```bash
# 播放录音
uv run play.py test_record.wav

# 调整音量播放
uv run play.py test_record.wav --volume 0.5
```

### VAD 语音活动检测

```bash
# 实时检测语音/静音状态 (默认 15 秒)
uv run vad.py

# 自定义阈值和时长
uv run vad.py --threshold 500 --duration 10
```

### AEC 回声消除测试

```bash
# 边播放 1000Hz 边录音，分析回声残留
uv run aec_test.py

# 指定测试频率
uv run aec_test.py --freq 500 --duration 5
```

### 降噪效果测试

```bash
# 分两步录制底噪和语音，对比信噪比
uv run noise_test.py

# 自定义每段录制时长
uv run noise_test.py --duration 3
```
