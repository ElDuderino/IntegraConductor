# Setup: Windows + WSL

Two Python environments are used and must stay separate.

| Environment | Runs | Location | Packages |
|---|---|---|---|
| WSL (Linux) | `integra7`, `integra7-mcp`, catalog, tests | `~/.local/share/integra7-conductor/venv` | this package, `mcp`, dev tools |
| Windows | `windows_adapter.py` only | `%LOCALAPPDATA%\integra7-conductor\venv` | `mido`, `python-rtmidi` |

Windows wheels cannot be imported by WSL Python, and Linux `mido` cannot see the
Roland driver's ports. The WSL side never imports `mido`.

## Windows prerequisites

1. Install the Roland INTEGRA-7 USB driver for your Windows version
   (<https://support.roland.com/hc/en-us/articles/360046252771>).
2. On the unit: **MENU → SYSTEM → USB Driver = VENDER**, then power-cycle and
   reconnect. With `GENERIC` the Roland driver's ports do not appear.
3. Install a Windows Python **3.10, 3.11 or 3.12**. `python-rtmidi` 1.5.8
   publishes Windows wheels only up to 3.12; with 3.13 or newer the install
   fails. Several Pythons can be installed side by side:
   `winget install --id Python.Python.3.12 -e`.
4. Run `scripts\setup-windows.ps1`. It prefers `py -3.12`, `-3.11`, `-3.10`,
   refuses to compile from source, and prints the ports Windows sees. Use
   `-Python C:\path\python.exe` to choose an interpreter and `-VenvPath` to
   move the environment.

## WSL prerequisites

1. WSL2 with Windows interop enabled (the default). Check:
   `cat /proc/sys/fs/binfmt_misc/WSLInterop` should start with `enabled`. If it
   was disabled, set `[interop] enabled=true` in `/etc/wsl.conf`, run
   `wsl.exe --shutdown` from Windows, and reopen the distro.
2. Python 3.11+ and, ideally, `uv`.
3. Run `scripts/setup-wsl.sh` (add `--with-windows` to run the PowerShell
   script too).
4. `integra7 doctor --write-config` discovers the Windows venv and stores its
   path as `windows_python`. Without it the path is rediscovered on every call
   (one extra `cmd.exe` launch).

## How the Windows adapter is launched

```text
[<windows python>, "-X", "utf8", "<wslpath -w .../windows_adapter.py>"]
```

- The command is an argument array passed to `subprocess.run`; there is no
  shell and no `cmd.exe /C` string. The request (ports, bytes, timings) travels
  as UTF-8 JSON on stdin, so quotes, apostrophes and spaces cannot be
  misparsed. The adapter answers with one ASCII-only JSON line.
- `windows_python` may be a Windows path (`C:\...`) or a WSL path
  (`/mnt/c/...`); Windows paths are converted with `wslpath -u`. The adapter
  script path is converted with `wslpath -w`.
- The child's working directory is the interpreter's folder, a Windows-visible
  path, which avoids UNC working-directory problems.
- One adapter process runs per atomic operation and holds the MIDI ports open
  for the whole message sequence.

The equivalent by hand from Bash:

```bash
PY="$(wslpath -u 'C:\Users\you\AppData\Local\integra7-conductor\venv\Scripts\python.exe')"
ADAPTER="$(wslpath -w src/integra7_conductor/midi/windows_adapter.py)"
"$PY" -X utf8 "$ADAPTER" --ports
echo '{"op":"ports"}' | "$PY" -X utf8 "$ADAPTER"
```

From Windows PowerShell:

```powershell
& "$env:LOCALAPPDATA\integra7-conductor\venv\Scripts\python.exe" src\integra7_conductor\midi\windows_adapter.py --ports
```

## Checkout location

- **`/mnt/c/...` (tested):** the adapter script has an ordinary `C:\` path.
- **WSL-native filesystem (not tested):** `wslpath -w` yields a
  `\\wsl.localhost\<distro>\...` UNC path, which Windows Python can execute. If
  it cannot, the adapter call fails with `ADAPTER_FAILED` and the path in
  `details`; move the checkout under `/mnt/c`, or package the adapter as an
  `.exe` on the Windows side and set `windows_adapter` to it.

## Troubleshooting

| Symptom (`error.code`) | Likely cause |
|---|---|
| `WINDOWS_INTEROP_UNAVAILABLE` | Interop disabled in `/etc/wsl.conf`, or not running in WSL |
| `ADAPTER_NOT_FOUND` | `setup-windows.ps1` not run, or `windows_python` points nowhere |
| `ADAPTER_DEPENDENCY_MISSING` | The Windows venv lacks `mido`/`python-rtmidi` (often Python 3.13+) |
| `PORT_NOT_FOUND` | Unit off or unplugged, driver missing, USB Driver not `VENDER`, or wrong name |
| `PORT_AMBIGUOUS` | The configured name matches several ports; use the exact name from `integra7 ports` |
| `PORT_OPEN_FAILED` | Another program (DAW, editor) holds the port |
| `DEVICE_TIMEOUT` on reads | Rx Exclusive off, wrong `device_id`, wrong `input_port`, or `sysex_port` should be `control` |
| `MIDI_NOT_VERIFIED` | The unit did not change: wrong part channel, Rx Program Change / Bank Select off |
| `DEVICE_BUSY` | Another `integra7` process held the hardware lock |
