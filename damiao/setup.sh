#!/usr/bin/env bash
# 达妙电机调试一次性环境安装: udev 规则 + can0 systemd unit。
# 需要 sudo; 幂等 (已存在则跳过)。
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "请用 sudo 运行: sudo bash setup.sh" >&2
    exit 1
fi

UDEV_RULE=/etc/udev/rules.d/99-canable.rules
SERVICE=/etc/systemd/system/can0-up.service

# --- udev 规则 ---
if [[ -f "$UDEV_RULE" ]]; then
    echo "[skip] $UDEV_RULE 已存在"
else
    cat > "$UDEV_RULE" <<'EOF'
# Makerbase CANable 2.0 (normaldotcom fork)
# slcan 固件
SUBSYSTEM=="usb", ATTR{idVendor}=="16d0", ATTR{idProduct}=="117e", MODE="0666"
# candleLight 固件 (gs_usb)
SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="606f", MODE="0666"
EOF
    echo "[ok]   写入 $UDEV_RULE"
fi

# --- systemd unit ---
if [[ -f "$SERVICE" ]]; then
    echo "[skip] $SERVICE 已存在"
else
    cat > "$SERVICE" <<'EOF'
[Unit]
Description=Bring up can0 at 1 Mbps (DaMiao motor bus)
BindsTo=sys-subsystem-net-devices-can0.device
After=sys-subsystem-net-devices-can0.device

[Service]
Type=oneshot
ExecStart=/usr/sbin/ip link set can0 up type can bitrate 1000000
ExecStop=/usr/sbin/ip link set can0 down
RemainAfterExit=yes

[Install]
WantedBy=sys-subsystem-net-devices-can0.device
EOF
    echo "[ok]   写入 $SERVICE"
fi

# --- 生效 ---
echo "[..]   重载 udev 与 systemd"
udevadm control --reload-rules
udevadm trigger
systemctl daemon-reload
systemctl enable can0-up.service || true

echo ""
echo "完成。下一步:"
echo "  1. 确认 CANable 2.0 已烧 candleLight 固件 (VID 1d50:606f)"
echo "     如仍是 slcan (16d0:117e), 先跑 uv run fw_update.py"
echo "  2. 插 USB, 应自动触发 can0 起来"
echo "  3. 检查: ip -details link show can0"
