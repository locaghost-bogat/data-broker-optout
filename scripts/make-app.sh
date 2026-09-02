#!/bin/bash
# Build a minimal double-clickable "Data Broker Opt-Out.app" bundle.
#
# This does NOT embed Python (keeps the bundle tiny and works on macOS 10.10+).
# It launches whatever `python3` is first on PATH, so a python.org or Homebrew
# Python 3 with Tkinter must be installed.
#
# Output: dist/Data Broker Opt-Out.app
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$HERE/dist/Data Broker Opt-Out.app"
BIN="$APP/Contents/MacOS"
RES="$APP/Contents/Resources"

rm -rf "$APP"
mkdir -p "$BIN" "$RES"
cp -R "$HERE/dbopt" "$RES/dbopt"
cp -R "$HERE/data" "$RES/data"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>Data Broker Opt-Out</string>
  <key>CFBundleDisplayName</key>     <string>Data Broker Opt-Out</string>
  <key>CFBundleIdentifier</key>      <string>com.local.databrokeroptout</string>
  <key>CFBundleVersion</key>         <string>1.0.0</string>
  <key>CFBundleShortVersionString</key> <string>1.0.0</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>launcher</string>
  <key>LSMinimumSystemVersion</key>  <string>10.10</string>
  <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST

cat > "$BIN/launcher" <<'SH'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"
export PYTHONPATH="$DIR"
exec "$PY" -m dbopt
SH
chmod +x "$BIN/launcher"

echo "Built: $APP"
echo "First launch: right-click -> Open (unsigned app)."
