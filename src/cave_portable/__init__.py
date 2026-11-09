"""CAVE Portable: independent, lightweight weather viewer."""

__version__ = "0.2.0"


def main():
    import os
    import sys

    if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        from .gtk_app import main as gtk_main

        return gtk_main()
    from .app import main as tk_main

    return tk_main()
