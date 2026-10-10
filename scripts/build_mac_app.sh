#!/bin/bash
# Build Jarvis.app for macOS: the dashboard in its own window, with the microphone.
# Uses only Apple's tools (swiftc, sips, iconutil, codesign). No Xcode project, no packages.
#   scripts/build_mac_app.sh            build into mac/build/ and install into ~/Applications
#   scripts/build_mac_app.sh --no-install
# The app stores this folder's path and your shell PATH (Jarvis needs the `claude` CLI), so
# build it again after moving the Jarvis folder. The build output is git-ignored.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/mac/Jarvis"
BUILD="$REPO/mac/build"
APP="$BUILD/Jarvis.app"

[ -x "$REPO/.venv/bin/jarvis" ] || { echo "Run scripts/setup.sh first (no .venv/bin/jarvis)."; exit 1; }
command -v swiftc >/dev/null || { echo "swiftc not found: install Xcode or the Command Line Tools."; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "Compiling…"
swiftc -O -o "$APP/Contents/MacOS/Jarvis" "$SRC/main.swift"

echo "Drawing the icon…"
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET" && mkdir -p "$ICONSET"
swift "$SRC/make_icon.swift" "$BUILD/icon-1024.png" 2>/dev/null
for s in 16 32 128 256 512; do
  sips -z $s $s "$BUILD/icon-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z $d $d "$BUILD/icon-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

PLIST="$APP/Contents/Info.plist"
cat > "$PLIST" <<'PL'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Jarvis</string>
  <key>CFBundleDisplayName</key><string>Jarvis</string>
  <key>CFBundleIdentifier</key><string>local.jarvis.assistant</string>
  <key>CFBundleExecutable</key><string>Jarvis</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Jarvis listens when you press the microphone or turn on hands-free. Speech is turned into text on this Mac.</string>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PL
plutil -insert JarvisRepo -string "$REPO" "$PLIST"
plutil -insert JarvisPath -string "$PATH" "$PLIST"

echo "Signing (ad-hoc, for this Mac)…"
codesign --force --sign - "$APP" >/dev/null 2>&1

if [ "${1:-}" != "--no-install" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Jarvis.app"
  cp -R "$APP" "$HOME/Applications/Jarvis.app"
  echo "Installed: $HOME/Applications/Jarvis.app"
  echo "Open it from Launchpad/Spotlight (\"Jarvis\") or drag it to the Dock."
else
  echo "Built: $APP"
fi
