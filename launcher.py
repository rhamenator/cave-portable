import os
import sys

# PyInstaller's GTK bundle may omit theme SVG loaders on a different Linux
# desktop. Adwaita keeps controls and labels readable in that case.
if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    os.environ.setdefault("GTK_THEME", "Adwaita")

from cave_portable import main

if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    main()
