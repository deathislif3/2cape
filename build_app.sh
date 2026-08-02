#!/bin/bash
set -e

APP_NAME="2cape.app"
BUILD_DIR="$(pwd)/build"
APP_DIR="${BUILD_DIR}/${APP_NAME}"
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

echo "=== 开始编译打包带有图标的 2cape.app ==="

# 清理旧构建
rm -rf "${BUILD_DIR}"
rm -rf "./2cape.app"
mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR}"

# 1. 编译 Swift 可执行文件 (针对 macOS 12.0+)
echo "[1/4] 编译 Swift 代码..."
swiftc -O -parse-as-library main.swift \
  -o "${MACOS_DIR}/2cape" \
  -target arm64-apple-macosx12.0 \
  -sdk $(xcrun --show-sdk-path)

# 2. 部署资源文件（2cape.py、AppIcon.icns、app_header_icon.png）
echo "[2/4] 部署 App 图标与 2cape.py 脚本..."
cp "2cape.py" "${RESOURCES_DIR}/2cape.py"
if [ -f "AppIcon.icns" ]; then
  cp "AppIcon.icns" "${RESOURCES_DIR}/AppIcon.icns"
fi
if [ -f "app_header_icon.png" ]; then
  cp "app_header_icon.png" "${RESOURCES_DIR}/app_header_icon.png"
fi

# 3. 生成 Info.plist（注册 CFBundleIconFile）
echo "[3/4] 生成 Info.plist..."
cat << 'EOF' > "${CONTENTS_DIR}/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>2cape</string>
    <key>CFBundleIdentifier</key>
    <string>com.local.2cape</string>
    <key>CFBundleName</key>
    <string>2cape</string>
    <key>CFBundleDisplayName</key>
    <string>2cape</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 4. 复制到当前目录供用户使用
echo "[4/4] 导出 2cape.app 到当前目录..."
cp -R "${APP_DIR}" "./2cape.app"

echo "=== 编译打包成功！带图标应用位于: ./2cape.app ==="
