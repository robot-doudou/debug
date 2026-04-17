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

### USB 控制接口

通过 USB vendor control transfer 访问（`pyusb`，非 HID）。参考实现: https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY

- VID: `0x2886`, PID: `0x001A`
- 固件更新工具: `respeaker-usb-dfu`
- **macOS 下 USB 控制接口可能被系统音频驱动占用，DOA 等控制功能建议在 Linux 上使用**

#### DOA 声源方向检测

两种读取方式:

| 命令 | resid | cmdid | 返回值 |
|------|-------|-------|--------|
| `DOA_VALUE` | 20 | 18 | 2 x uint16: 角度(0-359°) + 是否有语音(0/1) |
| `AEC_AZIMUTH_VALUES` | 33 | 75 | 4 x float(弧度): beam1, beam2, 自由扫描, 自动选择 |

读取协议:
```
direction: CTRL_IN | CTRL_TYPE_VENDOR | CTRL_RECIPIENT_DEVICE
bRequest:  0
wValue:    0x80 | cmdid    (bit 7 = read)
wIndex:    resid
wLength:   数据字节数 + 1 (状态字节)
```

响应首字节为状态: 0=成功, 64=重试。

#### 波束控制 (resid=33)

| 参数 | 说明 |
|------|------|
| `AEC_FIXEDBEAMSONOFF` | 开关固定波束模式 |
| `AEC_FIXEDBEAMSAZIMUTH_VALUES` | 设置固定波束方向 |
| `AEC_FIXEDBEAMSELEVATION_VALUES` | 设置固定波束仰角 |
| `AEC_FIXEDBEAMSGATING` | 固定波束门控开关 |
| `AEC_ASROUTONOFF` | ASR 输出模式开关 |
| `SHF_BYPASS` | 绕过 AEC |
| `AEC_HPFONOFF` | 高通滤波 (70/125/150/180 Hz) |
| `AEC_SPENERGY_VALUES` | 各波束语音能量 (4 x float) |

#### 音频参数 (resid=35)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `AUDIO_MGR_MIC_GAIN` | 90 | 麦克风增益 |
| `AUDIO_MGR_REF_GAIN` | 8.0 | 参考信号增益 |
| `AUDIO_MGR_SYS_DELAY` | 12 | 参考信号延迟(采样数) |
| `AUDIO_MGR_OP_L` / `OP_R` | — | 输出通道路由 (原始/处理后/AEC残差) |
| `AUDIO_MGR_SELECTED_AZIMUTHS` | — | 基于语音能量的 DOA (无语音时返回 NaN) |

#### 后处理 (resid=17)

| 参数 | 说明 |
|------|------|
| `PP_AGCONOFF` / `PP_AGCMAXGAIN` / `PP_AGCDESIREDLEVEL` | AGC 开关/最大增益/目标电平 |
| `PP_MIN_NS` | 稳态噪声抑制强度 |
| `PP_MIN_NN` | 非稳态噪声抑制强度 |
| `PP_ECHOONOFF` / `PP_GAMMA_E` | 回声抑制开关/强度 |
| `PP_LIMITONOFF` / `PP_LIMITPLIMIT` | 限幅器开关/阈值 |

#### LED 控制 (resid=20)

| 参数 | 说明 |
|------|------|
| `LED_EFFECT` | 模式: 0=关, 1=呼吸, 2=彩虹, 3=单色, **4=DOA**, 5=环形 |
| `LED_BRIGHTNESS` | 亮度 |
| `LED_SPEED` | 动画速度 |
| `LED_COLOR` / `LED_DOA_COLOR` | 颜色设置 |

#### 系统 (resid=48)

| 参数 | 说明 |
|------|------|
| `VERSION` | 固件版本 |
| `REBOOT` | 重启设备 |
| `SAVE_CONFIGURATION` | 保存配置到 Flash |
| `CLEAR_CONFIGURATION` | 恢复出厂设置 |
| `USB_BIT_DEPTH` | USB 音频位深 (16/24/32) |

## Linux 权限配置

### 音频设备权限

远程 (SSH) 环境下普通用户没有音频设备访问权限，需要加入 `audio` 组：

```bash
sudo usermod -aG audio $USER
# 重新登录生效 (SSH 重连即可)
```

### USB 控制权限

DOA 等 USB 控制功能需要访问 USB 设备，添加 udev 规则：

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2886", ATTR{idProduct}=="001a", MODE="0666"' | sudo tee /etc/udev/rules.d/99-respeaker.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

设置后拔插设备或重启即生效。不设规则也可以用 `sudo uv run` 临时运行。

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

### DOA 声源方向检测

```bash
# 实时显示声源角度 (默认 30 秒)
uv run doa.py

# 指定时长
uv run doa.py --duration 60

# 使用 AEC_AZIMUTH_VALUES 模式 (4 波束弧度值)
uv run doa.py --mode azimuth
```

> 需要 USB 控制权限，见 [Linux 权限配置](#linux-权限配置)。

### 降噪效果测试

```bash
# 分两步录制底噪和语音，对比信噪比
uv run noise_test.py

# 自定义每段录制时长
uv run noise_test.py --duration 3
```
