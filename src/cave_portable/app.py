"""Responsive Tk desktop interface. All network and image decoding runs off the UI thread."""

from __future__ import annotations

import io
import os
import queue
import sys
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from . import __version__
from . import data
from . import model
from . import hrrr
from . import mrms
from . import radar
from . import level3
from . import spc
from . import preferences
from . import location

BG = "#101923"
FG = "#eef4f7"
MUTED = "#a8bbc7"
ACCENT = "#57c7e8"
Image.MAX_IMAGE_PIXELS = 20_000_000


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"CAVE Portable {__version__}")
        self._window_icon = tk.PhotoImage(file=str(files("cave_portable").joinpath("assets/icon-64.png")))
        self.root.iconphoto(True, self._window_icon)
        self.root.geometry("1000x640")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="weather")
        self.results: queue.Queue = queue.Queue()
        self.pending: set[str] = set()
        self.images: dict[str, ImageTk.PhotoImage] = {}
        self.image_sources: dict[str, tuple[str, Image.Image]] = {}
        self.image_urls: dict[str, str] = {}
        self.radar_sites = dict(radar.SITES)
        self.radar_zoom = 1
        self.radar_center: tuple[float, float] | None = None
        self.radar_field: level3.Field | None = None
        self.radar_frame = 0
        self.radar_drag: tuple[int, int] | None = None
        self.render_sizes: dict[str, tuple[int, int]] = {}
        self.radar_zoom_text = tk.StringVar(value="1×")
        self.guidance_point = ("KLAN", 42.7761, -84.5997, "US")
        self.guidance_last_fetch: dict[str, datetime] = {}
        self.guidance_text = tk.StringVar(value="Loading local SPC outlook for KLAN…")
        self.forecast_text = tk.StringVar(value="Loading local NWS forecast…")
        self.hourly_text = tk.StringVar(value="Loading local NWS hourly forecast…")
        self.winter_text = tk.StringVar(value="NWS snow, ice, and gust forecast loading…")
        self.local_current = tk.StringVar(value="Nearby observation loading…")
        self.station_trend_text = tk.StringVar(value="Selected airport trend loading…")
        self.local_alert_text = tk.StringVar(value="Local official warnings and watches loading…")
        self.hail_text = tk.StringVar(value="MRMS MESH hail estimate: select Check hail for an on-demand reading")
        self.resize_job: str | None = None
        self.fallback_chrome = False
        self.drag_origin: tuple[int, int, int, int] | None = None
        self.closed = False
        saved = preferences.load()
        self.country = tk.StringVar(value=saved.get("country", "US"))
        self.postal_code = tk.StringVar(value=saved.get("postal_code", ""))
        self.street = tk.StringVar(value=saved.get("street", ""))
        self.postal_location: location.PostalLocation | None = None
        self.monitor_enabled = tk.BooleanVar(value=saved.get("monitor_enabled", False) and bool(saved.get("postal_code")))
        self.open_mini_on_location = self.monitor_enabled.get()
        self.monitor_point: tuple[float, float] | None = None
        self.monitor_seen: set[str] = set()
        self.mini_window: tk.Toplevel | None = None
        self.mini_weather = tk.StringVar(value="Set a ZIP or postal code to load local weather")
        self.point_status = tk.StringVar(value="Set a ZIP or postal code for local weather and alerts")

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
        drag_targets = [top]
        self._header_icon = tk.PhotoImage(file=str(files("cave_portable").joinpath("assets/icon-32.png")))
        icon_label = ttk.Label(top, image=self._header_icon)
        icon_label.pack(side="left", padx=(0, 8))
        drag_targets.append(icon_label)
        title_label = ttk.Label(top, text="CAVE PORTABLE", font=("Sans", 17, "bold"), foreground=ACCENT)
        title_label.pack(side="left")
        drag_targets.append(title_label)
        source_label = ttk.Label(top, text="  NOAA / NWS / SPC", foreground=MUTED)
        source_label.pack(side="left")
        drag_targets.append(source_label)
        for target in drag_targets:
            target.bind("<ButtonPress-1>", self._begin_window_drag)
            target.bind("<B1-Motion>", self._drag_window)
        ttk.Button(top, text="Refresh current view", command=self.refresh).pack(side="right")
        self.alert_summary = tk.StringVar(value="NWS alerts: checking…")
        ttk.Button(top, textvariable=self.alert_summary, command=self._open_alerts).pack(side="right", padx=8)
        ttk.Button(top, text="Official warnings", command=self._open_official_warnings).pack(side="right")

        self.status = tk.StringVar(value="Ready · For urgent decisions, use official warnings and local instructions")
        status_bar = ttk.Frame(root)
        status_bar.pack(side="bottom", fill="x")
        ttk.Label(status_bar, textvariable=self.status, foreground=MUTED, padding=(14, 5)).pack(side="left", fill="x", expand=True)
        self.fallback_close = ttk.Button(status_bar, text="Close", width=6, command=self.close)

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.observations_tab = ttk.Frame(self.tabs, padding=10)
        self.radar_tab = ttk.Frame(self.tabs, padding=10)
        self.satellite_tab = ttk.Frame(self.tabs, padding=10)
        self.severe_tab = ttk.Frame(self.tabs, padding=10)
        self.model_tab = ttk.Frame(self.tabs, padding=10)
        self.hrrr_tab = ttk.Frame(self.tabs, padding=10)
        for frame, title in ((self.observations_tab, "Observations"), (self.radar_tab, "Radar"), (self.satellite_tab, "Satellite"), (self.severe_tab, "Severe outlook & CAPE"), (self.model_tab, "Forecast ingredients"), (self.hrrr_tab, "HRRR storm forecast")):
            self.tabs.add(frame, text=title)
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self.refresh())

        self._observations_ui()
        self._image_ui(self.radar_tab, "radar", "NOAA/NWS national radar composite · latest available image")
        self._image_ui(self.satellite_tab, "satellite", "NOAA/NESDIS GOES GeoColor · latest available image")
        self._image_ui(self.severe_tab, "severe", "SPC convective outlooks and Southern Plains MLCAPE analysis")
        self._image_ui(self.model_tab, "model", "Selected GFS run and field · NSF Unidata THREDDS / USGS map")
        self._image_ui(self.hrrr_tab, "hrrr", "NCEP HRRR simulated reflectivity · forecast, not observed radar")
        self._satellite_controls()
        self._severe_controls()
        self._model_controls()
        self._hrrr_controls()
        self._radar_controls()

        self.root.after(100, self._drain)
        self.root.after(300, self.refresh)
        self.root.after(500, self._refresh_alert_count)
        self.root.after(900, self._load_radar_catalog)
        if saved.get("postal_code"):
            self.root.after(700, self.set_location)
        self.tick = 0
        self.root.after(60_000, self._periodic)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Configure>", self._schedule_image_resize)
        for key in ("<plus>", "<equal>", "<KP_Add>"):
            self.root.bind(key, lambda event: self._radar_key(event, 1))
        for key in ("<minus>", "<KP_Subtract>"):
            self.root.bind(key, lambda event: self._radar_key(event, -1))
        self.root.after(80, self._present_window)

    def _present_window(self):
        self.root.lift()
        if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
            self.root.after(700, self._recover_iconified_window)

    def _recover_iconified_window(self):
        if self.closed or self.root.state() != "iconic":
            return
        self.fallback_chrome = True
        self.fallback_close.pack(side="right", padx=8)
        self.root.overrideredirect(True)
        self.root.deiconify()
        self.root.lift()

    def _begin_window_drag(self, event):
        if self.fallback_chrome:
            self.drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_window(self, event):
        if self.fallback_chrome and self.drag_origin:
            x0, y0, left, top = self.drag_origin
            self.root.geometry(f"+{left + event.x_root - x0}+{top + event.y_root - y0}")

    def _observations_ui(self):
        locality = ttk.Frame(self.observations_tab)
        locality.pack(fill="x", pady=(0, 8))
        ttk.Label(locality, text="Local weather and alerts · ZIP / postal code required:").pack(side="left")
        country_picker = ttk.Combobox(locality, textvariable=self.country, values=("US", "CA"), state="readonly", width=4)
        country_picker.pack(side="left", padx=6)
        country_picker.bind("<<ComboboxSelected>>", self._location_edited)
        postal = ttk.Entry(locality, textvariable=self.postal_code, width=12)
        postal.pack(side="left", padx=4)
        postal.bind("<Return>", lambda _e: self.set_location())
        postal.bind("<KeyRelease>", self._location_edited)
        ttk.Button(locality, text="Set ZIP / postal code", command=self.set_location).pack(side="left", padx=4)
        ttk.Label(locality, text="No IP location", foreground=MUTED).pack(side="left", padx=8)
        address = ttk.Frame(self.observations_tab)
        address.pack(fill="x", pady=(0, 8))
        ttk.Label(address, text="Street address (optional):").pack(side="left")
        street_entry = ttk.Entry(address, textvariable=self.street, width=38)
        street_entry.pack(side="left", padx=6)
        street_entry.bind("<KeyRelease>", self._location_edited)
        street_entry.bind("<Return>", lambda _e: self.set_location())
        ttk.Label(address, text="Approximate geocode", foreground=MUTED).pack(side="left", padx=6)
        bar = ttk.Frame(self.observations_tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="ICAO station:").pack(side="left")
        self.station = tk.StringVar(value=preferences.load().get("station", "KDTW"))
        entry = ttk.Entry(bar, textvariable=self.station, width=9)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda _e: self.load_station())
        ttk.Button(bar, text="Load station", command=self.load_station).pack(side="left")
        ttk.Button(bar, text="View nearest radar", command=self._open_selected_radar).pack(side="left", padx=4)
        ttk.Label(bar, text="US state alerts:").pack(side="left", padx=(22, 4))
        self.state = tk.StringVar(value="MI")
        ttk.Entry(bar, textvariable=self.state, width=5).pack(side="left")
        ttk.Button(bar, text="Load alerts", command=self.load_alerts).pack(side="left", padx=5)

        options = ttk.Frame(self.observations_tab)
        options.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(options, text="Monitor official warnings and watches at postal area", variable=self.monitor_enabled, command=self._toggle_monitor).pack(side="left")
        ttk.Button(options, text="Mini weather window", command=self._show_mini).pack(side="left", padx=8)
        self.autostart = tk.BooleanVar(value=preferences.is_autostart_enabled())
        ttk.Checkbutton(options, text="Start at login", variable=self.autostart, command=self._toggle_autostart).pack(side="left", padx=8)
        ttk.Label(self.observations_tab, textvariable=self.point_status, foreground=MUTED).pack(fill="x", pady=(0, 8))
        briefing = ttk.LabelFrame(self.observations_tab, text="Selected location briefing · official sources", padding=6)
        briefing.pack(fill="x", pady=(0, 6))
        ttk.Label(briefing, textvariable=self.local_current, foreground=FG).pack(anchor="w")
        ttk.Label(briefing, textvariable=self.station_trend_text, foreground=MUTED,
                  wraplength=880, justify="left").pack(anchor="w")
        ttk.Label(briefing, textvariable=self.local_alert_text, foreground=FG,
                  wraplength=880, justify="left").pack(anchor="w")
        ttk.Label(briefing, textvariable=self.guidance_text, foreground=FG,
                  wraplength=880, justify="left").pack(anchor="w")
        ttk.Label(briefing, textvariable=self.forecast_text, foreground=MUTED,
                  wraplength=880, justify="left").pack(anchor="w")
        ttk.Label(briefing, textvariable=self.hourly_text, foreground=MUTED,
                  wraplength=880, justify="left").pack(anchor="w")
        ttk.Label(briefing, textvariable=self.winter_text, foreground=MUTED,
                  wraplength=880, justify="left").pack(anchor="w")
        hail_row = ttk.Frame(briefing)
        hail_row.pack(fill="x")
        ttk.Button(hail_row, text="Check hail near point", command=self.check_hail).pack(side="left", padx=(0, 8))
        ttk.Label(hail_row, textvariable=self.hail_text, foreground=MUTED,
                  wraplength=680, justify="left").pack(side="left")

        columns = ("station", "name", "time", "temp", "wind", "visibility", "category")
        table_frame = ttk.Frame(self.observations_tab)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=4)
        for key, title, width in (("station", "ICAO", 65), ("name", "Location", 220), ("time", "Observed", 140), ("temp", "°C", 55), ("wind", "Wind", 100), ("visibility", "Vis. mi", 70), ("category", "Flight", 70)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=45, stretch=key == "name")
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self._select_station)
        self.table.bind("<Double-1>", lambda _event: self._open_selected_radar())
        self.details = tk.Text(self.observations_tab, height=3, wrap="word", bg="#172632", fg=FG, insertbackground=FG, relief="flat", padx=10, pady=8)
        self.details.pack(fill="x", pady=(8, 0))
        self.details.insert("1.0", "Select an observation or load a station. METAR and TAF from NOAA Aviation Weather Center. Alerts from NWS.")
        self.details.configure(state="disabled")
        self.rows: dict[str, data.Observation] = {}

    def _image_ui(self, frame, key: str, caption: str):
        ttk.Label(frame, text=caption, foreground=MUTED).pack(anchor="w", pady=(0, 6))
        if key in ("severe", "hrrr"):
            ttk.Label(frame, textvariable=self.guidance_text, foreground=FG,
                      wraplength=900, justify="left").pack(anchor="w", pady=(0, 5))
        if key == "severe":
            ttk.Label(frame, textvariable=self.hail_text, foreground=MUTED,
                      wraplength=900, justify="left").pack(anchor="w", pady=(0, 5))
        if key == "hrrr":
            ttk.Label(frame, textvariable=self.forecast_text, foreground=MUTED,
                      wraplength=900, justify="left").pack(anchor="w", pady=(0, 5))
        label = ttk.Label(frame, text="Open this tab to load imagery", anchor="center")
        label.pack(fill="both", expand=True)
        setattr(self, key + "_image", label)
        if key == "radar":
            label.bind("<ButtonPress-1>", self._radar_press)
            label.bind("<ButtonRelease-1>", self._radar_release)
        setattr(self, key + "_controls", ttk.Frame(frame))
        getattr(self, key + "_controls").pack(fill="x", pady=6)
        stamp = tk.StringVar(value="Source time pending. Images show source-provided valid times and legends when present.")
        setattr(self, key + "_stamp", stamp)
        ttk.Label(frame, textvariable=stamp, foreground=MUTED,
                  wraplength=900, justify="left").pack(anchor="w")

    def _satellite_controls(self):
        self.satellite_choice = tk.StringVar(value="GOES East")
        for title in data.SATELLITE:
            ttk.Radiobutton(self.satellite_controls, text=title, value=title, variable=self.satellite_choice, command=self.refresh).pack(side="left", padx=6)

    def _severe_controls(self):
        self.severe_choice = tk.StringVar(value="Day 1")
        for title in (*data.OUTLOOK, "Southern Plains MLCAPE"):
            ttk.Radiobutton(self.severe_controls, text=title, value=title, variable=self.severe_choice, command=self.refresh).pack(side="left", padx=6)
        ttk.Label(self.severe_controls, text="CAPE is instability, not a standalone severe forecast.", foreground=MUTED).pack(side="right")
        ttk.Button(self.severe_controls, text="Check MRMS hail", command=self.check_hail).pack(side="left", padx=8)

    def _model_controls(self):
        self.model_field = tk.StringVar(value="CAPE")
        field_picker = ttk.Combobox(self.model_controls, textvariable=self.model_field, values=tuple(model.FIELDS),
                                    state="readonly", width=18)
        field_picker.pack(side="left", padx=4)
        field_picker.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.model_run = tk.StringVar(value="Latest run")
        run_picker = ttk.Combobox(self.model_controls, textvariable=self.model_run, values=model.RUN_CHOICES,
                                  state="readonly", width=15)
        run_picker.pack(side="left", padx=4)
        run_picker.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Label(self.model_controls, text="Forecast hour:").pack(side="left", padx=6)
        self.model_hour = tk.StringVar(value="24")
        picker = ttk.Combobox(self.model_controls, textvariable=self.model_hour, values=[str(hour) for hour in model.HOURS], state="readonly", width=5)
        picker.pack(side="left", padx=6)
        picker.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.model_valid = tk.StringVar(value="Choose a GFS field, run, and forecast hour.")
        ttk.Label(self.model_controls, textvariable=self.model_valid, foreground=MUTED).pack(side="left", padx=12)
        self._add_zoom_controls(self.model_controls)

    def _hrrr_controls(self):
        ttk.Label(self.hrrr_controls, text="Hours after latest HRRR run:").pack(side="left", padx=6)
        self.hrrr_hour = tk.StringVar(value="6")
        picker = ttk.Combobox(self.hrrr_controls, textvariable=self.hrrr_hour,
                              values=[str(hour) for hour in hrrr.HOURS], state="readonly", width=5)
        picker.pack(side="left", padx=6)
        picker.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self._add_zoom_controls(self.hrrr_controls)

    def _add_zoom_controls(self, controls):
        ttk.Button(controls, text="−", width=3, command=lambda: self._step_radar_zoom(-1)).pack(side="left", padx=2)
        ttk.Label(controls, textvariable=self.radar_zoom_text).pack(side="left")
        ttk.Button(controls, text="+", width=3, command=lambda: self._step_radar_zoom(1)).pack(side="left", padx=2)

    def _radar_controls(self):
        self.radar_product = tk.StringVar(value="Digital reflectivity")
        product = ttk.Combobox(self.radar_controls, textvariable=self.radar_product,
                               values=("National reflectivity", *radar.PRODUCTS, *level3.PRODUCTS,
                                       "MRMS hail swath (30 min)"), state="readonly", width=29)
        product.pack(side="left", padx=6)
        product.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.radar_site = tk.StringVar(value="GRR · Grand Rapids")
        site = ttk.Combobox(self.radar_controls, textvariable=self.radar_site, values=tuple(self.radar_sites), state="readonly", width=25)
        self.radar_site_picker = site
        site.pack(side="left", padx=6)
        site.bind("<<ComboboxSelected>>", lambda _e: self._radar_site_changed())
        self.radar_timeline = tk.StringVar(value="Latest")
        timeline = ttk.Combobox(self.radar_controls, textvariable=self.radar_timeline,
                                values=("Latest", "1 scan back", "2 scans back", "3 scans back", "4 scans back", "5 scans back"),
                                state="readonly", width=13)
        timeline.pack(side="left", padx=4)
        timeline.bind("<<ComboboxSelected>>", lambda _e: self._radar_timeline_changed())
        self.radar_tilt = tk.StringVar(value="Tilt 0")
        tilt_picker = ttk.Combobox(self.radar_controls, textvariable=self.radar_tilt,
                                   values=tuple(f"Tilt {tilt}" for tilt in level3.TILTS),
                                   state="readonly", width=7)
        tilt_picker.pack(side="left", padx=4)
        tilt_picker.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.radar_boundaries = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.radar_controls, text="Official boundaries", variable=self.radar_boundaries,
                        command=self.refresh).pack(side="left", padx=3)
        ttk.Button(self.radar_controls, text="−", width=3,
                   command=lambda: self._step_radar_zoom(-1)).pack(side="left", padx=2)
        ttk.Label(self.radar_controls, textvariable=self.radar_zoom_text).pack(side="left")
        ttk.Button(self.radar_controls, text="+", width=3,
                   command=lambda: self._step_radar_zoom(1)).pack(side="left", padx=2)
        self.radar_valid = tk.StringVar(value="National composite · NOAA/NWS")

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
                if key in ("radar", "site-radar", "satellite", "severe", "model", "hrrr"):
                    image_key = "radar" if key == "site-radar" else key
                    if image_key == "radar":
                        self.radar_field = None
                    getattr(self, image_key + "_image").configure(image="", text=str(exc))
                    self.images.pop(image_key, None)
                    self.image_sources.pop(image_key, None)
                    getattr(self, image_key + "_stamp").set("No current image available")
                elif key in ("alerts", "alert-count"):
                    self.alert_summary.set("NWS alerts unavailable")
                    if key == "alerts":
                        self._set_details("NWS alerts unavailable. Check weather.gov directly.")
                elif key == "point-alerts":
                    self.point_status.set("Local warning feed unavailable; check your official weather service")
                elif key == "spc-guidance":
                    self.guidance_text.set(f"Local SPC outlook unavailable: {exc}. Check the official SPC outlook.")
                elif key == "point-forecast":
                    self.forecast_text.set(f"Local NWS forecast unavailable: {exc}")
                elif key == "hourly-forecast":
                    self.hourly_text.set(f"NWS hourly forecast unavailable: {exc}")
                elif key == "winter-forecast":
                    self.winter_text.set(f"NWS winter forecast grid unavailable: {exc}")
                elif key == "mrms-hail":
                    self.hail_text.set(f"MRMS MESH hail estimate unavailable: {exc}")
                elif key == "local-alert-summary":
                    self.local_alert_text.set(f"Official local alert feed unavailable: {exc}")
                elif key == "station-trend":
                    self.station_trend_text.set(f"Selected airport trend unavailable: {exc}")
                elif key in ("location", "local-weather"):
                    self.point_status.set(f"Local weather unavailable: {exc}")
                    if key == "local-weather":
                        self.mini_weather.set("Nearby observation unavailable\nCheck the official weather service")
        self.root.after(100, self._drain)

    def refresh(self):
        tab = self.tabs.index(self.tabs.select())
        if tab == 0:
            stations = tuple(dict.fromkeys((self._station_for_settings(), *data.STATIONS)))
            self._submit("observations", lambda: data.metars(stations), self._show_observations)
            self._refresh_station_trend()
            self._refresh_guidance()
        elif tab == 1:
            choice, site = self.radar_product.get(), self.radar_site.get()
            if choice == "National reflectivity":
                self.radar_field = None
                self.radar_valid.set("National composite · NOAA/NWS")
                self._load_image("radar", data.RADAR_URL)
            else:
                sites, zoom = self.radar_sites, self.radar_zoom
                center = self.radar_center
                frame = self.radar_frame
                if choice == "MRMS hail swath (30 min)":
                    self.radar_field = None
                    self._submit("site-radar", lambda: mrms.swath_map(site, sites, zoom, center),
                                 lambda result: self._show_swath(site, choice, zoom, center, result))
                elif choice in level3.PRODUCTS:
                    boundaries = self.radar_boundaries.get()
                    tilt = int(self.radar_tilt.get().split()[-1])
                    alert_point = self.guidance_point[1:3]
                    include_us_alerts = self.guidance_point[3] == "US"
                    self._submit("site-radar", lambda: level3.field_map(site, choice, sites, zoom, center, frame, boundaries, tilt,
                                                                        alert_point, include_us_alerts),
                                 lambda result: self._show_level3(site, choice, zoom, center, frame, boundaries, tilt, result))
                else:
                    self.radar_field = None
                    self._submit("site-radar", lambda: radar.site_map(site, choice, sites=sites, zoom=zoom, center=center),
                                 lambda result: self._show_site_radar(site, choice, zoom, center, result))
        elif tab == 2:
            self._load_image("satellite", data.SATELLITE[self.satellite_choice.get()])
        elif tab == 3:
            choice = self.severe_choice.get()
            self._load_image("severe", data.MLCAPE_URL if choice == "Southern Plains MLCAPE" else data.OUTLOOK[choice])
            self._refresh_guidance()
        elif tab == 4:
            hours = int(self.model_hour.get())
            field_name, run_choice = self.model_field.get(), self.model_run.get()
            place, lat, lon, _country = self.guidance_point
            zoom = self.radar_zoom
            token = f"GFS:{field_name}:{run_choice}:{hours}:{lat:.4f}:{lon:.4f}:{zoom}"
            self.model_request_token = token
            self._submit("model", lambda: model.field_map(field_name, hours, model.regional_bbox(lat, lon, zoom), run_choice),
                         lambda result: self._show_model(hours, token, place, result))

        elif tab == 5:
            hours = int(self.hrrr_hour.get())
            place, lat, lon, _country = self.guidance_point
            zoom = self.radar_zoom
            token = f"HRRR:{hours}:{lat:.4f}:{lon:.4f}:{zoom}"
            self.hrrr_request_token = token
            self._submit("hrrr", lambda: hrrr.reflectivity(hours, center=(lat, lon), zoom=zoom),
                         lambda result: self._show_hrrr(hours, token, place, result))
            self._refresh_guidance()

    def _set_guidance_point(self, place, lat, lon, country="US"):
        target = (place, lat, lon, country)
        if target != self.guidance_point:
            self.guidance_point = target
            self.guidance_last_fetch.clear()
            self.guidance_text.set(f"Loading local SPC outlook for {place}…" if country == "US"
                                   else "SPC severe outlooks cover the contiguous US")
            self.forecast_text.set("Loading local NWS forecast…" if country == "US"
                                   else "NWS point forecasts cover the contiguous US")
            self.hourly_text.set("Loading local NWS hourly forecast…" if country == "US"
                                 else "NWS hourly forecasts cover the contiguous US")
            self.winter_text.set("Loading NWS snow, ice, and gust forecast…" if country == "US"
                                 else "NWS winter forecast grid covers the contiguous US")
            self.hail_text.set("MRMS MESH hail estimate: select Check hail for this point")
            self.local_alert_text.set("Local official warnings and watches loading…")
            if self.tabs.index(self.tabs.select()) in (0, 3, 5):
                self._refresh_guidance()
            if self.tabs.index(self.tabs.select()) in (4, 5):
                self.refresh()

    def _refresh_guidance(self):
        place, lat, lon, country = self.guidance_point
        self._refresh_local_alert_summary()
        if country != "US":
            return
        target = self.guidance_point
        now = datetime.now(timezone.utc)
        if "spc" not in self.guidance_last_fetch or now - self.guidance_last_fetch["spc"] >= timedelta(minutes=10):
            self._submit("spc-guidance", lambda: (target, spc.point_guidance(lat, lon).summary(place)), self._show_spc_guidance)
        if "nws" not in self.guidance_last_fetch or now - self.guidance_last_fetch["nws"] >= timedelta(minutes=10):
            self._submit("point-forecast", lambda: (target, data.point_forecast(lat, lon)), self._show_nws_forecast)
        if "hourly" not in self.guidance_last_fetch or now - self.guidance_last_fetch["hourly"] >= timedelta(minutes=10):
            self._submit("hourly-forecast", lambda: (target, data.hourly_forecast(lat, lon)), self._show_hourly_forecast)
        if "winter" not in self.guidance_last_fetch or now - self.guidance_last_fetch["winter"] >= timedelta(minutes=10):
            self._submit("winter-forecast", lambda: (target, data.winter_forecast(lat, lon)), self._show_winter_forecast)

    def _refresh_station_trend(self):
        station = self._station_for_settings()
        now = datetime.now(timezone.utc)
        if (getattr(self, "station_trend_station", None) == station
                and "station-trend" in self.guidance_last_fetch
                and now - self.guidance_last_fetch["station-trend"] < timedelta(minutes=10)):
            return
        self._submit("station-trend", lambda: (station, data.station_trend(station)), self._show_station_trend)

    def _show_station_trend(self, result):
        station, trend = result
        if station != self._station_for_settings():
            self.root.after(0, self._refresh_station_trend)
            return
        self.station_trend_station = station
        self.guidance_last_fetch["station-trend"] = datetime.now(timezone.utc)
        self.station_trend_text.set(trend.summary())

    def _show_spc_guidance(self, result):
        target, outlook = result
        if target != self.guidance_point:
            self._refresh_guidance()
            return
        self.guidance_last_fetch["spc"] = datetime.now(timezone.utc)
        self.guidance_text.set(outlook)

    def _show_nws_forecast(self, result):
        target, forecast = result
        if target != self.guidance_point:
            self._refresh_guidance()
            return
        self.guidance_last_fetch["nws"] = datetime.now(timezone.utc)
        self.forecast_text.set(forecast)

    def _show_hourly_forecast(self, result):
        target, forecast = result
        if target != self.guidance_point:
            self._refresh_guidance()
            return
        self.guidance_last_fetch["hourly"] = datetime.now(timezone.utc)
        self.hourly_text.set(forecast)

    def _show_winter_forecast(self, result):
        target, forecast = result
        if target != self.guidance_point:
            self._refresh_guidance()
            return
        self.guidance_last_fetch["winter"] = datetime.now(timezone.utc)
        self.winter_text.set(forecast)

    def check_hail(self):
        target = self.guidance_point
        place, lat, lon, country = target
        if country != "US":
            self.hail_text.set("MRMS MESH currently covers the contiguous US")
            return
        self.hail_text.set("Loading current NOAA MRMS MESH hail estimate…")
        self._submit("mrms-hail", lambda: (target, mrms.near_point(lat, lon).summary(place)), self._show_hail)

    def _show_hail(self, result):
        target, summary = result
        if target == self.guidance_point:
            self.hail_text.set(summary)

    def _refresh_local_alert_summary(self):
        target = self.guidance_point
        _place, lat, lon, country = target
        now = datetime.now(timezone.utc)
        if "alerts" in self.guidance_last_fetch and now - self.guidance_last_fetch["alerts"] < timedelta(minutes=5):
            return
        action = data.point_alerts if country == "US" else data.canadian_point_alerts
        self._submit("local-alert-summary", lambda: (target, action(lat, lon)), self._show_local_alert_summary)

    def _show_local_alert_summary(self, result):
        target, alerts = result
        if target != self.guidance_point:
            return
        self.guidance_last_fetch["alerts"] = datetime.now(timezone.utc)
        warnings = [item for item in alerts if item.level == "warning"]
        watches = [item for item in alerts if item.level == "watch"]
        advisories = [item for item in alerts if item.level == "advisory"]
        summary = (f"Official local alerts: {len(warnings)} warning(s), {len(watches)} watch(es), "
                   f"{len(advisories)} advisories")
        if warnings or watches or advisories:
            summary += " · " + (warnings or watches or advisories)[0].headline[:130]
        self.local_alert_text.set(summary)

    def _set_radar_zoom(self, factor):
        if factor not in radar.ZOOMS:
            return
        if self.tabs.index(self.tabs.select()) == 1 and self.radar_product.get() == "National reflectivity":
            self.radar_product.set("Site reflectivity")
        self.radar_zoom = factor
        self.radar_zoom_text.set(f"{factor}×")
        if self.tabs.index(self.tabs.select()) in (1, 4, 5):
            self.refresh()

    def _radar_timeline_changed(self):
        values = ("Latest", "1 scan back", "2 scans back", "3 scans back", "4 scans back", "5 scans back")
        self.radar_frame = values.index(self.radar_timeline.get())
        if self.tabs.index(self.tabs.select()) == 1:
            self.refresh()

    def _show_level3(self, site, choice, zoom, center, frame, boundaries, tilt, result):
        if (site, choice, zoom, center, frame, boundaries, tilt) != (self.radar_site.get(), self.radar_product.get(),
                                                              self.radar_zoom, self.radar_center, self.radar_frame,
                                                              self.radar_boundaries.get(), int(self.radar_tilt.get().split()[-1])):
            self.root.after(0, self.refresh)
            return
        picture, stamp, field = result
        self.radar_field = field
        self.radar_valid.set(f"{site.split(' · ')[0]} {choice} · {stamp}")
        self.radar_stamp.set(f"{stamp} · click to inspect a value; drag to pan")
        self.image_urls["radar"] = f"{site}:{choice}:{zoom}:{center}:{frame}:{boundaries}:{tilt}"
        self._show_image("radar", self.image_urls["radar"], picture)

    def _radar_press(self, event):
        self.radar_drag = (event.x, event.y)

    def _radar_release(self, event):
        if self.radar_drag is None or self.radar_product.get() == "National reflectivity":
            return
        image = self.radar_image
        width, height = self.render_sizes.get("radar", (0, 0))
        if not width or not height:
            return
        left = (image.winfo_width() - width) / 2
        top = (image.winfo_height() - height) / 2
        start_x, start_y = self.radar_drag
        self.radar_drag = None
        x, y = event.x - left, event.y - top
        if not (0 <= x < width and 0 <= y < height):
            return
        site = self.radar_site.get()
        west, south, east, north = map(float, radar._bbox(site, self.radar_sites, self.radar_zoom, self.radar_center).split(","))
        dx, dy = event.x - start_x, event.y - start_y
        if abs(dx) + abs(dy) > 8:
            self.radar_center = ((south + north) / 2 + dy / height * (north - south),
                                 (west + east) / 2 - dx / width * (east - west))
            self.refresh()
        elif self.radar_field:
            lat, lon = north - y / height * (north - south), west + x / width * (east - west)
            value = self.radar_field.value_at(lat, lon)
            unit = level3.PRODUCTS[self.radar_product.get()][2]
            self.status.set(f"K{self.radar_field.site} {self.radar_product.get()} at {lat:.3f}, {lon:.3f}: "
                            + (f"{value:.2f} {unit}" if value is not None else "no valid return"))

    def _step_radar_zoom(self, direction):
        index = radar.ZOOMS.index(self.radar_zoom)
        self._set_radar_zoom(radar.ZOOMS[max(0, min(len(radar.ZOOMS) - 1, index + direction))])

    def _radar_key(self, event, direction):
        if self.tabs.index(self.tabs.select()) not in (1, 4, 5) or isinstance(event.widget, (ttk.Entry, ttk.Combobox, tk.Entry)):
            return None
        self._step_radar_zoom(direction)
        return "break"

    def _radar_site_changed(self):
        self.radar_center = None
        if self.radar_product.get() == "National reflectivity":
            self.radar_product.set("Site reflectivity")
        if self.tabs.index(self.tabs.select()) == 1:
            self.refresh()

    def _set_nearest_radar(self, lat, lon):
        site = radar.nearest_site(lat, lon, self.radar_sites)
        self.radar_site.set(site)
        self.radar_center = (lat, lon)
        if self.radar_product.get() == "National reflectivity":
            self.radar_product.set("Site reflectivity")
        if self.tabs.index(self.tabs.select()) == 1:
            self.refresh()

    def _load_radar_catalog(self):
        self._submit("radar-catalog", radar.available_sites, self._accept_radar_catalog)

    def _accept_radar_catalog(self, sites):
        selected = self.radar_site.get().split(" · ")[0]
        self.radar_sites = sites
        self.radar_site_picker.configure(values=tuple(sites))
        self.radar_site.set(next((name for name in sites if name.startswith(selected + " · ")), next(iter(sites))))
        if self.tabs.index(self.tabs.select()) == 1:
            self.refresh()

    def _show_hrrr(self, hours, token, place, result):
        if hours != int(self.hrrr_hour.get()) or token != self.hrrr_request_token:
            self.refresh()
            return
        picture, timing = result
        self.hrrr_stamp.set(f"NCEP HRRR simulated reflectivity around {place} · {timing} · forecast")
        self.image_urls["hrrr"] = token
        self._show_image("hrrr", token, picture)

    def _show_site_radar(self, site, choice, zoom, center, result):
        if site != self.radar_site.get() or choice != self.radar_product.get() or zoom != self.radar_zoom or center != self.radar_center:
            self.root.after(0, self.refresh)
            return
        picture, valid = result
        source = "NWS" if choice == "Hydrometeor class (hail indicator)" else "Iowa Environmental Mesonet"
        self.radar_valid.set(f"{site.split(' · ')[0]} {choice} · {valid} · {source}")
        self.radar_stamp.set(f"Radar scan valid {valid} · current within 15 minutes")
        self.image_urls["radar"] = "site-radar"
        self._show_image("radar", "site-radar", picture)

    def _show_swath(self, site, choice, zoom, center, result):
        if (site, choice, zoom, center) != (self.radar_site.get(), self.radar_product.get(),
                                            self.radar_zoom, self.radar_center):
            self.root.after(0, self.refresh)
            return
        picture, stamp = result
        self.radar_valid.set(stamp)
        self.radar_stamp.set(stamp + " · drag to pan")
        token = f"{site}:{choice}:{zoom}:{center}:{stamp}"
        self.image_urls["radar"] = token
        self._show_image("radar", token, picture)

    def _show_model(self, hours, token, place, result):
        if hours != int(self.model_hour.get()) or token != self.model_request_token:
            self.root.after(0, self.refresh)
            return
        picture, valid = result
        self.model_valid.set("Around " + place + " · " + valid)
        self.model_stamp.set("Forecast " + valid + " · not an observation or warning")
        self.image_urls["model"] = token
        self._show_image("model", token, picture)

    def _periodic(self):
        if not self.closed:
            self.tick += 1
            if self.tabs.index(self.tabs.select()) <= 2 or self.tick % 5 == 0:
                self.refresh()
            self._refresh_alert_count()
            self._refresh_point_alerts()
            if self.postal_location and (self.monitor_enabled.get() or (self.mini_window is not None and self.mini_window.winfo_exists())) and self.tick % 5 == 0:
                self._refresh_local_weather()
            self.root.after(60_000, self._periodic)

    def _refresh_alert_count(self):
        state = self.state.get().strip().upper()
        if len(state) == 2 and state.isascii() and state.isalpha():
            self._submit("alert-count", lambda: (state, data.alerts(state)), self._show_alert_count)

    def _show_alert_count(self, result):
        state, items = result
        if state != self.state.get().strip().upper():
            return
        self.alerts_snapshot = items
        self.alert_summary.set(f"NWS {state} alerts: {len(items)}")

    def _open_alerts(self):
        self.tabs.select(self.observations_tab)
        self.load_alerts()

    def _open_official_warnings(self):
        webbrowser.open("https://weather.gc.ca/" if self.country.get() == "CA" else "https://www.weather.gov/")

    def _show_observations(self, rows):
        self.table.delete(*self.table.get_children())
        self.rows = {row.station: row for row in rows}
        for row in sorted(rows, key=lambda row: (row.station != self._station_for_settings(), row.station)):
            self.table.insert("", "end", iid=row.station, values=(row.station, row.name, row.observed, f"{row.temp_c:.1f}" if row.temp_c is not None else "—", row.wind, row.visibility, row.flight_category))
        if not rows:
            self._set_details("No observations returned. Try loading a station directly.")
        current = self.rows.get(self._station_for_settings())
        if current and self.postal_location is None:
            temperature = f"{current.temp_c:.1f} °C" if current.temp_c is not None else "temperature unavailable"
            self.local_current.set(f"{current.station} · {temperature} · {current.conditions} · observed {current.observed}")

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
            if row.lat is not None and row.lon is not None:
                self._set_guidance_point(row.station, row.lat, row.lon)
                self._set_nearest_radar(row.lat, row.lon)

    def _open_selected_radar(self):
        row = self.rows.get(self.station.get().strip().upper())
        if row and row.lat is not None and row.lon is not None:
            self._set_nearest_radar(row.lat, row.lon)
            self.tabs.select(self.radar_tab)
        elif self.postal_location:
            self._set_nearest_radar(self.postal_location.lat, self.postal_location.lon)
            self.tabs.select(self.radar_tab)
        else:
            self.status.set("Load or select a station with coordinates to view nearby radar")

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
            row = rows[0]
            if row.station not in self.rows:
                self.table.insert("", 0, iid=row.station,
                                  values=(row.station, row.name, row.observed,
                                          f"{row.temp_c:.1f}" if row.temp_c is not None else "—",
                                          row.wind, row.visibility, row.flight_category))
            self.rows[row.station] = row
            saved = preferences.load()
            saved["station"] = row.station
            preferences.save(saved)
            if row.lat is not None and row.lon is not None:
                self._set_guidance_point(row.station, row.lat, row.lon)
                self._set_nearest_radar(row.lat, row.lon)
            self._set_details(f"{rows[0].name} · {rows[0].observed}\n\n{rows[0].raw}\n\nFORECAST\n{forecast}")

    def set_location(self):
        try:
            country, code = location.validate_postal(self.country.get(), self.postal_code.get())
        except data.DataError as exc:
            self.status.set(str(exc))
            self.point_status.set(str(exc))
            return
        self.point_status.set("Resolving postal area…")
        street = self.street.get().strip()
        self._submit("location", lambda: location.resolve(country, code, street), self._accept_location)

    def _location_edited(self, _event):
        if self.postal_location is not None:
            previous = self.postal_location
            self.postal_location = None
            self.monitor_point = None
            self.monitor_enabled.set(False)
            preferences.save({"station": self._station_for_settings(), "country": previous.country,
                              "postal_code": previous.code, "street": previous.street, "monitor_enabled": False})
            self.point_status.set("Set the new ZIP or postal code to resume local weather and alerts")

    def _save_preferences(self):
        preferences.save({"station": self._station_for_settings(), "country": self.country.get(),
                          "postal_code": self.postal_code.get(), "street": self.street.get(),
                          "monitor_enabled": self.monitor_enabled.get()})

    def _station_for_settings(self):
        try:
            return data.validate_station(self.station.get())
        except data.DataError:
            return preferences.load().get("station", "KDTW")

    def _accept_location(self, resolved: location.PostalLocation):
        try:
            current = location.validate_postal(self.country.get(), self.postal_code.get())
        except data.DataError:
            return
        if (resolved.country, resolved.code) != current or resolved.street != self.street.get().strip():
            return
        prior = self.postal_location
        if prior != resolved:
            self.monitor_seen.clear()
        self.postal_location = resolved
        self._set_guidance_point(resolved.locality or resolved.code, resolved.lat, resolved.lon, resolved.country)
        self._set_nearest_radar(resolved.lat, resolved.lon)
        self.postal_code.set(resolved.code)
        self.monitor_point = (resolved.lat, resolved.lon) if self.monitor_enabled.get() else None
        self.point_status.set(resolved.label)
        self._save_preferences()
        self._refresh_local_weather()
        self._refresh_point_alerts()
        if self.open_mini_on_location:
            self.open_mini_on_location = False
            self._show_mini()

    def _refresh_local_weather(self):
        if self.postal_location:
            target = self.postal_location
            self._submit("local-weather", lambda: (target, data.nearby_metar(target.lat, target.lon)), self._accept_local_weather)

    def _accept_local_weather(self, result):
        target, row = result
        if target == self.postal_location:
            self._update_mini(row)

    def load_alerts(self):
        self._submit("alerts", lambda: data.alerts(self.state.get()), self._show_alerts)

    def _show_alerts(self, alerts):
        self.alert_summary.set(f"NWS {self.state.get().strip().upper()} alerts: {len(alerts)}")
        if not alerts:
            self._set_details("No active NWS alerts returned for this state.")
        else:
            self._set_details("ACTIVE NWS ALERTS\n\n" + "\n\n".join(f"{event}: {headline}\n{description}" for event, headline, description in alerts[:5]))

    def _load_image(self, key, url):
        self.image_urls[key] = url
        def decode():
            raw, updated = data.image_record(url)
            with Image.open(io.BytesIO(raw)) as opened:
                opened.seek(0)
                result = opened.convert("RGB")
                result.thumbnail((960, 500), Image.Resampling.LANCZOS)
                return result, updated
        self._submit(key, decode, lambda result: self._show_dated_image(key, url, result))

    def _show_dated_image(self, key, url, result):
        picture, updated = result
        self._show_image(key, url, picture)
        if self.image_urls.get(key) == url:
            getattr(self, key + "_stamp").set(f"Source updated {updated:%d %b %Y %H:%M UTC} · current as of fetch")

    def _show_image(self, key, url, pil_image):
        if self.image_urls.get(key) != url:
            self.root.after(0, self.refresh)
            return
        self.image_sources[key] = (url, pil_image)
        self._render_image(key, pil_image)

    def _render_image(self, key, source):
        picture = source.copy()
        picture.thumbnail((max(400, self.root.winfo_width() - 60),
                           max(240, self.root.winfo_height() - 270)), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(picture, master=self.root)
        self.images[key] = photo
        self.render_sizes[key] = picture.size
        getattr(self, key + "_image").configure(image=photo, text="")

    def _schedule_image_resize(self, event):
        if event.widget is not self.root or not self.image_sources or self.closed:
            return
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(180, self._resize_images)

    def _resize_images(self):
        self.resize_job = None
        for key, (url, source) in self.image_sources.items():
            if self.image_urls.get(key) == url:
                self._render_image(key, source)

    def _update_mini(self, row: data.Observation):
        temperature = f"{row.temp_c:.1f} °C" if row.temp_c is not None else "Temperature unavailable"
        code = self.postal_location.code if self.postal_location else "Local"
        self.mini_weather.set(f"{code} · {temperature}\n{row.conditions} · {row.station} airport\nObserved {row.observed}")
        self.local_current.set(f"{temperature} · {row.conditions} · nearby airport {row.station} · observed {row.observed}")

    def _show_mini(self):
        if self.postal_location is None:
            self.status.set("Set a valid ZIP or postal code before opening local weather")
            return
        if self.mini_window is not None and self.mini_window.winfo_exists():
            self.mini_window.lift()
            return
        mini = tk.Toplevel(self.root)
        mini.title("CAVE Portable weather")
        mini.geometry("370x180")
        mini.minsize(340, 160)
        mini.configure(bg=BG)
        ttk.Label(mini, textvariable=self.mini_weather, font=("Sans", 12, "bold"), padding=12, wraplength=345).pack(fill="x")
        ttk.Label(mini, textvariable=self.point_status, foreground=MUTED, padding=(12, 0), wraplength=345).pack(fill="x")
        ttk.Button(mini, text="Open main view", command=lambda: (self.root.deiconify(), self.root.lift())).pack(anchor="e", padx=10, pady=4)
        self.mini_window = mini
        self._refresh_local_weather()

    def _toggle_monitor(self):
        if self.monitor_enabled.get():
            if self.postal_location is None:
                self.monitor_enabled.set(False)
                self.status.set("Set a valid ZIP or postal code before enabling local warnings")
                return
            self.monitor_seen.clear()
            self.monitor_point = (self.postal_location.lat, self.postal_location.lon)
            self._refresh_point_alerts()
        else:
            self.monitor_point = None
            self.point_status.set("Local alert monitor off")
        self._save_preferences()

    def _toggle_autostart(self):
        if self.autostart.get() and self.postal_location is None:
            self.autostart.set(False)
            self.status.set("Set a valid ZIP or postal code before enabling start at login")
            return
        try:
            preferences.set_autostart(self.autostart.get())
            self.status.set("Start at login " + ("enabled" if self.autostart.get() else "disabled"))
        except OSError as exc:
            self.autostart.set(not self.autostart.get())
            self.status.set(f"Could not update login startup: {exc}")

    def _refresh_point_alerts(self):
        if self.monitor_enabled.get() and self.monitor_point is not None and self.postal_location:
            lat, lon = self.monitor_point
            country = self.postal_location.country
            self._submit("point-alerts", lambda: (lat, lon, country, data.point_alerts(lat, lon) if country == "US" else data.canadian_point_alerts(lat, lon)), self._accept_point_alerts)

    def _accept_point_alerts(self, result):
        lat, lon, country, alerts = result
        if self.monitor_point == (lat, lon) and self.postal_location and self.postal_location.country == country:
            self._show_point_alerts(alerts)

    def _show_point_alerts(self, alerts: list[data.WeatherAlert]):
        if not self.monitor_enabled.get():
            return
        area = self.postal_location.code if self.postal_location else "postal area"
        agency = "NWS" if self.postal_location and self.postal_location.country == "US" else "ECCC"
        warning_count = sum(alert.level == "warning" for alert in alerts)
        watch_count = sum(alert.level == "watch" for alert in alerts)
        advisory_count = sum(alert.level == "advisory" for alert in alerts)
        self.point_status.set(f"{area} centroid · {warning_count} {agency} warning(s), "
                              f"{watch_count} watch(es), {advisory_count} advisories")
        fresh = [alert for alert in alerts if alert.level in ("warning", "watch")
                 and alert.identifier not in self.monitor_seen]
        self.monitor_seen.update(alert.identifier for alert in alerts)
        if fresh:
            if any(alert.level == "warning" for alert in fresh):
                self.root.bell()
            summary = "\n\n".join(f"{alert.event}: {alert.headline}\n{alert.description[:500]}" for alert in fresh[:3])
            title = "New " + agency + " weather alert near " + area
            show = messagebox.showwarning if any(alert.level == "warning" for alert in fresh) else messagebox.showinfo
            show(title, summary + "\n\nCheck official local guidance.", parent=self.root)

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    if sys.platform.startswith("linux") and not ("DISPLAY" in __import__("os").environ or "WAYLAND_DISPLAY" in __import__("os").environ):
        raise SystemExit("CAVE Portable needs a graphical desktop session")
    root = tk.Tk(className="Caveportable")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
