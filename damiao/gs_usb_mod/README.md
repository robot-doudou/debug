# gs_usb OOT 模块 (Jetson L4T 补丁)

## 为啥要有这个目录

JetPack 6 的 L4T 内核 (`5.15.x-tegra`) **没有编 `gs_usb` 驱动**。NVIDIA 在他们的内核源码里手动删掉了 `drivers/net/can/usb/gs_usb.c`，同目录下 `kvaser_usb / etas_es58x / peak_usb` 都保留着 —— 他们是故意剪的，不是配置未开。

后果：CANable 2.0 (candleLight 固件, VID:PID `1d50:606f`) 插上 Jetson 只能在 `lsusb` 看到，**不会生成 `canN` netdev**（因为没有驱动 claim 这颗 USB 设备，自然没人调 `register_netdev()`）。

Ubuntu 主线仓库的 `linux-modules-*` 包里虽然有 `gs_usb.ko`，但它们是针对 `5.15.0-XX-generic` / `-raspi` / `-aws` 这些泛型内核编的，vermagic 和 `5.15.185-tegra` 对不上，`modprobe` 会拒；`--force` 硬塞可能 oops，不值得。

所以：**把 mainline `gs_usb.c` 拉过来，按 OOT 模块编一份。** 一次搞定。

## 前置

- Jetson Orin 跑 JetPack 6.x (L4T 36.x)，`uname -r` 形如 `5.15.185-tegra`
- `nvidia-l4t-kernel-headers` 已装（`dpkg -l | grep nvidia-l4t-kernel-headers`）
- `/lib/modules/$(uname -r)/build` 软链存在（指向 `/usr/src/linux-headers-.../kernel-source`）
- `gcc` + `make` 在 PATH

```bash
# 一次性依赖
sudo apt install nvidia-l4t-kernel-headers build-essential
```

## 编 + 装

```bash
cd damiao/gs_usb_mod

# 只编
bash build.sh

# 编 + 装 + modprobe + 开机自载
sudo bash build.sh install
```

`install` 阶段做的事：

1. `install -m 0644 gs_usb.ko /lib/modules/$(uname -r)/extra/`
2. `depmod -a`（刷模块依赖索引）
3. 写 `/etc/modules-load.d/gs_usb.conf`（开机自动 `modprobe gs_usb`）
4. 当场 `modprobe gs_usb`

## 验证

```bash
# 1. 模块已加载
lsmod | grep gs_usb
# 预期: gs_usb  XXXXX  0
#       usbcore XXXXX  N gs_usb,...

# 2. USB 驱动挂上
ls /sys/bus/usb/drivers/gs_usb/
# 预期有 1-X.Y:1.0 之类的绑定项 (CANable 插着时)

# 3. netdev 出现
ip -details link show type can
# 预期: can0 driver=mttcan (SoC 内置)
#       can1 driver=gs_usb (CANable), parentdev 形如 usb-3610000.xhci-2.3

# 4. 协议层探活 (damiao 侧已改为自动识别接口)
uv run ../detect.py --id 1
```

## 实测记录 (Jetson Orin Nano Developer Kit)

- `uname -r`: `5.15.185-tegra`
- `gs_usb.ko` 体积: ~100 KB
- CANable 2.0 上去后枚举为 **`can1`**（`can0` 被 SoC MTTCAN 占）
- `detect.py` 自动按驱动 (`gs_usb`) 挑 `can1`, 不用手动指定接口

`damiao/` 主 README 和所有脚本已改为自动识别驱动，不再硬编 `can0`。`setup.sh` 也改成按 VID:PID 匹配的 udev 规则自动拉 1M，不再依赖按名字硬编的 systemd unit。

## 升级 / 维护

- **升内核时（`uname -r` 变）**：重跑 `sudo bash build.sh install`。模块装在 `/lib/modules/<新内核>/extra/` 下，旧版不用删（`depmod` 会自动只认新内核目录里的）。
- **升 `gs_usb.c` 自身**：`curl` 拉对应 stable tag 的 `gs_usb.c` 覆盖；更新 `SOURCE` 里的 tag + sha256；重编重装。
- **彻底卸载**：`sudo make -C . uninstall && sudo rm -f /etc/modules-load.d/gs_usb.conf && sudo rmmod gs_usb`

## 坑

- **`modprobe: FATAL: Module gs_usb not found`**：装完没跑 `depmod -a`，或 `.ko` 装到了错的内核版本目录。检查 `find /lib/modules -name gs_usb.ko`。
- **`insmod: ERROR: could not insert module: Invalid module format`**：`.ko` 是拿别的内核头编的，或编译时 `KDIR` 指错。确认 `/lib/modules/$(uname -r)/build` 解析到 `5.15.185-tegra` 对应的源树。
- **模块装了但插 CANable 还是不出 `canN`**：可能 CANable 固件还是 slcan (`16d0:117e`)，gs_usb 只认 candleLight (`1d50:606f`)。`lsusb` 核对。
- **`can1` 出现但收不到帧**：别忘了 `sudo ip link set can1 up type can bitrate 1000000`。插上到能用要两步：驱动枚举 netdev + `ip link` 拉起 + 对齐波特率。

## 文件

- `gs_usb.c` — vendored from `linux-stable` tag `v5.15.185`, 详见 `SOURCE`
- `Makefile` — 标准 OOT 模块 Makefile (`obj-m := gs_usb.o`)
- `build.sh` — 一键 make / install 脚本
- `SOURCE` — `gs_usb.c` 的来源 / 版本 / 哈希, 不要删

## 参考

- mainline 源：<https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/can/usb/gs_usb.c?h=linux-5.15.y>
- candleLight 固件：<https://github.com/normaldotcom/candleLight_fw>
- 为啥 NVIDIA 剪 gs_usb：官方没说。同类故事另见 `uvcvideo` / `v4l2loopback`，NVIDIA 习惯按他们自己的"嵌入式场景需要"裁剪内核
