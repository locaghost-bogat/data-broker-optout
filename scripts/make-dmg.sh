#!/bin/bash
# Wrap dist/Data Broker Opt-Out.app into a distributable .dmg.
#
# Get the .app there first, one of:
#   bash scripts/make-app.sh              # thin bundle (recipient needs Python 3 + Tk)
#   python3 setup.py py2app               # standalone bundle (embeds Python + Tk)
#
# Then:
#   bash scripts/make-dmg.sh
#
# Output: dist/Data Broker Opt-Out <version>.dmg
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Data Broker Opt-Out"
DIST="$HERE/dist"
APP="$DIST/$APP_NAME.app"

VERSION="$(cd "$HERE" && PYTHONPATH="$HERE" python3 -c 'import dbopt; print(dbopt.__version__)' 2>/dev/null || echo 1.0.0)"
DMG="$DIST/$APP_NAME $VERSION.dmg"

if [ ! -d "$APP" ]; then
  echo "error: $APP not found."
  echo "Build it first:  bash scripts/make-app.sh   (or)   python3 setup.py py2app"
  exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"    # drag-to-install target

rm -f "$DMG"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING" \
  -fs HFS+ \
  -format UDZO \
  -imagekey zlib-level=9 \
  -ov \
  "$DMG"

echo
echo "Built: $DMG"
if codesign -dv "$APP" >/dev/null 2>&1; then
  echo "App is code-signed."
else
  echo "App is UNSIGNED. On first launch a recipient must right-click the app -> Open,"
  echo "or you sign + notarize it (see README 'Signing & notarization')."
fi
