#!/usr/bin/env bash
# Jetson (aarch64) 用: 从源码编 pyrealsense2 并装进 venv。
#
# 为什么需要这个:
#   - PyPI pyrealsense2 aarch64 wheel 从 2.57 起打了假的 manylinux2014 标 (实际要 glibc 2.38)
#   - 2.56.5 wheel 虽然兼容 glibc 2.35 但 bundled librealsense 的 IMU/HID 初始化在 Jetson 内核上炸
#     (No HID info provided → rs2_create_device bad optional access)
#   - Intel apt 源的 librealsense 在 Jetson 上工作但不提供 python3-pyrealsense2 包
#
# 解决: 自己编 librealsense v2.57.7 + Python binding, 开 FORCE_RSUSB_BACKEND 走纯 libusb,
#       绕开 V4L2+HID 那条坑路。IMU 也能通。产物装进本子项目 venv。
#
# 运行前提: sudo apt install cmake libusb-1.0-0-dev pybind11-dev libssl-dev
# 用法:     scripts/build_pyrealsense2.sh [clean]

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="v2.57.7"
SRC_DIR="$PROJECT_DIR/third_party/librealsense-${VERSION#v}"
BUILD_DIR="$SRC_DIR/build"
VENV="$PROJECT_DIR/.venv"

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "[error] venv 不存在, 先在 $PROJECT_DIR 跑 uv sync" >&2
    exit 1
fi

PY_VER=$("$VENV/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_ABI=$("$VENV/bin/python" -c 'import sys; print(f"cpython-{sys.version_info.major}{sys.version_info.minor}-aarch64-linux-gnu")' | sed 's/cpython/cpython/')
SITE_PKG="$VENV/lib/python${PY_VER}/site-packages/pyrealsense2"

echo "[info] project : $PROJECT_DIR"
echo "[info] python  : $PY_VER"
echo "[info] target  : $SITE_PKG"

if [[ "${1:-}" == "clean" ]]; then
    echo "[clean] 删除 $BUILD_DIR 和 $SITE_PKG"
    rm -rf "$BUILD_DIR" "$SITE_PKG"
    exit 0
fi

# 1. 拉源码 (浅克隆, ~150MB)
if [[ ! -d "$SRC_DIR/.git" ]]; then
    echo "[clone] $VERSION → $SRC_DIR"
    mkdir -p "$PROJECT_DIR/third_party"
    git clone --depth 1 --branch "$VERSION" https://github.com/IntelRealSense/librealsense.git "$SRC_DIR"
else
    echo "[skip] 源码已存在: $SRC_DIR"
fi

# 2. cmake 配置 (若 CMakeCache 已在就跳过, 除非传 clean)
if [[ ! -f "$BUILD_DIR/CMakeCache.txt" ]]; then
    echo "[cmake] 配置..."
    mkdir -p "$BUILD_DIR"
    cmake -S "$SRC_DIR" -B "$BUILD_DIR" \
        -DBUILD_PYTHON_BINDINGS=ON \
        -DPYTHON_EXECUTABLE="$VENV/bin/python" \
        -DFORCE_RSUSB_BACKEND=ON \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_GRAPHICAL_EXAMPLES=OFF \
        -DBUILD_TOOLS=OFF \
        -DCHECK_FOR_UPDATES=OFF \
        -DBUILD_UNIT_TESTS=OFF \
        -DBUILD_WITH_CUDA=OFF \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_RPATH='$ORIGIN' \
        -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON
else
    echo "[skip] CMake 已配置: $BUILD_DIR (传 clean 参数可重配)"
fi

# 3. 编译 (~15 min on Orin Nano)
echo "[make] -j$(nproc) pyrealsense2 pyrsutils"
cmake --build "$BUILD_DIR" --target pyrealsense2 pyrsutils -- -j"$(nproc)"

# 4. 产物装进 venv
RELEASE="$BUILD_DIR/Release"
PY_SO="pyrealsense2.${PY_ABI}.so"
if [[ ! -f "$RELEASE/${PY_SO}.2.57.7" ]]; then
    echo "[error] 没找到 $RELEASE/${PY_SO}.2.57.7, Python 版本跟编译时的不一致?" >&2
    ls "$RELEASE" >&2
    exit 1
fi

echo "[install] → $SITE_PKG"
mkdir -p "$SITE_PKG"
cp "$SRC_DIR/wrappers/python/pyrealsense2/__init__.py" "$SITE_PKG/"
cp -a "$RELEASE"/pyrealsense2.${PY_ABI}.so* "$SITE_PKG/"
cp -a "$RELEASE"/pyrsutils.${PY_ABI}.so* "$SITE_PKG/"
cp -a "$RELEASE"/librealsense2.so* "$SITE_PKG/"

# 5. 自检
echo "[verify] import..."
"$VENV/bin/python" -c "import pyrealsense2 as rs; ctx = rs.context(); print(f'devices: {len(ctx.query_devices())}')"
echo "[done] OK"
