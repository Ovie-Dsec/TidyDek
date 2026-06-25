# TidyDek — Auto File Organizer for Windows

Monitors directories and automatically sorts files into categorized
subfolders. Runs as a background daemon with a single-instance IPC lock.

## Download

[Download the latest TidyDek.exe](https://github.com/Ovie-Dsec/TidyDek/releases/latest)

## Quick Start

1. Download `TidyDek.exe` from the Releases page
2. Run it — it watches its own directory
3. Drop files into that folder — they sort automatically

## Features

- **10 file categories:** PDFs, Excel, Code, Design, Documents, Images, Videos, Audio, Archives, Installers
- **User-created folder relocation** into a master `Folders/` directory
- **Recursion guardrails** — never loops inside already-sorted folders
- **Self-healing PID lock** — survives crashes, restarts cleanly without manual cleanup
- **IPC daemon** — if you run a copy from another folder, it registers with the main daemon via loopback socket instead of spawning a duplicate
- **Windows startup** — registers itself to auto-launch at logon

## Privacy

TidyDek runs entirely offline. It does **not**:

- Collect or transmit telemetry, analytics, or usage data
- Phone home to any remote server
- Store or log file contents — only file paths and extension names are processed
- Communicate over the network — the IPC socket binds exclusively to `127.0.0.1` (localhost only)

TidyDek requires `broadFileSystemAccess` to move files on your behalf. All file operations occur locally.

## Build from Source

```batch
pip install -r requirements.txt
pyinstaller --onefile --windowed --icon=autosort.ico --name=TidyDek organizer.py
```

Output: `dist\TidyDek.exe`

## License

MIT — see [LICENSE](LICENSE).
