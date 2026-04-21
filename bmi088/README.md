# BMI088 六轴 IMU 调试工具

本目录为 Jetson Orin Nano Developer Kit 上调试 Bosch BMI088 六轴 IMU（加速度计 + 陀螺仪）的工具集。**本项目仅测 SPI 模式**（模块物理切到 SPI 档）。

> 不熟悉 IMU 是什么、在豆豆里起什么作用，先读 [intro.md](./intro.md)。本文档偏接线 / 调试 / 使用手册。

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
| 39  | GND         | —                     | 40  | I2S0_SDOUT  | GPIO            |

补充事实：
- I/O 电平 3.3V，禁止送 5V 信号进 GPIO
- I2C Bus 7（pin 3/5）默认启用，可直接用 `i2cdetect -y -r 7`
- I2C Bus 1（pin 27/28）默认启用，但已有设备占用地址 `0x40` 和 `0x25`
- SPI0 和 SPI1 的所有针默认是 GPIO，不是 SPI；启用方式:
  `sudo /opt/nvidia/jetson-io/jetson-io.py` → Configure 40-pin Header → 勾选 **菜单里叫 "spi1" / "spi3"** (见下文"命名坑") → 保存重启 → `/dev/spidev0.0`, `spidev0.1`, `spidev1.0`, `spidev1.1` 出现
- SPI 能力: 2 组控制器，每组 2 路硬件 CS，最多 4 个硬件 CS 从设备
- UART1（pin 8/10）默认启用为 `/dev/ttyTHS0`

### 资料 2：BMI088 模块（蓝色中国 breakout，丝印 "BMI088V1.0"）

模块外观：
- 正面右上角有一个物理拨动开关，丝印 `SPI / IIC`，物理切换协议
- 背面 9 针排针（未焊接，用户自焊），从上到下丝印:

  | 序号 | IIC 模式名 | SPI 模式名 |
  | ---- | ---------- | ---------- |
  | 1    | VCC        | VCC        |
  | 2    | GND        | GND        |
  | 3    | ADO        | MISO       |
  | 4    | SDA        | MOSI       |
  | 5    | SCL        | SCLK       |
  | 6    | NC         | CSB1       |
  | 7    | NC         | CSB2       |
  | 8    | INT1       | INT1       |
  | 9    | INT3       | INT3       |

- 左列（ADO/SDA/SCL/NC/NC）在 IIC 模式有效
- 右列（MISO/MOSI/SCLK/CSB1/CSB2）在 SPI 模式有效
- VCC/GND/INT1/INT3 两种模式都用，物理是同一个针

### 资料 3：BMI088 芯片技术细节

#### 双芯片架构
- 模块内是两颗独立 die：加速度计 (BMA) + 陀螺仪 (BMG)
- 无论 I2C 还是 SPI，都必须当作两个独立设备访问（两个地址 / 两根 CS）

#### I2C 地址
- 加速度 ACC: `0x18` 或 `0x19`（取决于 SDO1/SA0_A 引脚上下拉，模块出厂固定）
- 陀螺   GYR: `0x68` 或 `0x69`（取决于 SDO2/SA0_G 引脚上下拉，模块出厂固定）
- 实际地址需要 `i2cdetect` 扫出来确认

#### CHIP_ID（寄存器 `0x00`）
- ACC CHIP_ID = `0x1E`
- GYR CHIP_ID = `0x0F`

#### 加速度计（ACC）关键寄存器
- `0x00` ACC_CHIP_ID（只读，= `0x1E`）
- `0x12` ACC_X_LSB（数据起始，6 字节 little-endian int16，顺序 X, Y, Z）
- `0x40` ACC_CONF
  - 写 `0xA8` = ODR 100 Hz, bwp=normal
  - 其他 ODR 编码详见 datasheet
- `0x41` ACC_RANGE
  - `0x00` = ±3g
  - `0x01` = ±6g
  - `0x02` = ±12g
  - `0x03` = ±24g
  - 标度换算: `value_m_s2 = raw_int16 * range_g * 9.81 / 32768`
- `0x7C` ACC_PWR_CONF（suspend 控制，`0x00` = 关闭 suspend）
- `0x7D` ACC_PWR_CTRL（`0x00` = off, `0x04` = on）
- `0x7E` ACC_SOFTRESET（写 `0xB6` 触发软复位）

#### 加速度计启动序列（必须，否则数据永远是 0）
1. 写 `0xB6` 到 `0x7E`（软复位）
2. 写 `0x04` 到 `0x7D`（PWR_CTRL → on）
3. 写 `0x00` 到 `0x7C`（PWR_CONF → 关 suspend）
4. 每步之间至少 sleep 50 ms

#### 陀螺仪（GYR）关键寄存器
- `0x00` GYR_CHIP_ID（只读，= `0x0F`）
- `0x02` GYR_X_LSB（数据起始，6 字节 little-endian int16，顺序 X, Y, Z）
- `0x0F` GYR_RANGE
  - `0x00` = ±2000 dps（默认，标度 `2000/32768` dps/LSB）
  - `0x01` = ±1000 dps
  - `0x02` = ±500 dps
  - `0x03` = ±250 dps
  - `0x04` = ±125 dps
- 陀螺仪上电即工作，不需要启动序列

#### SPI 模式的已知坑
- SPI 模式下，加速度计的第一次读响应的第一个字节是 dummy byte，必须丢弃
- I2C 模式下不存在此问题
- 具体读 N 字节: `xfer([addr|0x80, 0x00, 0xFF×N])`，返回长度 N+2，**前 2 字节丢弃**，后 N 字节是数据
- 陀螺仪 SPI 读无 dummy byte，标准流程

#### 物理合理性判据（静止时）
- 加速度三轴平方和开根号 ≈ 9.81 m/s²（容差 ±0.5 算正常）
- 陀螺仪三轴读数 < 1 dps（零偏正常范围）
- 翻转模块时，对应主导轴加速度符号翻转

---

## 本项目设计选择（基于上述资料）

- **接口**: SPI（模块拨到 SPI 档）
- **控制器**: Jetson SPI0（pin 19/21/23/24/26）
- **片选**: 两路硬件 CS 各接一个 die，**不用 GPIO 模拟**
  - `/dev/spidev0.0` (SPI0_CS0) → ACC (CSB1)
  - `/dev/spidev0.1` (SPI0_CS1) → GYR (CSB2)
- **供电**: 3.3V（pin 17），绝不接 5V
- **SPI 时钟**: 默认 1 MHz，可到 10 MHz 上限
- **SPI 模式**: mode 3 (CPOL=1, CPHA=1)
- **中断**: 本期不接 INT1/INT3，用 polling

## 接线方案

### 模块侧 DIP 开关
**必须拨到 "SPI" 档**（模块正面右上角）。拨错档位 `chip_id` 读出来会是 0。

### 接线对照表

| 模块丝印 (SPI) | 模块 Pin | Jetson J12 Pin | Jetson 信号 | 方向 |
|----------------|---------|----------------|-------------|------|
| VCC            | 1       | **17**         | 3.3V        | 供电 |
| GND            | 2       | **20**         | GND         | —    |
| MISO           | 3       | **21**         | SPI0_MISO   | Jetson ← BMI088 |
| MOSI           | 4       | **19**         | SPI0_MOSI   | Jetson → BMI088 |
| SCLK           | 5       | **23**         | SPI0_SCK    | Jetson → BMI088 |
| CSB1 (ACC)     | 6       | **24**         | SPI0_CS0    | Jetson → BMI088 → `/dev/spidev0.0` |
| CSB2 (GYR)     | 7       | **26**         | SPI0_CS1    | Jetson → BMI088 → `/dev/spidev0.1` |
| INT1           | 8       | —              | 悬空        | 本期不用（改 polling） |
| INT3           | 9       | —              | 悬空        | 本期不用 |

关键点：
- 模块丝印 `MISO/MOSI` 是**主机视角命名**，直连不要交叉
- 两颗 die 共 SCK/MOSI/MISO，只有 CS 分开
- **严禁把 VCC 接 5V**（pin 2/4 是 5V，别接错）
- INT1/INT3 本阶段不接；若后续要做中断驱动采样再接 GPIO + `gpiod`

### Jetson SPI0 启用

**坑警告**：JetPack 6.x 默认镜像上 `/dev/spidev0.0` / `spidev0.1` 节点**出厂就存在** (`spidev` 驱动已绑到内部 SPI 控制器)，但**40-pin 的物理针 pinmux 还是 GPIO**，SPI 控制器根本没路由到外面。直接用节点会误以为配好了，结果 `xfer2` 往"虚空"发，MISO 上收到的是 GPIO 输入电平（通常全 0）。**必须跑 `jetson-io.py` 把物理针 pinmux 切到 SPI 功能。**

```bash
sudo /opt/nvidia/jetson-io/jetson-io.py
# 菜单:
#   Configure 40-pin expansion header
#     → Configure header pins manually
#     → 找到一行显示 "spi1  (19,21,23,24,26)"，空格把星号从 unused 挪到 spi1
#     → Back → Save pin changes → Save and reboot to reconfigure pins
```

**命名坑**：jetson-io 菜单用 **SoC 内部控制器编号** (SPI1 / SPI3)，Linux 侧是 0-based 重排 (`/dev/spidev0.*` / `/dev/spidev1.*`)，资料 1 的 "SPI0 / SPI1" 也是 Linux 侧视角。别被菜单里的 "spi1" 误导接错针。对照：

| jetson-io 菜单 | 物理针 (J12) | Linux 节点 | 资料 1 叫法 |
|---------------|-------------|-----------|------------|
| **spi1** ← 本项目用这个 | 19 / 21 / 23 / 24 / 26 | `/dev/spidev0.{0,1}` | SPI0 |
| spi3 | 13 / 16 / 18 / 22 / 37 | `/dev/spidev1.{0,1}` | SPI1 |

重启后验证：

```bash
# 1. extlinux 应多出 FDT= 指向一份 -user-custom.dtbo
grep FDT /boot/extlinux/extlinux.conf

# 2. 节点仍在 + 驱动是 spidev
ls -l /dev/spidev0.*
readlink /sys/bus/spi/devices/spi0.0/driver        # → .../drivers/spidev

# 3. loopback 自测 Jetson SPI master 是否真的到了 40-pin:
#    杜邦线短接 pin 19 (MOSI) → pin 21 (MISO)，跑:
uv run probe.py --cs 0 --mode 3 --hz 1000000
# 预期 rx=[0x80, 0x00, ...] 首字节回送，说明 pinmux/master 都 OK
# 仍全 0 → jetson-io 没勾对 / 没重启 / 没保存
```

loopback 通过后再把 BMI088 接上去。

### spidev 权限

实测：**JetPack 6.x 出厂镜像默认已把 `/dev/spidev*` 归到 `gpio` 组 (mode 0660)，首次创建的用户也自动加入 `gpio` 组**，不用配 udev。直接验证：

```bash
ls -l /dev/spidev0.*
# crw-rw---- 1 root gpio 153, 0 ... /dev/spidev0.0

groups | tr ' ' '\n' | grep -E '^gpio$'    # 看到 "gpio" 即可
```

两条都 OK 则跳过本节。不在 `gpio` 组的老镜像：`sudo usermod -aG gpio $USER` 后重新登录。其他发行版若 `/dev/spidev*` 没有默认组，可以自建一条 udev 规则：

```bash
sudo groupadd -f spi
sudo usermod -aG spi $USER
echo 'KERNEL=="spidev*", GROUP="spi", MODE="0660"' | sudo tee /etc/udev/rules.d/99-spidev.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

懒得配时也可以直接 `sudo uv run <script>.py`。

## 上电前核对清单

- [ ] 模块拨动开关在 **SPI**
- [ ] VCC → Jetson pin 17 (3.3V)，**不是** 5V
- [ ] GND 共地（pin 20）
- [ ] MISO / MOSI / SCLK / CS0 / CS1 一一对应（见接线表）
- [ ] `/dev/spidev0.0` / `/dev/spidev0.1` 存在且当前用户可读写
- [ ] **已跑过 `jetson-io.py` 勾选 spi0 并重启**（光有节点不代表 pinmux 到位，见下文；loopback 测过才算数）
- [ ] 模块通电后不发烫

## 使用

> 脚本复用 `device.py` 里的 `Bmi088` 类 (封装 SPI 读写 / ACC 启动序列 / 量程换算)。`uv sync` 装依赖；首次在 Jetson 上 `spidev` 是源码编译包，会比较慢。

### 检测设备

```bash
uv run detect.py
```

列出 `/dev/spidev*` 节点，对 CS0/CS1 各发一次 `CHIP_ID` 读，验证 ACC (`0x1E`) / GYR (`0x0F`) 是否响应正确。

### 实时流 / Hz 测试

```bash
# 默认持续 10s，打印实时 ACC+GYR 并统计有效采样率
uv run stream.py

# 自定义时长 / SPI 时钟
uv run stream.py --duration 30 --spi-hz 5000000

# 保存 CSV 供后处理
uv run stream.py --save out/stream.csv
```

### IMU 测试（重力 / 零偏 / 姿态）

对齐 `realsense/imu.py`：静置一段时间，检查重力模长、陀螺零偏、重力主方向。

```bash
uv run imu.py
# 换量程 / 采样时长
uv run imu.py --acc-range 6 --gyr-range 500 --duration 10
```

判据（静止时，详见资料 3）：
- 加速度模长 `≈ 9.81 m/s²`，容差 `±0.5`
- 陀螺模长 `< 1 dps (≈ 0.017 rad/s)`
- 翻转模块时主导轴符号应翻转

### 局域网看结果

```bash
uv run main.py              # 0.0.0.0:8001
```

浏览器打开 `http://<jetson IP>:8001/out/` 看保存的 CSV / JSON。

## 故障排查

| 现象 | 可能原因 / 处理 |
|------|----------------|
| `/dev/spidev0.0` 不存在 | 极少见 — SPI 控制器被某个配置关掉了，跑 `jetson-io.py` 重新勾 SPI0 |
| 节点在但 loopback 也读全 0 | **pinmux 还在 GPIO**，jetson-io 没跑 / 没重启 / 没保存；或勾错到 SPI1；或 `/boot/extlinux/extlinux.conf` 缺 `FDT=...-user-custom.dtbo` 一行 |
| `PermissionError: /dev/spidev0.0` | 少见 (JetPack 默认用户在 `gpio` 组)；`groups` 看一下，缺则 `sudo usermod -aG gpio $USER` + 重新登录；或直接 `sudo uv run` |
| `CHIP_ID` 读出 `0x00` / `0xFF` | 拨动开关没在 SPI 档 / CS 接错 / MISO 断线 / VCC 未通 |
| ACC CHIP_ID 对但数据全 0 | 漏做启动序列（软复位 + PWR_CTRL=`0x04` + PWR_CONF=`0x00`） |
| ACC CHIP_ID 读出左移 / 错位 | 没丢 SPI 读的 dummy byte；或 SPI 模式不是 mode 3 |
| GYR CHIP_ID 对但数据抖动大 | SPI 时钟过高（>10 MHz）；地线太长；电源噪声 |
| 重力模长偏离 >0.5 m/s² | 设备不静止 / 模块标定偏移；或量程寄存器没写入（默认值确认一下） |
| 陀螺零偏 >1 dps | 温升 / 未静置；不是故障，做一次静止零偏标定减掉即可 |

## 参考

- BMI088 datasheet: https://www.bosch-sensortec.com/products/motion-sensors/imus/bmi088/
- Jetson Orin Nano 40-pin J12 pinout: https://www.jetson-ai-lab.com/pinout/jetson-orin-nano.html
- jetson-io 配置工具: `/opt/nvidia/jetson-io/jetson-io.py` (也有 `config-by-hardware.py` / `config-by-function.py` / `config-by-pin.py` 非交互版本)
- Linux spidev 接口文档: https://www.kernel.org/doc/html/latest/spi/spidev.html
