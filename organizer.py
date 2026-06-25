"""
Auto Folder Organizer v1.0.0
Author: Ovie Zeus
License: MIT

A Windows daemon that monitors directories and automatically organizes
files into categorized subfolders as they are created or modified.
User-created folders are safely relocated into a master "Folders" directory.
"""

import sys
import os

# Redirect stdout/stderr to devnull when running without a console
# (e.g. PyInstaller --windowed / --noconsole mode).
if not sys.stdout:
    sys.stdout = open(os.devnull, "w")
if not sys.stderr:
    sys.stderr = open(os.devnull, "w")

import ctypes
import socket
import shutil
import time
import threading
import logging
import platform
import psutil

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Hide the console window on Windows (PyInstaller windowed mode).
if sys.platform == "win32":
    whnd = ctypes.windll.kernel32.GetConsoleWindow()
    if whnd:
        ctypes.windll.user32.ShowWindow(whnd, 0)


# ─── Constants ───────────────────────────────────────────────────────────────

APP_NAME = "AutoFolderOrganizer"
APP_AUTHOR = "Ovie Zeus"
APP_VERSION = "1.0.0"

REGISTRY_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_RUN_VALUE = APP_NAME
APP_REG_KEY = r"Software\AutoFolderOrganizer"
UNINSTALL_REG_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoFolderOrganizer"
)

DAEMON_PORT = 65433
DAEMON_MARKER = "REGISTER_DIR:"

PID_FILE = os.path.join(os.path.expanduser("~"), f"{APP_NAME}.lock")

# ─── Logging Setup ──────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# ─── Immutable Master Category Directories ──────────────────────────────────

MASTER_CATEGORIES = (
    "PDFs",
    "Excel",
    "Code",
    "Design",
    "Documents",
    "Images",
    "Videos",
    "Audio",
    "Archives",
    "Installers",
    "Folders",
    "Others",
)

# ─── File Category Mapping ──────────────────────────────────────────────────

FILE_CATEGORIES = {
    "PDFs": (".pdf",),
    "Excel": (".xlsx", ".xls", ".csv", ".xlsm", ".xlsb"),
    "Code": (
        ".py", ".js", ".ts", ".jsx", ".tsx",
        ".html", ".htm", ".css", ".scss", ".sass", ".less",
        ".cpp", ".c", ".h", ".hpp", ".cxx", ".hxx",
        ".java", ".rs", ".go", ".rb", ".php", ".swift",
        ".kt", ".kts", ".scala", ".clj",
        ".sh", ".bat", ".ps1", ".cmd",
        ".sql", ".json", ".xml", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf",
        ".md", ".rst", ".tex",
        ".vue", ".svelte", ".astro",
        ".makefile", ".dockerfile", ".cmake",
    ),
    "Design": (
        ".psd", ".ai", ".sketch", ".fig",
        ".xd", ".ae", ".aep",
        ".blend", ".ma", ".mb", ".fbx", ".obj", ".3ds",
        ".ase", ".afdesign", ".afphoto", ".afpub",
        ".eps", ".svg", ".indd", ".idml",
        ".dwg", ".dxf", ".stl",
    ),
    "Documents": (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".pptx", ".csv"),
    "Images": (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp"),
    "Videos": (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv"),
    "Audio": (".mp3", ".wav", ".flac", ".m4a", ".aac"),
    "Archives": (".zip", ".rar", ".7z", ".tar", ".gz"),
    "Installers": (".exe", ".msi", ".dmg", ".pkg", ".deb"),
}


# ─── Helper Functions ───────────────────────────────────────────────────────


def get_script_name():
    """Return the basename of the current executable or script."""
    if getattr(sys, "frozen", False):
        return os.path.basename(sys.executable)
    return os.path.basename(os.path.abspath(__file__))


def get_launch_dir():
    """
    Return the directory containing the executable (frozen) or the
    current working directory (script mode).
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.kernel32.GetModuleFileNameW(None, buf, 260)
            return os.path.dirname(buf.value)
        return os.path.dirname(sys.executable)
    return os.getcwd()


# ─── Windows Registry Helpers ───────────────────────────────────────────────


def reg_set_value(root, key_path, name, value_type, value):
    """Write a registry value under the given key."""
    import winreg

    try:
        key = winreg.CreateKeyEx(root, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, name, 0, value_type, value)
        winreg.CloseKey(key)
    except Exception:
        pass


def reg_get_value(root, key_path, name):
    """Read a registry value; returns None if missing."""
    import winreg

    try:
        key = winreg.OpenKey(root, key_path, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, name)
        winreg.CloseKey(key)
        return val
    except Exception:
        return None


def reg_delete_tree(root, key_path):
    """Recursively delete a registry key and all subkeys."""
    import winreg

    try:
        key = winreg.OpenKey(root, key_path, 0, winreg.KEY_ALL_ACCESS)
        i = 0
        while True:
            try:
                subkey = winreg.EnumKey(key, i)
                reg_delete_tree(key, os.path.join(key_path, subkey))
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
        winreg.DeleteKey(root, key_path)
    except Exception:
        pass


# ─── Splash / First-Run ─────────────────────────────────────────────────────


def show_splash_screen():
    """Show a first-run welcome message box (Windows only)."""
    if sys.platform != "win32":
        return

    import winreg

    first_run = reg_get_value(
        winreg.HKEY_CURRENT_USER, APP_REG_KEY, "FirstRunDone"
    )
    if first_run:
        return

    ctypes.windll.user32.MessageBoxTimeoutW(
        0,
        f"Created by {APP_AUTHOR}",
        APP_NAME,
        0x40,
        0,
        3000,
    )
    reg_set_value(
        winreg.HKEY_CURRENT_USER,
        APP_REG_KEY,
        "FirstRunDone",
        winreg.REG_DWORD,
        1,
    )


# ─── Uninstaller Registration ────────────────────────────────────────────────


def register_uninstaller():
    """Register the application in Windows Add/Remove Programs."""
    if sys.platform != "win32":
        return

    import winreg

    exe_path = sys.executable
    appdata_dir = os.environ.get("APPDATA", "")
    uninstaller_dir = os.path.join(appdata_dir, APP_NAME)
    os.makedirs(uninstaller_dir, exist_ok=True)

    uninstaller_path = os.path.join(uninstaller_dir, "uninstall.bat")
    bat_content = (
        '@echo off\r\n'
        'echo Uninstalling Auto Folder Organizer...\r\n'
        f'"{exe_path}" --uninstall\r\n'
        'pause\r\n'
    )
    with open(uninstaller_path, "w") as f:
        f.write(bat_content)

    reg_set_value(
        winreg.HKEY_CURRENT_USER,
        UNINSTALL_REG_KEY,
        "DisplayName",
        winreg.REG_SZ,
        f"Auto Folder Organizer by {APP_AUTHOR}",
    )
    reg_set_value(
        winreg.HKEY_CURRENT_USER,
        UNINSTALL_REG_KEY,
        "UninstallString",
        winreg.REG_SZ,
        f'"{exe_path}" --uninstall',
    )
    reg_set_value(
        winreg.HKEY_CURRENT_USER,
        UNINSTALL_REG_KEY,
        "DisplayIcon",
        winreg.REG_SZ,
        exe_path,
    )
    reg_set_value(
        winreg.HKEY_CURRENT_USER,
        UNINSTALL_REG_KEY,
        "DisplayVersion",
        winreg.REG_SZ,
        APP_VERSION,
    )
    reg_set_value(
        winreg.HKEY_CURRENT_USER,
        UNINSTALL_REG_KEY,
        "Publisher",
        winreg.REG_SZ,
        APP_AUTHOR,
    )
    reg_set_value(
        winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY, "NoModify", winreg.REG_DWORD, 1
    )
    reg_set_value(
        winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY, "NoRepair", winreg.REG_DWORD, 1
    )


# ─── Uninstaller Logic ─────────────────────────────────────────────────────


def run_uninstaller():
    """Perform full application uninstall (registry, files, processes)."""
    if sys.platform != "win32":
        return

    import winreg

    # Kill the running daemon process
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
            except OSError:
                pass  # process already dead
            else:
                handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 0)
                    time.sleep(0.25)
        except (OSError, ValueError):
            pass
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

    # Remove registry keys
    try:
        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            os.path.join(REGISTRY_RUN_KEY, REGISTRY_RUN_VALUE),
        )
    except OSError:
        pass

    reg_delete_tree(winreg.HKEY_CURRENT_USER, APP_REG_KEY)
    reg_delete_tree(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY)

    # Remove application data
    appdata_dir = os.path.join(os.environ.get("APPDATA", ""), APP_NAME)
    if os.path.exists(appdata_dir):
        try:
            shutil.rmtree(appdata_dir)
        except OSError:
            pass

    ctypes.windll.user32.MessageBoxW(
        0,
        "Auto Folder Organizer has been uninstalled.",
        APP_NAME,
        0x40,
    )
    sys.exit(0)


# ─── Registry Autostart ──────────────────────────────────────────────────────


def set_registry_autostart():
    """Add the executable to Windows startup via HKCU Run key."""
    if sys.platform != "win32":
        return

    import winreg

    exe_path = sys.executable
    try:
        reg_set_value(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_RUN_KEY,
            REGISTRY_RUN_VALUE,
            winreg.REG_SZ,
            f'"{exe_path}"',
        )
    except Exception:
        pass


# ─── Recursion Guardrail ─────────────────────────────────────────────────────


def is_protected_name(name):
    """
    Return True if *name* matches one of the immutable master category
    directory names — immediate return to prevent recursive loops.
    """
    return name in MASTER_CATEGORIES


def is_inside_protected_directory(path, script_dir):
    """
    Return True if *path* resides inside or directly matches any master
    category directory. This prevents watchdog events fired within sorted
    folders from triggering further moves.
    """
    if not path:
        return False

    abs_path = os.path.abspath(path)
    abs_script = os.path.abspath(script_dir)

    if abs_path == abs_script:
        return False

    parent = os.path.dirname(abs_path)
    while parent != abs_script and parent != os.path.dirname(parent):
        dir_name = os.path.basename(parent)
        if is_protected_name(dir_name):
            return True
        parent = os.path.dirname(parent)

    return False


# ─── File Path Utilities ────────────────────────────────────────────────────


def get_unique_path(dest_path):
    """
    If *dest_path* already exists, append _1, _2, etc. to create a
    unique file or directory name.
    """
    base, ext = os.path.splitext(dest_path)
    counter = 1
    while True:
        new_path = f"{base}_{counter}{ext}"
        if not os.path.exists(new_path):
            return new_path
        counter += 1


def get_category(extension):
    """
    Return the category folder name for a given file extension.
    Falls back to ``"Others"`` when no match is found.
    """
    for category, extensions in FILE_CATEGORIES.items():
        if extension.lower() in extensions:
            return category
    return "Others"


# ─── File Mover ─────────────────────────────────────────────────────────────


def move_file(filepath, script_dir, script_name):
    """
    Move *filepath* to its categorized subdirectory under *script_dir*.
    Silently returns if the path is inside a protected category directory
    or is the script itself.
    """
    if not os.path.isfile(filepath):
        return

    if is_inside_protected_directory(filepath, script_dir):
        return

    filename = os.path.basename(filepath)
    if filename == script_name:
        return

    _, ext = os.path.splitext(filename)
    category = get_category(ext)
    category_dir = os.path.join(script_dir, category)
    os.makedirs(category_dir, exist_ok=True)

    dest_path = os.path.join(category_dir, filename)
    dest_path = get_unique_path(dest_path)

    try:
        shutil.move(filepath, dest_path)
        logging.info(f"Organizing: {filename} -> {category}/")
    except (PermissionError, OSError) as e:
        logging.warning(f"Failed to move {filename}: {e}")


# ─── Directory Mover (User-Created Folders) ──────────────────────────────────


def move_user_folder(folder_path, script_dir, script_name):
    """
    Relocate a user-created folder into the master ``Folders`` directory.
    The 0.5-second settle window prevents moves while the user is actively
    renaming a folder on Windows.
    """
    time.sleep(0.5)

    if not os.path.isdir(folder_path):
        return

    if is_inside_protected_directory(folder_path, script_dir):
        return

    folder_name = os.path.basename(folder_path)
    if folder_name == script_name:
        return

    folders_dir = os.path.join(script_dir, "Folders")
    os.makedirs(folders_dir, exist_ok=True)

    dest_path = os.path.join(folders_dir, folder_name)
    dest_path = get_unique_path(dest_path)

    try:
        shutil.move(folder_path, dest_path)
        logging.info(f"Organized folder: {folder_name} -> Folders/")
    except (PermissionError, OSError) as e:
        logging.warning(f"Failed to move folder {folder_name}: {e}")


# ─── Watchdog Event Handler ─────────────────────────────────────────────────


class FileMoverHandler(FileSystemEventHandler):
    """
    Responds to file system events:
    - Files are moved into their extension-based category folder.
    - Directories that are not master categories are relocated into
      the master ``Folders`` directory.
    Events fired inside protected category directories are silently
    dropped to prevent recursion.
    """

    def __init__(self, script_dir, script_name):
        super().__init__()
        self.script_dir = script_dir
        self.script_name = script_name

    def on_created(self, event):
        if is_inside_protected_directory(event.src_path, self.script_dir):
            return

        if event.is_directory:
            dir_name = os.path.basename(event.src_path)
            if is_protected_name(dir_name):
                return
            move_user_folder(
                event.src_path, self.script_dir, self.script_name
            )
            return

        self._handle_file(event.src_path)

    def on_modified(self, event):
        if is_inside_protected_directory(event.src_path, self.script_dir):
            return

        if event.is_directory:
            dir_name = os.path.basename(event.src_path)
            if is_protected_name(dir_name):
                return
            move_user_folder(
                event.src_path, self.script_dir, self.script_name
            )
            return

        self._handle_file(event.src_path)

    def _handle_file(self, filepath):
        # Skip incomplete downloads / temp files
        if filepath.lower().endswith((".tmp", ".crdownload", ".part")):
            return
        time.sleep(0.5)  # wait for write-stream to settle
        move_file(filepath, self.script_dir, self.script_name)


# ─── Organize Existing Files ────────────────────────────────────────────────


def organize_existing(script_dir, script_name):
    """
    Move every file and user-created folder already present in
    *script_dir* into their appropriate category.
    """
    for item in os.listdir(script_dir):
        item_path = os.path.join(script_dir, item)

        if item == script_name:
            continue

        if is_protected_name(item):
            continue

        if os.path.isfile(item_path):
            move_file(item_path, script_dir, script_name)
        elif os.path.isdir(item_path):
            move_user_folder(item_path, script_dir, script_name)


# ─── Socket Daemon Server ────────────────────────────────────────────────────


def start_socket_server(observers, lock, ready_event):
    """
    Listen on ``127.0.0.1:DAEMON_PORT`` for registration requests from
    secondary instances. Each message contains a directory path prefixed
    with ``DAEMON_MARKER``.  The server validates the path, creates a new
    ``FileMoverHandler`` + ``Observer`` pair, and schedules it.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", DAEMON_PORT))
    server.listen(5)
    server.settimeout(1.0)

    ready_event.set()

    while True:
        try:
            conn, _ = server.accept()
            data = conn.recv(4096).decode("utf-8").strip()
            conn.close()

            if data.startswith(DAEMON_MARKER):
                new_dir = data[len(DAEMON_MARKER):]

                if (
                    os.path.isdir(new_dir)
                    and new_dir not in [o["dir"] for o in observers]
                ):
                    with lock:
                        new_script_name = get_script_name()
                        organize_existing(new_dir, new_script_name)

                        handler = FileMoverHandler(new_dir, new_script_name)
                        observer = Observer()
                        observer.schedule(handler, new_dir, recursive=False)
                        observer.start()

                        observers.append({
                            "dir": new_dir,
                            "observer": observer,
                        })
                        logging.info(f"Registered new directory: {new_dir}")

        except socket.timeout:
            continue
        except Exception as e:
            logging.error(f"Socket server error: {e}")


# ─── Single-Instance Lock ────────────────────────────────────────────────────


def acquire_single_instance():
    """
    Ensure only one instance of the application runs at a time.

    Uses a PID file with ``O_CREAT | O_EXCL`` for atomic acquisition.
    If a stale lock file is found (process no longer alive), it is
    silently cleaned up and a fresh lock is created — enabling
    infinite restart self-healing.

    Returns ``True`` if this is the only instance, ``False`` otherwise.
    On non-Windows platforms always returns ``True``.
    """
    if sys.platform != "win32":
        return True

    # ── Read and validate any existing PID lock ──────────────────────────
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())

            if psutil.pid_exists(pid):
                try:
                    proc = psutil.Process(pid)
                    if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                        return False
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass  # can't access → stale, fall through

            # Process is dead or unreachable — discard stale lock
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

        except (OSError, ValueError):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

    # ── Acquire fresh lock atomically ────────────────────────────────────
    try:
        global _lock_fd
        _lock_fd = os.open(
            PID_FILE,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        os.write(_lock_fd, str(os.getpid()).encode())
        return True
    except OSError:
        return False


# ─── Send Path to Existing Daemon ────────────────────────────────────────────


def send_to_daemon(directory):
    """
    Send *directory* to the already-running daemon so it registers a new
    watch.  Tries up to 3 times with a 0.5 s sleep between attempts.
    Returns ``True`` on success, ``False`` otherwise.
    """
    for _ in range(3):
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(1)
            client.connect(("127.0.0.1", DAEMON_PORT))
            client.send(
                f"{DAEMON_MARKER}{directory}".encode("utf-8"),
            )
            client.close()
            return True
        except Exception:
            time.sleep(0.5)
    return False


# ─── Entry Point ─────────────────────────────────────────────────────────────


def main():
    """Application entry point."""
    if "--uninstall" in sys.argv:
        run_uninstaller()
        return

    launch_dir = get_launch_dir()
    script_name = get_script_name()

    show_splash_screen()
    set_registry_autostart()
    register_uninstaller()

    if not acquire_single_instance():
        send_to_daemon(launch_dir)
        os._exit(0)

    logging.info(f"Starting master daemon. Monitoring: {launch_dir}")

    observers = []
    lock = threading.Lock()
    ready_event = threading.Event()

    server_thread = threading.Thread(
        target=start_socket_server,
        args=(observers, lock, ready_event),
        daemon=True,
    )
    server_thread.start()
    ready_event.wait(timeout=3)

    organize_existing(launch_dir, script_name)

    handler = FileMoverHandler(launch_dir, script_name)
    observer = Observer()
    observer.schedule(handler, launch_dir, recursive=False)
    observer.start()
    observers.append({"dir": launch_dir, "observer": observer})

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    for o in observers:
        o["observer"].stop()
        o["observer"].join()

    logging.info("File organizer stopped.")


# ─── CLI Entry ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
