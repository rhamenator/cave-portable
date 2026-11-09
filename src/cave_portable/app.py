"""Responsive Tk desktop interface. All network and image decoding runs off the UI thread."""

from __future__ import annotations

import io
import queue
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from tkinter import ttk

from PIL import Image, ImageTk

from . import __version__
from . import data

BG = "#101923"
FG = "#eef4f7"
MUTED = "#a8bbc7"
ACCENT = "#57c7e8"
Image.MAX_IMAGE_PIXELS = 20_000_000


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"CAVE Portable {__version__}")
        self.root.geometry("1040x760")
        self.root.minsize(720, 540)
        self.root.configure(bg=BG)
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="weather")
        self.results: queue.Queue = queue.Queue()
        self.pending: set[str] = set()
        self.images: dict[str, ImageTk.PhotoImage] = {}
        self.image_urls: dict[str, str] = {}
        self.closed = False

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("Sans", 10))
        style.configure("TButton", padding=7)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8))
        style.configure("Treeview", rowheight=26, background="#172632", foreground=FG, fieldbackground="#172632")
        style.configure("Treeview.Heading", font=("Sans", 10, "bold"))
        style.map("Treeview", background=[("selected", "#23566b")], foreground=[("selected", FG)])

        top = ttk.Frame(root, padding=(14, 10))
        top.pack(fill="x")
        ttk.Label(top, text="CAVE PORTABLE", font=("Sans", 17, "bold"), foreground=ACCENT).pack(side="left")
        ttk.Label(top, text="  Weather visualization • NOAA / NWS / SPC", foreground=MUTED).pack(side="left")
        ttk.Button(top, text="Refresh current view", command=self.refresh).pack(side="right")

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.observations_tab = ttk.Frame(self.tabs, padding=10)
        self.radar_tab = ttk.Frame(self.tabs, padding=10)
        self.satellite_tab = ttk.Frame(self.tabs, padding=10)
        self.severe_tab = ttk.Frame(self.tabs, padding=10)
        for frame, title in ((self.observations_tab, "Observations"), (self.radar_tab, "Radar"), (self.satellite_tab, "Satellite"), (self.severe_tab, "Severe outlook & CAPE")):
            self.tabs.add(frame, text=title)
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self.refresh())

        self._observations_ui()
        self._image_ui(self.radar_tab, "radar", "NOAA/NWS national radar composite · latest available image")
        self._image_ui(self.satellite_tab, "satellite", "NOAA/NESDIS GOES GeoColor · latest available image")
        self._image_ui(self.severe_tab, "severe", "SPC convective outlooks and Southern Plains MLCAPE analysis")
        self._satellite_controls()
        self._severe_controls()

        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status, foreground=MUTED, padding=(14, 5)).pack(fill="x")
        self.root.after(100, self._drain)
        self.root.after(300, self.refresh)
        self.root.after(300_000, self._periodic)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _observations_ui(self):
        bar = ttk.Frame(self.observations_tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="ICAO station:").pack(side="left")
        self.station = tk.StringVar(value="KDTW")
        entry = ttk.Entry(bar, textvariable=self.station, width=9)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda _e: self.load_station())
        ttk.Button(bar, text="Load station", command=self.load_station).pack(side="left")
        ttk.Label(bar, text="US state alerts:").pack(side="left", padx=(22, 4))
        self.state = tk.StringVar(value="MI")
        ttk.Entry(bar, textvariable=self.state, width=5).pack(side="left")
        ttk.Button(bar, text="Load alerts", command=self.load_alerts).pack(side="left", padx=5)

        columns = ("station", "name", "time", "temp", "wind", "visibility", "category")
        self.table = ttk.Treeview(self.observations_tab, columns=columns, show="headings", height=14)
        for key, title, width in (("station", "ICAO", 65), ("name", "Location", 220), ("time", "Observed", 140), ("temp", "°C", 55), ("wind", "Wind", 100), ("visibility", "Vis. mi", 70), ("category", "Flight", 70)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=45, stretch=key == "name")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self._select_station)
        self.details = tk.Text(self.observations_tab, height=9, wrap="word", bg="#172632", fg=FG, insertbackground=FG, relief="flat", padx=10, pady=8)
        self.details.pack(fill="x", pady=(8, 0))
        self.details.insert("1.0", "Select an observation or load a station. METAR and TAF from NOAA Aviation Weather Center. Alerts from NWS.")
        self.details.configure(state="disabled")
        self.rows: dict[str, data.Observation] = {}

    def _image_ui(self, frame, key: str, caption: str):
        ttk.Label(frame, text=caption, foreground=MUTED).pack(anchor="w", pady=(0, 6))
        label = ttk.Label(frame, text="Open this tab to load imagery", anchor="center")
        label.pack(fill="both", expand=True)
        setattr(self, key + "_image", label)
        setattr(self, key + "_controls", ttk.Frame(frame))
        getattr(self, key + "_controls").pack(fill="x", pady=6)
        ttk.Label(frame, text="Images show source-provided valid times and legends. Refresh to request the latest product.", foreground=MUTED).pack(anchor="w")

    def _satellite_controls(self):
        self.satellite_choice = tk.StringVar(value="GOES East")
        for title in data.SATELLITE:
            ttk.Radiobutton(self.satellite_controls, text=title, value=title, variable=self.satellite_choice, command=self.refresh).pack(side="left", padx=6)

    def _severe_controls(self):
        self.severe_choice = tk.StringVar(value="Day 1")
        for title in (*data.OUTLOOK, "Southern Plains MLCAPE"):
            ttk.Radiobutton(self.severe_controls, text=title, value=title, variable=self.severe_choice, command=self.refresh).pack(side="left", padx=6)
        ttk.Label(self.severe_controls, text="CAPE is instability, not a standalone severe forecast.", foreground=MUTED).pack(side="right")

    def _submit(self, key, operation, callback):
        if key in self.pending or self.closed:
            return
        self.pending.add(key)
        self.status.set(f"Loading {key}…")
        future = self.pool.submit(operation)
        future.add_done_callback(lambda f: self.results.put((key, f, callback)))

    def _drain(self):
        if self.closed:
            return
        while True:
            try:
                key, future, callback = self.results.get_nowait()
            except queue.Empty:
                break
            self.pending.discard(key)
            try:
                callback(future.result())
                self.status.set(f"Updated {key} · {datetime.now(timezone.utc):%H:%M UTC}")
            except Exception as exc:
                self.status.set(f"{key}: {exc}")
        self.root.after(100, self._drain)

    def refresh(self):
        tab = self.tabs.index(self.tabs.select())
        if tab == 0:
            self._submit("observations", data.metars, self._show_observations)
        elif tab == 1:
            self._load_image("radar", data.RADAR_URL)
        elif tab == 2:
            self._load_image("satellite", data.SATELLITE[self.satellite_choice.get()])
        else:
            choice = self.severe_choice.get()
            self._load_image("severe", data.MLCAPE_URL if choice == "Southern Plains MLCAPE" else data.OUTLOOK[choice])

    def _periodic(self):
        if not self.closed:
            self.refresh()
            self.root.after(300_000, self._periodic)

    def _show_observations(self, rows):
        self.table.delete(*self.table.get_children())
        self.rows = {row.station: row for row in rows}
        for row in rows:
            self.table.insert("", "end", iid=row.station, values=(row.station, row.name, row.observed, f"{row.temp_c:.1f}" if row.temp_c is not None else "—", row.wind, row.visibility, row.flight_category))
        if not rows:
            self._set_details("No observations returned. Try loading a station directly.")

    def _set_details(self, content):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", content)
        self.details.configure(state="disabled")

    def _select_station(self, _event):
        selected = self.table.selection()
        if selected:
            row = self.rows[selected[0]]
            self.station.set(row.station)
            self._set_details(f"{row.name} · {row.observed}\n\n{row.raw}")

    def load_station(self):
        try:
            station = data.validate_station(self.station.get())
        except data.DataError as exc:
            self.status.set(str(exc))
            return
        self._submit("station", lambda: (data.metars((station,)), data.taf(station)), self._show_station)

    def _show_station(self, result):
        rows, forecast = result
        if not rows:
            self._set_details("No observation for that station.\n\n" + forecast)
        else:
            self._set_details(f"{rows[0].name} · {rows[0].observed}\n\n{rows[0].raw}\n\nFORECAST\n{forecast}")

    def load_alerts(self):
        self._submit("alerts", lambda: data.alerts(self.state.get()), self._show_alerts)

    def _show_alerts(self, alerts):
        if not alerts:
            self._set_details("No active NWS alerts returned for this state.")
        else:
            self._set_details("ACTIVE NWS ALERTS\n\n" + "\n\n".join(f"{event}: {headline}\n{description}" for event, headline, description in alerts[:5]))

    def _load_image(self, key, url):
        self.image_urls[key] = url
        def decode():
            raw = data.image(url)
            with Image.open(io.BytesIO(raw)) as opened:
                opened.seek(0)
                result = opened.convert("RGB")
                result.thumbnail((960, 500), Image.Resampling.LANCZOS)
                return result
        self._submit(key, decode, lambda result: self._show_image(key, url, result))

    def _show_image(self, key, url, pil_image):
        if self.image_urls.get(key) != url:
            self.root.after(0, self.refresh)
            return
        photo = ImageTk.PhotoImage(pil_image, master=self.root)
        self.images[key] = photo
        getattr(self, key + "_image").configure(image=photo, text="")

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    if sys.platform.startswith("linux") and not ("DISPLAY" in __import__("os").environ or "WAYLAND_DISPLAY" in __import__("os").environ):
        raise SystemExit("CAVE Portable needs a graphical desktop session")
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
