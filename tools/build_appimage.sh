#!/usr/bin/env bash
# Builds dist/pyBatchMKVPropEdit-<version>-x86_64.AppImage. Run on Linux from the project folder:
#   tools/build_appimage.sh
#
# Needs: the venv with the dev dependencies (.venv, or set PYTHON) and appimagetool
# (https://github.com/AppImage/appimagetool/releases) in PATH, or its path in APPIMAGETOOL.
# Build on the oldest distribution you want to support: the AppImage runs on that glibc and newer ones.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
ARCH="${ARCH:-$(uname -m)}"

if ! command -v "$APPIMAGETOOL" >/dev/null 2>&1; then
    echo "appimagetool not found. Download it from https://github.com/AppImage/appimagetool/releases," >&2
    echo "make it executable and put it in PATH, or set APPIMAGETOOL=/path/to/appimagetool." >&2
    exit 1
fi

VERSION="$("$PYTHON" -c 'import sys; sys.path.insert(0, "src"); import bmpe; print(bmpe.__version__)')"

"$PYTHON" -m PyInstaller build.spec --noconfirm

APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/pybatchmkvpropedit "$APPDIR/usr/lib/pybatchmkvpropedit"

cp packaging/linux/pybatchmkvpropedit.desktop "$APPDIR/"
cp packaging/linux/pybatchmkvpropedit.desktop "$APPDIR/usr/share/applications/"
cp src/bmpe/resources/icon.png "$APPDIR/pybatchmkvpropedit.png"
cp src/bmpe/resources/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/pybatchmkvpropedit.png"
ln -s pybatchmkvpropedit.png "$APPDIR/.DirIcon"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/pybatchmkvpropedit/pybatchmkvpropedit" "$@"
EOF
chmod +x "$APPDIR/AppRun"

OUT="dist/pyBatchMKVPropEdit-${VERSION}-${ARCH}.AppImage"
# extract-and-run: appimagetool also works without FUSE (containers, WSL)
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$OUT"
echo "Built $OUT"
