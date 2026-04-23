#!/usr/bin/env bash
# 编译 + 安装 + 加载 gs_usb.ko (Jetson L4T 无此模块, 需 OOT 构建)
# 用法:
#   bash build.sh          # 只 make
#   sudo bash build.sh install   # make + 装到 /lib/modules/.../extra + modprobe
set -euo pipefail

cd "$(dirname "$0")"

KREL="$(uname -r)"
KDIR="/lib/modules/${KREL}/build"

if [[ ! -d "$KDIR" ]]; then
    echo "缺内核头: $KDIR 不存在" >&2
    echo "装: sudo apt install nvidia-l4t-kernel-headers" >&2
    exit 1
fi

echo "[..] make -C $KDIR"
make -C "$KDIR" M="$PWD" modules

if [[ "${1:-}" != "install" ]]; then
    echo "[ok] 编出 gs_usb.ko  ($(stat -c%s gs_usb.ko) bytes)"
    echo "     下一步: sudo bash $0 install"
    exit 0
fi

if [[ $EUID -ne 0 ]]; then
    echo "install 阶段需要 sudo: sudo bash $0 install" >&2
    exit 1
fi

DEST="/lib/modules/${KREL}/extra"
echo "[..] install -> $DEST/gs_usb.ko"
install -d "$DEST"
install -m 0644 gs_usb.ko "$DEST/"

echo "[..] depmod -a"
depmod -a

# 开机自动加载
MODLOAD=/etc/modules-load.d/gs_usb.conf
if [[ ! -f "$MODLOAD" ]]; then
    echo gs_usb > "$MODLOAD"
    echo "[ok] 写入 $MODLOAD (开机自动 modprobe gs_usb)"
fi

echo "[..] modprobe gs_usb"
modprobe gs_usb

echo "[ok] 完成。验证:"
echo "     lsmod | grep gs_usb"
echo "     ls /sys/bus/usb/drivers/gs_usb/"
echo "     # 拔插 CANable 2.0, 然后:"
echo "     ip -details link show type can"
