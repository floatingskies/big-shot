#!/usr/bin/env bash
# Big Shot UI — Install Script
# Installs the standalone big-shot-ui application for Cinnamon.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh          # installs to ~/.local
#   sudo ./install.sh     # installs system-wide to /usr/local
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# ── Detect install prefix ─────────────────────────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    PREFIX="/usr/local"
else
    PREFIX="$HOME/.local"
fi

LIBDIR="$PREFIX/lib/big-shot-ui"
BINDIR="$PREFIX/bin"

echo "==> Installing Big Shot UI to $PREFIX"

# ── Dependency check ──────────────────────────────────────────────────────────
check_dep() {
    if ! python3 -c "import $1" &>/dev/null; then
        echo "MISSING: Python package '$1'"
        MISSING=1
    fi
}

echo "--> Checking dependencies…"
MISSING=0

# Check Python 3.10+
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"; then
    echo "    Python $PY_VER ✓"
else
    echo "    Python $PY_VER — need 3.10+  ✗"
    MISSING=1
fi

# GTK4 Python bindings
for pkg in gi cairo; do
    if python3 -c "import $pkg" &>/dev/null; then
        echo "    $pkg ✓"
    else
        echo "    $pkg ✗"
        MISSING=1
    fi
done

# GTK4 availability
if python3 -c "
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
" &>/dev/null; then
    echo "    GTK4 ✓"
else
    echo "    GTK4 ✗  (install: sudo apt install python3-gi gir1.2-gtk-4.0)"
    MISSING=1
fi

# GdkPixbuf
if python3 -c "
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
" &>/dev/null; then
    echo "    GdkPixbuf ✓"
else
    echo "    GdkPixbuf ✗  (install: sudo apt install gir1.2-gdkpixbuf-2.0)"
    MISSING=1
fi

# Screen capture tool
if command -v scrot &>/dev/null; then
    echo "    scrot ✓"
elif command -v gnome-screenshot &>/dev/null; then
    echo "    gnome-screenshot ✓  (scrot preferred: sudo apt install scrot)"
else
    echo "    scrot / gnome-screenshot ✗  (sudo apt install scrot)"
    MISSING=1
fi

if [[ $MISSING -eq 1 ]]; then
    echo ""
    echo "Please install missing dependencies, then re-run install.sh"
    echo ""
    echo "Quick fix (Ubuntu / Linux Mint):"
    echo "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0"
    echo "  sudo apt install gir1.2-gdkpixbuf-2.0 scrot"
    exit 1
fi

# ── Copy files ────────────────────────────────────────────────────────────────
echo "--> Copying files…"

mkdir -p "$LIBDIR" "$BINDIR"

# Copy library tree
cp -r big_shot_app.py drawing ui "$LIBDIR/"

# Install wrapper script
cat > "$BINDIR/big-shot-ui" <<EOF
#!/usr/bin/env bash
# Big Shot UI launcher
exec python3 "$LIBDIR/big_shot_app.py" "\$@"
EOF
chmod +x "$BINDIR/big-shot-ui"

echo ""
echo "==> Installed: $BINDIR/big-shot-ui"
echo ""
echo "Test it with:"
echo "   big-shot-ui --mode=screenshot"
echo "   big-shot-ui --mode=area"
echo "   big-shot-ui --mode=screencast"
echo ""
echo "If \$PREFIX/bin is not in your PATH, add this to ~/.bashrc:"
echo "   export PATH=\"$BINDIR:\$PATH\""
