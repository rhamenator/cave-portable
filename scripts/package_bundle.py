"""Turn PyInstaller output into a downloadable release asset."""

import os
import pathlib
import shutil
import subprocess
import sys

name = sys.argv[1]
target = pathlib.Path("release-assets")
target.mkdir(exist_ok=True)
if sys.platform == "darwin":
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "dist/CAVE-Portable.app", str(target / f"{name}.zip")], check=True)
elif os.name == "nt":
    shutil.copy2("scripts/install_windows.ps1", "dist/install-windows.ps1")
    shutil.make_archive(str(target / name), "zip", "dist")
else:
    shutil.copy2("src/cave_portable/assets/icon-256.png", "dist/cave-portable.png")
    shutil.copy2("scripts/install_linux.sh", "dist/install-linux.sh")
    subprocess.run(["tar", "-C", "dist", "-czf", str(target / f"{name}.tar.gz"), "CAVE-Portable", "cave-portable.png", "install-linux.sh"], check=True)
