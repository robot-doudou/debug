# INA228 电流/电压/功率监测 调试工具

本目录为 Jetson Orin Nano Developer Kit 上调试 TI **INA228** 85V、20-bit、I²C 电流/功率监测芯片的工具集。接在豆豆 6S 电池输出端做**总功耗遥测**。

> 不熟悉 INA228 是什么 / 能用来干嘛，先读 [intro.md](./intro.md)。本文档偏接线 / 调试 / 使用手册。

---

## 硬件参考资料

### 资料 1：Jetson Orin Nano Developer Kit — 40-pin J12 完整 pinout

| Pin | 功能 1 (主) | 功能 2 (备选)         | Pin | 功能 1 (主) | 功能 2 (备选)   |
| --- | ----------- | --------------------- | --- | ----------- | --------------- |
| 1   | 3.3V        | —                     | 2   | 5.0V        | —               |
| 3   | I2C1_SDA    | I2C Bus 7（默认启用） | 4   | 5.0V        | —               |
| 5   | I2C1_SCL    | I2C Bus 7（默认启用） | 6   | GND         | —               |
| 7   | GPIO09      | AUDIO_MCLK            | 8   | UART1_TX    | /dev/ttyTHS0    |
| 9   | GND         | —                     | 10  | UART1_RX    | /dev/ttyTHS0    |
| 11  | UART1_RTS   | GPIO                  | 12  | I2S0_SCLK   | GPIO            |
| 13  | SPI1_SCK    | GPIO                  | 14  | GND         | —               |
| 15  | GPIO12      | PWM                   | 16  | SPI1_CS1    | GPIO            |
| 17  | 3.3V        | —                     | 18  | SPI1_CS0    | GPIO            |
| 19  | SPI0_MOSI   | GPIO                  | 20  | GND         | —               |
| 21  | SPI0_MISO   | GPIO                  | 22  | SPI1_MISO   | GPIO            |
| 23  | SPI0_SCK    | GPIO                  | 24  | SPI0_CS0    | GPIO            |
| 25  | GND         | —                     | 26  | SPI0_CS1    | GPIO            |
| 27  | I2C0_SDA    | I2C Bus 1             | 28  | I2C0_SCL    | I2C Bus 1       |
| 29  | GPIO01      | —                     | 30  | GND         | —               |
| 31  | GPIO11      | —                     | 32  | GPIO07      | PWM             |
| 33  | GPIO13      | PWM                   | 34  | GND         | —               |
| 35  | I2S0_FS     | GPIO                  | 36  | UART1_CTS   | GPIO            |
| 37  | SPI1_MOSI   | GPIO                  | 38  | I2S0_SDIN   | GPIO            |
| 39  | GND         | —                     | 40  | UART1_CTS   | GPIO            |

补充事实：
- I/O 电平 3.3V，严禁送 5V 信号进 GPIO
- **I2C Bus 7 (pin 3/5) 默认启用**，可直接 `i2cdetect -y -r 7`
- I2C Bus 1 (pin 27/28) 默认启用，**已有设备占用 `0x40` / `0x25`** —— INA228 默认地址 `0x40` 会冲突，本项目走 Bus 7
- jetson-io 菜单里 pin 3/5 叫 `i2c8`，pin 27/28 叫 `i2c2` (SoC 控制器编号)，不是 Linux 侧的 `/dev/i2c-7` / `-1`

### 资料 2：INA228 模块（4 针）

| 丝印 | 实际含义 | 说明 |
|------|---------|------|
| UCC  | **VCC**（供电，模块标签拼写错误） | 2.7–5.5V，建议 3.3V 与 Jetson I/O 电平匹配 |
| SDA  | I²C 数据 | 模块板载 SDA 上拉到 VCC |
| SCL  | I²C 时钟 | 模块板载 SCL 上拉到 VCC |
| GND  | 公共地 | 和 Jetson 共地 |

模块另一侧是 shunt 电阻 + IN+/IN- 两个大电流端子，**已接在电池回路上**（本期调试不涉及）。

### 资料 3：INA228 芯片要点

#### I²C 地址
由 A0 / A1 引脚决定。本模块板载 A0=A1=GND → **`0x40`**。
全部 16 种组合（A0/A1 ∈ {GND, VS, SDA, SCL}）见 datasheet Table 7-2。

#### 关键寄存器

| 寄存器 | 名称 | 位宽 | 说明 |
|--------|------|------|------|
| `0x00` | CONFIG | 16 | bit 15 = RST（写 1 软复位）；bit 4 = ADCRANGE (0=±163.84mV, 1=±40.96mV) |
| `0x01` | ADC_CONFIG | 16 | MODE / VBUSCT / VSHCT / VTCT / AVG，默认 `0xFB68` = 连续 shunt+bus+temp，每次 1052 µs，平均 1 次 |
| `0x02` | SHUNT_CAL | 15 | 校准值，= `13107.2×10⁶ × CURRENT_LSB × R_SHUNT` (ADCRANGE=0) |
| `0x04` | VSHUNT | 24 | signed，LSB = 312.5 nV (ADCRANGE=0) or 78.125 nV (ADCRANGE=1) |
| `0x05` | VBUS | 24 | signed，LSB = 195.3125 µV，量程 0–85V |
| `0x06` | DIETEMP | 16 | signed，LSB = 7.8125 m°C (高 12 位有效) |
| `0x07` | CURRENT | 24 | signed，LSB = CURRENT_LSB (由 SHUNT_CAL 决定) |
| `0x08` | POWER | 24 | unsigned，LSB = 3.2 × CURRENT_LSB |
| `0x09` | ENERGY | 40 | unsigned，LSB = 16 × POWER_LSB × 时间 |
| `0x0A` | CHARGE | 40 | signed，LSB = CURRENT_LSB × 时间 |
| `0x0B` | DIAG_ALRT | 16 | 状态标志、故障位（CNVRF 数据就绪位） |
| `0x3E` | MANUFACTURER_ID | 16 | = `0x5449` ("TI") |
| `0x3F` | DEVICE_ID | 16 | = `0x228?` (高 12 位 = `0x228`，低 4 位 = die revision) |

#### 关键换算
- **CURRENT_LSB** = `I_MAX_expected / 2^19` （用户选，决定分辨率和量程）
- **SHUNT_CAL** = `13107.2e6 × CURRENT_LSB × R_SHUNT` （ADCRANGE=0）
- **SHUNT_CAL (ADCRANGE=1)** = 上式 × 4
- VSHUNT ADC 范围（硬件）:
  - ADCRANGE=0: ±163.84 mV → 最大可测电流 = `163.84e-3 / R_SHUNT`
  - ADCRANGE=1: ±40.96 mV → 高分辨率模式（4× 精度）

#### 上电启动序列（最简）
1. 软复位：向 CONFIG (`0x00`) 写 `0x8000`
2. 写 SHUNT_CAL (`0x02`) = 根据公式计算的校准值
3. （可选）改 CONFIG / ADC_CONFIG 配量程、平均次数
4. 读 VBUS / CURRENT / POWER / DIETEMP

启动无必需延迟，但软复位后等 10 ms 更稳。

#### 数据读取小提醒
- 24-bit 值在 I²C 上是**大端 3 字节**，符号位在最高字节 bit 7
- VSHUNT / VBUS / CURRENT 的 24-bit 寄存器**低 4 位保留**，使用前右移 4 位（得到 20-bit signed 有效数据）
- 40-bit 寄存器读 5 字节
- 所有多字节寄存器必须在一次 I²C 读事务中连读，否则会撕裂

---

## 本项目参数（核算结果）

| 参数 | 数值 | 备注 |
|------|------|------|
| R_SHUNT | **2 mΩ** (模块丝印 R002) | 已焊在模块上 |
| I_MAX 期望 | **100 A** | 6S 四足峰值 |
| ADCRANGE | **0 (±163.84 mV)** | 高量程 |
| CURRENT_LSB | **200 µA** = 2×10⁻⁴ A | 圆整后 |
| SHUNT_CAL | **5243** = `0x147B` | 写入 `0x02` |
| POWER_LSB | **640 µW** | = 3.2 × CURRENT_LSB |
| 最大可测电流 | **81.92 A** | 受 ADC ±163.84 mV 限制 |
| VBUS 量程 | 0–85V（硬件），本项目 6S 25.2V max | 留余量充足 |

### ⚠️ 电流截断提示

`I > 81.92 A` 会被 ADC **硬限幅**，CURRENT 寄存器停在 `0x7FFFF << 4`。日常行走峰值通常在 60–80A 可正常测量；起步冲击 / 跌倒 / 短路瞬间可能截断。**不影响电压和功耗，但电流读数在截断区不准确**。

彻底解决：换 1 mΩ shunt（变 ±163.84 A 量程，分辨率减半）或升级到 INA228 兼容但更大量程的 INA229。

## 接线方案

### 接线对照表

| 模块丝印 | 模块含义 | Jetson J12 Pin | 方向 |
|----------|---------|----------------|------|
| UCC (VCC) | 2.7-5.5V 供电 | **pin 1** (3.3V) | 供电 |
| SDA       | I²C 数据      | **pin 3** (I2C1_SDA, Bus 7) | 双向 |
| SCL       | I²C 时钟      | **pin 5** (I2C1_SCL, Bus 7) | Jetson → 模块 |
| GND       | 公共地        | **pin 6** (GND)  | —    |

四根线集中在 header 最顶端 2 行（pins 1/3/5/6），走线短。

关键点：
- **必须用 Bus 7（pin 3/5）**，Bus 1（pin 27/28）已被内部设备占用 0x40 导致冲突
- VCC 用 **pin 1 的 3.3V**（pin 17 已被 BMI088 占用，40-pin 上只有两个 3.3V 源）
- **不要接 5V (pin 2/4)**，否则 SDA/SCL 会上拉到 5V 电平 → 干扰 Jetson 3.3V GPIO
- 本期不接 ALERT（模块根本没这一脚）；以后做阈值中断再外拉
- I²C 总线不需要额外上拉（模块板载已有）

### I2C 总线启用状态

资料 1 提到 Bus 1 和 Bus 7 **默认启用**。实测验证：

```bash
ls /dev/i2c-*               # 应看到 /dev/i2c-0, /dev/i2c-1, /dev/i2c-7 等
groups | tr ' ' '\n' | grep '^i2c$'    # 用户应在 i2c 组
```

Jetson 出厂把用户加入 `i2c` 组且 `/dev/i2c-*` 属组 `i2c`，**不用 udev / sudo**。

### 上电前核对清单

- [ ] UCC 接 Jetson **3.3V（pin 1）**，不是 5V，也不是 pin 17（已被 BMI088 占用）
- [ ] GND 共地 (pin 6，紧挨 SCL)
- [ ] SDA/SCL 一一对应（不要和 Bus 1 的 pin 27/28 混）
- [ ] 模块供电后不发烫（模块 VCC 有稳压，>5V 会导致自发热）
- [ ] shunt 电阻已接入电池回路（电池 − → IN+ → shunt → IN- → 负载/Jetson 电源）—— 已由用户完成
- [ ] 用 `i2cdetect -y -r 7` 扫到 `0x40`

## 使用

> 脚本在接线完成后开发。每个脚本复用 `device.py` 里的 `Ina228` 类（封装 I²C 读写、SHUNT_CAL、单位换算）。`uv sync` 装依赖。

### 检测设备

```bash
uv run detect.py
```

扫 `/dev/i2c-7`，对 `0x40` 读 `MANUFACTURER_ID` (期望 `0x5449`) 和 `DEVICE_ID` (期望 `0x228x`)。

### 一次性读数

```bash
# 电压 / 电流 / 功率 / 温度 一次采样
uv run read.py

# 自定义 R_SHUNT / I_MAX 重算 CURRENT_LSB (如果换了电阻或期望量程)
uv run read.py --r-shunt 0.001 --i-max 160
```

### 实时流

```bash
# 默认持续 10s，打印并统计采样率
uv run stream.py

# 保存 CSV
uv run stream.py --save auto --duration 60

# 高分辨率模式 (I<20A 时电流精度 ×4，超过即截断)
uv run stream.py --adcrange 1
```

### 局域网查看结果

```bash
uv run main.py              # 0.0.0.0:8001
```

## 故障排查

| 现象 | 可能原因 / 处理 |
|------|----------------|
| `i2cdetect` 在 Bus 7 扫不到任何地址 | 模块没供电 / UCC 接到 GND / SDA-SCL 互换 |
| 扫到地址但不是 0x40 | 模块 A0/A1 没全拉地，看模块丝印确认实际地址，传 `--addr` 参数 |
| MANUFACTURER_ID 不是 `0x5449` | 读回字节序反了（INA228 是大端）/ 地址错 / 挂了别的芯片 |
| 电流读数永远 0 | SHUNT_CAL 没写 / 写成 0 / ADCRANGE 位没配对公式 |
| 电流读数偏差 2× / 4× | ADCRANGE 切换后 SHUNT_CAL 没跟着改（两种模式公式不同，driver 必须跟 ADCRANGE 联动） |
| 大电流时读数封顶在 ~82A | ADC 硬限幅，见"电流截断提示"；换小 shunt 或接受 |
| VBUS 读出负值 | IN+ IN- 接反（电池正极 → IN+，负载 → IN-，电流从 IN+ 流向 IN-） |
| 读数抖动大 | ADC_CONFIG 平均次数太少 (默认 1 次)；调到 16/64/128 |

## 参考

- INA228 datasheet: https://www.ti.com/product/INA228
- Jetson Orin Nano 40-pin J12 pinout: https://www.jetson-ai-lab.com/pinout/jetson-orin-nano.html
- Linux i2c-dev 接口文档: https://www.kernel.org/doc/html/latest/i2c/dev-interface.html
- smbus2 Python 库: https://github.com/kplindegaard/smbus2
