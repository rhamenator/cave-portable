"""Small user preferences and explicit per-user login startup registration."""

from __future__ import annotations

import json
import os
import pathlib
import plistlib
import subprocess
import sys
import tempfile

from .data import DataError, validate_station
from .location import validate_postal
from . import units


def settings_path() -> pathlib.Path:
    if sys.platform == "win32":
        root = pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = pathlib.Path.home() / "Library" / "Application Support"
    else:
        root = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config"))
    return root / "cave-portable" / "settings.json"


def load() -> dict:
    path = settings_path()
    try:
        if path.stat().st_size > 4096:
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {}
        country = str(obj.get("country", "US"))
        postal = str(obj.get("postal_code", ""))
        if postal:
            country, postal = validate_postal(country, postal)
        return {"station": validate_station(str(obj.get("station", "KDTW"))),
                "country": country, "postal_code": postal,
                "street": str(obj.get("street", ""))[:120],
                "units": units.validate(str(obj.get("units", units.DEFAULT))),
                "monitor_enabled": obj.get("monitor_enabled") is True and bool(postal)}
    except (OSError, ValueError, DataError):
        return {}


def save(settings: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    country = str(settings.get("country", "US"))
    postal = str(settings.get("postal_code", ""))
    if postal:
        country, postal = validate_postal(country, postal)
    payload = json.dumps({
        "station": validate_station(str(settings.get("station", "KDTW"))),
        "country": country,
        "postal_code": postal,
        "street": str(settings.get("street", "")).strip()[:120],
        "units": units.validate(str(settings.get("units", units.DEFAULT))),
        "monitor_enabled": settings.get("monitor_enabled") is True and bool(postal),
    }, indent=2) + "\n"
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".settings-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(payload)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "cave_portable"]


def _startup_path() -> pathlib.Path:
    if sys.platform == "darwin":
        return pathlib.Path.home() / "Library" / "LaunchAgents" / "org.caveportable.app.plist"
    root = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config"))
    return root / "autostart" / "cave-portable.desktop"


def is_autostart_enabled() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, "CAVE Portable")
                return True
        except OSError:
            return False
    return _startup_path().exists()


def set_autostart(enabled: bool) -> None:
    command = _launch_command()
    if sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if enabled:
                winreg.SetValueEx(key, "CAVE Portable", 0, winreg.REG_SZ, subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, "CAVE Portable")
                except FileNotFoundError:
                    pass
        return
    path = _startup_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        payload = {"Label": "org.caveportable.app", "ProgramArguments": command, "RunAtLoad": True}
        path.write_bytes(plistlib.dumps(payload))
    else:
        def quote(arg: str) -> str:
            return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
        path.write_text("[Desktop Entry]\nType=Application\nName=CAVE Portable\nExec=" + " ".join(quote(arg) for arg in command) + "\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
