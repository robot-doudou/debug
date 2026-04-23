#!/usr/bin/env bash
# 达妙电机调试一次性环境安装: udev 规则 (USB 权限 + CANable 插上自动拉 1M)。
# 需要 sudo; 幂等 (已存在则跳过)。
#
# Jetson 坑: Orin SoC 内置 MTTCAN 控制器通常占 can0, CANable 会被 gs_usb
# 分到 can1。旧版 setup.sh 硬编 can0-up.service 是错的——它会把 SoC CAN
# 拉成 1M, 跟 CANable 没关系。新版按 VID:PID 匹配 CANable, 不管叫啥名都对。
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "请用 sudo 运行: sudo bash setup.sh" >&2
    exit 1
fi

USB_RULE=/etc/udev/rules.d/99-canable.rules
UP_RULE=/etc/udev/rules.d/80-candleLight-up.rules
OLD_SERVICE=/etc/systemd/system/can0-up.service

# --- 清理旧的 can0-up.service (按 can0 名字硬编, Jetson 上会误拉 SoC MTTCAN) ---
if [[ -f "$OLD_SERVICE" ]]; then
    echo "[清理] 旧版 $OLD_SERVICE (Jetson 上会误拉 SoC MTTCAN, 不要了)"
    systemctl disable --now can0-up.service 2>/dev/null || true
    rm -f "$OLD_SERVICE"
    systemctl daemon-reload
fi

# --- USB 权限 udev 规则 ---
# 已存在且包含 DFU 条目则跳过; 缺失 DFU 条目 (老版本) 强制覆盖更新
if [[ -f "$USB_RULE" ]] && grep -q "0483" "$USB_RULE"; then
    echo "[skip] $USB_RULE 已是最新版本"
else
    if [[ -f "$USB_RULE" ]]; then
        echo "[更新] $USB_RULE 缺 DFU 条目, 覆盖旧版"
    fi
    cat > "$USB_RULE" <<'EOF'
# Makerbase CANable 2.0 (normaldotcom fork)
# slcan 固件
SUBSYSTEM=="usb", ATTR{idVendor}=="16d0", ATTR{idProduct}=="117e", MODE="0666"
# candleLight 固件 (gs_usb)
SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666"
# STM32 DFU 模式 (烧固件时设备 VID:PID 会临时变成这个)
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="df11", MODE="0666"
EOF
    echo "[ok]   写入 $USB_RULE"
fi

# --- CANable 自动拉 1M udev 规则 ---
# 触发条件: net 子系统新增接口, 父 USB 设备 VID=1d50 PID=606f (candleLight 固件)
# 动作: ip link set <kname> type can bitrate 1000000 up
# %k 是内核名 (can0 / can1 / ...), 不管 Jetson 把它分到哪都对
if [[ -f "$UP_RULE" ]]; then
    echo "[skip] $UP_RULE 已存在"
else
    cat > "$UP_RULE" <<'EOF'
# CANable 2.0 (candleLight) 插上自动以 1 Mbps 拉起
# 注意: ip link 必须拆两条. "type can bitrate X up" 会把 up 当成 CAN 类型参数, iproute2 拒收.
ACTION=="add", SUBSYSTEM=="net", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="606f", \
    RUN+="/sbin/ip link set %k type can bitrate 1000000", \
    RUN+="/sbin/ip link set %k up"
EOF
    echo "[ok]   写入 $UP_RULE"
fi

# --- 生效 ---
echo "[..]   重载 udev"
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --action=add
udevadm trigger --subsystem-match=net --action=add

echo ""
echo "完成。下一步:"
echo "  1. 确认 CANable 2.0 已烧 candleLight 固件 (VID 1d50:606f), 否则先 fw_update.py"
echo "  2. Jetson 还要装 gs_usb 驱动: cd gs_usb_mod && sudo bash build.sh install"
echo "  3. 拔插一次 CANable, 自动以 1M 拉起"
echo "  4. 检查: uv run detect.py"
