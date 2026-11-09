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
    shutil.make_archive(str(target / name), "zip", "dist")
else:
    subprocess.run(["tar", "-C", "dist", "-czf", str(target / f"{name}.tar.gz"), "CAVE-Portable"], check=True)
