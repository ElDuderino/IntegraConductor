#!/usr/bin/env bash
# Sets up the WSL (Linux) side: virtual environment, `integra7` / `integra7-mcp`
# commands on PATH, and the patch catalog. Sends nothing to any MIDI device.
#
#   scripts/setup-wsl.sh                 # WSL side only
#   scripts/setup-wsl.sh --with-windows  # also run scripts/setup-windows.ps1 via interop
#
# Environment:
#   INTEGRA7_VENV     venv location (default: ~/.local/share/integra7-conductor/venv,
#                     kept on the Linux filesystem because venvs on /mnt/c are slow)
#   INTEGRA7_BIN_DIR  where to link the commands (default: ~/.local/bin)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${INTEGRA7_VENV:-${XDG_DATA_HOME:-$HOME/.local/share}/integra7-conductor/venv}"
BIN_DIR="${INTEGRA7_BIN_DIR:-$HOME/.local/bin}"
WITH_WINDOWS=0
for arg in "$@"; do
  case "$arg" in
    --with-windows) WITH_WINDOWS=1 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

echo "==> Creating virtual environment: $VENV"
if command -v uv >/dev/null 2>&1; then
  uv venv --quiet --allow-existing "$VENV"
  VIRTUAL_ENV="$VENV" uv pip install --quiet -e "$REPO[dev,mcp]"
else
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -e "$REPO[dev,mcp]"
fi

echo "==> Linking commands into $BIN_DIR"
mkdir -p "$BIN_DIR"
for cmd in integra7 integra7-mcp; do
  ln -sfn "$VENV/bin/$cmd" "$BIN_DIR/$cmd"
done
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "    NOTE: $BIN_DIR is not on PATH; add it to your shell profile." ;;
esac

echo "==> Building the patch catalog from bundled sources"
"$VENV/bin/integra7" patches import >/dev/null
"$VENV/bin/integra7" patches search "Full Grand 1" --limit 1

if [ "$WITH_WINDOWS" = 1 ]; then
  echo "==> Setting up the Windows MIDI environment"
  powershell.exe -NoProfile -ExecutionPolicy Bypass \
    -File "$(wslpath -w "$REPO/scripts/setup-windows.ps1")"
  "$VENV/bin/integra7" doctor --write-config || true
fi

echo
echo "Done. Next:"
echo "  integra7 doctor                      # check interop, adapter and ports"
echo "  $VENV/bin/python -m pytest \"$REPO\"   # run the offline test suite"
