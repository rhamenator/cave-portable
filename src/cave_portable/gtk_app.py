"""Native Wayland desktop view for Linux. Weather operations stay off the UI thread."""

from __future__ import annotations

import io
import tempfile
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from importlib.resources import files

import gi
from PIL import Image, ImageDraw

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3
except (ImportError, ValueError):
    AyatanaAppIndicator3 = None

from . import __version__, data, hrrr, level3, location, model, mrms, preferences, radar, spc


def label(text: str) -> Gtk.Label:
    item = Gtk.Label(label=text)
    item.set_xalign(0)
    return item


def button(text: str, callback) -> Gtk.Button:
    item = Gtk.Button(label=text)
    item.connect("clicked", lambda _widget: callback())
    return item


def row(*items) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    for item in items:
        box.pack_start(item, False, False, 0)
    return box


def choice(values, selected: str, callback=None) -> Gtk.ComboBoxText:
    widget = Gtk.ComboBoxText()
    for value in values:
        widget.append_text(value)
    widget.set_active(list(values).index(selected))
    if callback:
        widget.connect("changed", lambda _widget: callback())
    return widget


class App:
    def __init__(self):
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="weather")
        self.pending: set[str] = set()
        self.images: dict[str, tuple[str, Image.Image]] = {}
        self.image_targets: dict[str, Gtk.Image] = {}
        self.image_stamps: dict[str, Gtk.Label] = {}
        self.image_requests: dict[str, str] = {}
        self.postal_location: location.PostalLocation | None = None
        self.setting_postal = False
        self.monitor_seen: set[str] = set()
        self.mini: Gtk.Window | None = None
        self.latest_local_weather: str | None = None
        self.saved = preferences.load()
        self.radar_sites = dict(radar.SITES)
        self.radar_zoom = 1
        self.radar_center: tuple[float, float] | None = None
        self.radar_field: level3.Field | None = None
        self.radar_frame = 0
        self.radar_drag: tuple[float, float] | None = None
        self.zoom_labels: list[Gtk.Label] = []
        self.updating_radar_catalog = False
        self.setting_nearest_radar = False
        self.guidance_point = ("KLAN", 42.7761, -84.5997, "US")
        self.guidance_last_fetch: dict[str, datetime] = {}
        self.guidance_labels: dict[str, Gtk.Label] = {}
        self.open_mini_on_location = bool(self.saved.get("monitor_enabled"))
        self.indicator = None
        self.indicator_icons = None

        self.window = Gtk.Window(title=f"CAVE Portable {__version__}")
        self.window.set_default_size(1000, 680)
        self.window.set_size_request(860, 550)
        self.window.set_icon_from_file(str(files("cave_portable").joinpath("assets/icon-64.png")))
        self.window.connect("destroy", self.close)
        self.window.connect("key-press-event", self.radar_key)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_border_width(12)
        self.window.add(outer)

        header = row(Gtk.Image.new_from_file(str(files("cave_portable").joinpath("assets/icon-32.png"))),
                     label("CAVE PORTABLE · NOAA / NWS / SPC"))
        header.pack_end(button("Refresh", self.refresh), False, False, 0)
        header.pack_end(button("Official warnings", self.open_official), False, False, 0)
        header.pack_end(button("Minimize to tray", self.minimize_to_tray), False, False, 0)
        self.alert_button = button("NWS alerts", self.load_alerts)
        header.pack_end(self.alert_button, False, False, 0)
        outer.pack_start(header, False, False, 0)

        self.tabs = Gtk.Notebook()
        outer.pack_start(self.tabs, True, True, 0)
        self.observations_ui()
        self.image_ui("radar", "Radar", "Decoded NOAA Level III radar at the selected site · optional national composite")
        self.image_ui("satellite", "Satellite", "NOAA/NESDIS GOES GeoColor")
        self.image_ui("severe", "Severe outlook & CAPE", "SPC categorical outlooks and Southern Plains MLCAPE")
        self.image_ui("model", "Forecast ingredients", "Selected GFS run and field · NSF Unidata THREDDS / USGS map")
        self.image_ui("hrrr", "HRRR storm forecast", "NCEP HRRR simulated reflectivity · forecast, not observed radar")
        self.tabs.connect("switch-page", lambda *_args: GLib.idle_add(self.refresh))

        self.status = label("Ready · For urgent decisions, use official warnings and local instructions")
        outer.pack_start(self.status, False, False, 0)
        self.window.show_all()
        self.setup_indicator()
        GLib.timeout_add(200, self.refresh)
        GLib.timeout_add(500, self.refresh_alert_count)
        GLib.timeout_add(900, self.load_radar_catalog)
        if self.saved.get("postal_code"):
            GLib.timeout_add(700, self.set_location)
        GLib.timeout_add_seconds(60, self.periodic)

    def observations_ui(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(8)
        self.tabs.append_page(page, Gtk.Label(label="Observations"))
        self.country = choice(("US", "CA"), self.saved.get("country", "US"), self.location_edited)
        self.postal = Gtk.Entry()
        self.postal.set_width_chars(12)
        self.postal.set_text(self.saved.get("postal_code", ""))
        self.postal.connect("changed", lambda _widget: self.location_edited())
        self.postal.connect("activate", lambda _widget: self.set_location())
        page.pack_start(row(label("Local weather · ZIP / postal code required:"), self.country, self.postal,
                            button("Set location", self.set_location), label("No IP location")), False, False, 0)
        self.street = Gtk.Entry()
        self.street.set_width_chars(36)
        self.street.set_text(self.saved.get("street", ""))
        self.street.connect("changed", lambda _widget: self.location_edited())
        self.street.connect("activate", lambda _widget: self.set_location())
        page.pack_start(row(label("Street address (optional):"), self.street, label("Approximate geocode")), False, False, 0)
        self.station = Gtk.Entry()
        self.station.set_width_chars(8)
        self.station.set_text(self.saved.get("station", "KDTW"))
        self.station.connect("activate", lambda _widget: self.load_station())
        self.state = Gtk.Entry()
        self.state.set_width_chars(4)
        self.state.set_text("MI")
        page.pack_start(row(label("ICAO station:"), self.station, button("Load station", self.load_station),
                            button("View nearest radar", self.open_selected_radar),
                            label("US state alerts:"), self.state, button("Load alerts", self.load_alerts)), False, False, 0)
        self.monitor = Gtk.CheckButton(label="Monitor official warnings and watches at postal area")
        self.monitor.set_active(bool(self.saved.get("monitor_enabled") and self.saved.get("postal_code")))
        self.monitor.connect("toggled", self.toggle_monitor)
        self.autostart = Gtk.CheckButton(label="Start at login")
        self.autostart.set_active(preferences.is_autostart_enabled())
        self.autostart.connect("toggled", self.toggle_autostart)
        page.pack_start(row(self.monitor, button("Mini weather window", self.show_mini), self.autostart), False, False, 0)
        self.point_status = label("Set a ZIP or postal code for local weather and alerts")
        page.pack_start(self.point_status, False, False, 0)
        briefing = Gtk.Expander(label="Selected location briefing · official sources")
        briefing.set_expanded(True)
        briefing_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        briefing_box.set_border_width(5)
        self.local_current_label = label("Nearby observation loading…")
        briefing_box.pack_start(self.local_current_label, False, False, 0)
        self.station_trend_label = label("Selected airport trend loading…")
        self.station_trend_label.set_line_wrap(True)
        briefing_box.pack_start(self.station_trend_label, False, False, 0)
        self.local_alert_label = label("Local official warnings and watches loading…")
        briefing_box.pack_start(self.local_alert_label, False, False, 0)
        local_guidance = label("SPC point outlook loading…")
        local_guidance.set_line_wrap(True)
        self.guidance_labels["observations"] = local_guidance
        briefing_box.pack_start(local_guidance, False, False, 0)
        self.local_forecast_label = label("NWS point forecast loading…")
        self.local_forecast_label.set_line_wrap(True)
        briefing_box.pack_start(self.local_forecast_label, False, False, 0)
        self.local_hourly_label = label("NWS hourly forecast loading…")
        self.local_hourly_label.set_line_wrap(True)
        briefing_box.pack_start(self.local_hourly_label, False, False, 0)
        self.hail_label = label("MRMS MESH hail estimate: select Check hail for an on-demand reading")
        self.hail_label.set_line_wrap(True)
        briefing_box.pack_start(row(button("Check hail near point", self.check_hail), self.hail_label), False, False, 0)
        briefing.add(briefing_box)
        page.pack_start(briefing, False, False, 0)

        self.store = Gtk.ListStore(str, str, str, str, str, str, str)
        self.table = Gtk.TreeView(model=self.store)
        for idx, title in enumerate(("ICAO", "Location", "Observed", "°C", "Wind", "Vis. mi", "Flight")):
            column = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=idx)
            column.set_resizable(True)
            column.set_min_width(45)
            self.table.append_column(column)
        self.table.get_selection().connect("changed", self.select_station)
        self.table.connect("row-activated", lambda *_args: self.open_selected_radar())
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.table)
        page.pack_start(scroll, True, True, 0)
        self.details = Gtk.TextView()
        self.details.set_editable(False)
        self.details.set_wrap_mode(Gtk.WrapMode.WORD)
        self.details.get_buffer().set_text("Select an observation or load a station. METAR and TAF from NOAA Aviation Weather Center. Alerts from NWS.")
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_size_request(-1, 90)
        detail_scroll.add(self.details)
        page.pack_start(detail_scroll, False, False, 0)
        self.rows: dict[str, data.Observation] = {}

    def image_ui(self, key: str, title: str, caption: str):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(8)
        self.tabs.append_page(page, Gtk.Label(label=title))
        page.pack_start(label(caption), False, False, 0)
        if key in ("severe", "hrrr"):
            guidance = label("Loading local SPC outlook for KLAN…")
            guidance.set_line_wrap(True)
            guidance.set_max_width_chars(105)
            self.guidance_labels[key] = guidance
            page.pack_start(guidance, False, False, 0)
        if key == "severe":
            page.pack_start(row(button("Check MRMS hail near point", self.check_hail)), False, False, 0)
        if key == "hrrr":
            self.forecast_label = label("Loading local NWS forecast…")
            self.forecast_label.set_line_wrap(True)
            self.forecast_label.set_max_width_chars(105)
            page.pack_start(self.forecast_label, False, False, 0)
        image = Gtk.Image()
        image.set_size_request(700, 350)
        self.image_targets[key] = image
        image_widget = image
        if key == "radar":
            image_widget = Gtk.EventBox()
            image_widget.add(image)
            image_widget.connect("button-press-event", self.radar_press)
            image_widget.connect("button-release-event", self.radar_release)
        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        viewport.add_with_viewport(image_widget)
        page.pack_start(viewport, True, True, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.pack_start(controls, False, False, 0)
        if key == "radar":
            self.radar_product = choice(("National reflectivity", *radar.PRODUCTS, *level3.PRODUCTS,
                                         "MRMS hail swath (30 min)"), "Digital reflectivity", self.refresh)
            self.radar_site = choice(tuple(self.radar_sites), "GRR · Grand Rapids", self.radar_site_changed)
            controls.pack_start(self.radar_product, False, False, 0)
            controls.pack_start(self.radar_site, False, False, 0)
            self.radar_timeline = choice(("Latest", "1 scan back", "2 scans back", "3 scans back", "4 scans back", "5 scans back"),
                                         "Latest", self.timeline_changed)
            controls.pack_start(self.radar_timeline, False, False, 0)
            self.radar_tilt = choice(tuple(f"Tilt {tilt}" for tilt in level3.TILTS), "Tilt 0", self.refresh)
            controls.pack_start(self.radar_tilt, False, False, 0)
            self.radar_boundaries = Gtk.CheckButton(label="Official boundaries")
            self.radar_boundaries.set_active(True)
            self.radar_boundaries.connect("toggled", lambda _widget: self.refresh())
            controls.pack_start(self.radar_boundaries, False, False, 0)
            controls.pack_start(button("−", lambda: self.step_radar_zoom(-1)), False, False, 0)
            self.zoom_label = label("1×")
            self.zoom_labels.append(self.zoom_label)
            controls.pack_start(self.zoom_label, False, False, 0)
            controls.pack_start(button("+", lambda: self.step_radar_zoom(1)), False, False, 0)
        elif key == "satellite":
            self.satellite_choice = choice(tuple(data.SATELLITE), "GOES East", self.refresh)
            controls.pack_start(self.satellite_choice, False, False, 0)
        elif key == "severe":
            self.severe_choice = choice((*data.OUTLOOK, "Southern Plains MLCAPE"), "Day 1", self.refresh)
            controls.pack_start(self.severe_choice, False, False, 0)
            controls.pack_start(label("CAPE is instability, not a standalone severe forecast."), False, False, 0)
        elif key == "model":
            self.model_field = choice(tuple(model.FIELDS), "CAPE", self.refresh)
            controls.pack_start(self.model_field, False, False, 0)
            self.model_run = choice(model.RUN_CHOICES, "Latest run", self.refresh)
            controls.pack_start(self.model_run, False, False, 0)
            controls.pack_start(label("Forecast hour:"), False, False, 0)
            self.model_hour = choice(tuple(str(hour) for hour in model.HOURS), "24", self.refresh)
            controls.pack_start(self.model_hour, False, False, 0)
            self.add_zoom_controls(controls)
        else:
            controls.pack_start(label("Hours after latest HRRR run:"), False, False, 0)
            self.hrrr_hour = choice(tuple(str(hour) for hour in hrrr.HOURS), "6", self.refresh)
            controls.pack_start(self.hrrr_hour, False, False, 0)
            self.add_zoom_controls(controls)
        stamp = label("Source time pending. Images show source-provided valid times and legends when present.")
        stamp.set_line_wrap(True)
        stamp.set_max_width_chars(120)
        page.pack_start(stamp, False, False, 0)
        self.image_stamps[key] = stamp

    def add_zoom_controls(self, controls):
        controls.pack_start(button("−", lambda: self.step_radar_zoom(-1)), False, False, 0)
        zoom_label = label(f"{self.radar_zoom}×")
        self.zoom_labels.append(zoom_label)
        controls.pack_start(zoom_label, False, False, 0)
        controls.pack_start(button("+", lambda: self.step_radar_zoom(1)), False, False, 0)

    def submit(self, key: str, operation, callback):
        if self.closed or key in self.pending:
            return
        self.pending.add(key)
        self.status.set_text(f"Loading {key}…")
        future = self.pool.submit(operation)
        future.add_done_callback(lambda done: GLib.idle_add(self.complete, key, done, callback))

    def complete(self, key, future, callback):
        self.pending.discard(key)
        if self.closed:
            return False
        try:
            callback(future.result())
            self.status.set_text(f"Updated {key} · {datetime.now(timezone.utc):%H:%M UTC}")
        except Exception as exc:
            self.status.set_text(f"{key}: {exc}")
            image_key = "radar" if key == "site-radar" else key
            if image_key in self.image_targets:
                self.image_targets[image_key].clear()
                self.image_stamps[image_key].set_text(f"No current image available: {exc}")
            elif key == "point-alerts":
                self.point_status.set_text("Local warning feed unavailable; check the official service")
            elif key in ("location", "local-weather"):
                self.point_status.set_text(f"Local weather unavailable: {exc}")
                if key == "local-weather":
                    self.latest_local_weather = None
                    if self.mini:
                        self.mini_label.set_text("Nearby observation unavailable. Check the official weather service.")
            elif key == "spc-guidance":
                for item in self.guidance_labels.values():
                    item.set_text(f"Local SPC outlook unavailable: {exc}. Check the official SPC outlook.")
            elif key == "point-forecast":
                self.forecast_label.set_text(f"Local NWS forecast unavailable: {exc}")
                self.local_forecast_label.set_text(f"Local NWS forecast unavailable: {exc}")
            elif key == "hourly-forecast":
                self.local_hourly_label.set_text(f"NWS hourly forecast unavailable: {exc}")
            elif key == "mrms-hail":
                self.hail_label.set_text(f"MRMS MESH hail estimate unavailable: {exc}")
            elif key == "local-alert-summary":
                self.local_alert_label.set_text(f"Official local alert feed unavailable: {exc}")
            elif key == "station-trend":
                self.station_trend_label.set_text(f"Selected airport trend unavailable: {exc}")
        return False

    def refresh(self):
        tab = self.tabs.get_current_page()
        if tab == 0:
            stations = tuple(dict.fromkeys((self.valid_station(), *data.STATIONS)))
            self.submit("observations", lambda: data.metars(stations), self.show_observations)
            self.refresh_station_trend()
            self.refresh_guidance()
        elif tab == 1:
            product = self.radar_product.get_active_text()
            if product == "National reflectivity":
                self.radar_field = None
                self.load_image("radar", data.RADAR_URL)
            else:
                site = self.radar_site.get_active_text()
                if not site:
                    return False
                center = self.radar_center
                frame = self.radar_frame
                boundaries = self.radar_boundaries.get_active()
                tilt = self.radar_tilt.get_active()
                token = f"{site}:{product}:{self.radar_zoom}:{center}:{frame}:{boundaries}:{tilt}"
                self.begin_image_request("radar", token)
                sites, zoom = self.radar_sites, self.radar_zoom
                if product == "MRMS hail swath (30 min)":
                    self.radar_field = None
                    self.submit("site-radar", lambda: mrms.swath_map(site, sites, zoom, center),
                                lambda result: self.show_product("radar", token, result, ""))
                elif product in level3.PRODUCTS:
                    alert_point = self.guidance_point[1:3]
                    include_us_alerts = self.guidance_point[3] == "US"
                    self.submit("site-radar", lambda: level3.field_map(site, product, sites, zoom, center, frame, boundaries, tilt,
                                                                       alert_point, include_us_alerts),
                                lambda result: self.show_level3(token, result))
                else:
                    self.radar_field = None
                    source = "NWS Level III hydrometeor scan" if product == "Hydrometeor class (hail indicator)" else "Iowa Mesonet radar scan"
                    self.submit("site-radar", lambda: radar.site_map(site, product, sites=sites, zoom=zoom, center=center),
                                lambda result: self.show_product("radar", token, result, source))
        elif tab == 2:
            self.load_image("satellite", data.SATELLITE[self.satellite_choice.get_active_text()])
        elif tab == 3:
            selected = self.severe_choice.get_active_text()
            self.load_image("severe", data.MLCAPE_URL if selected == "Southern Plains MLCAPE" else data.OUTLOOK[selected])
            self.refresh_guidance()
        elif tab == 4:
            hours = int(self.model_hour.get_active_text())
            field_name, run_choice = self.model_field.get_active_text(), self.model_run.get_active_text()
            place, lat, lon, _country = self.guidance_point
            zoom = self.radar_zoom
            token = f"GFS:{field_name}:{run_choice}:{hours}:{lat:.4f}:{lon:.4f}:{zoom}"
            self.begin_image_request("model", token)
            self.submit("model", lambda: model.field_map(field_name, hours, model.regional_bbox(lat, lon, zoom), run_choice),
                        lambda result: self.show_product("model", token, result, f"Forecast around {place} ·"))
        elif tab == 5:
            hours = int(self.hrrr_hour.get_active_text())
            place, lat, lon, _country = self.guidance_point
            zoom = self.radar_zoom
            token = f"HRRR:{hours}:{lat:.4f}:{lon:.4f}:{zoom}"
            self.begin_image_request("hrrr", token)
            self.submit("hrrr", lambda: hrrr.reflectivity(hours, center=(lat, lon), zoom=zoom),
                        lambda result: self.show_product("hrrr", token, result,
                                                         f"NCEP HRRR simulated reflectivity around {place}"))
            self.refresh_guidance()
        return False

    def set_guidance_point(self, place: str, lat: float, lon: float, country: str = "US"):
        target = (place, lat, lon, country)
        if target != self.guidance_point:
            self.guidance_point = target
            self.guidance_last_fetch.clear()
            for item in self.guidance_labels.values():
                item.set_text(f"Loading local SPC outlook for {place}…" if country == "US"
                              else "SPC severe outlooks cover the contiguous US")
            self.forecast_label.set_text("Loading local NWS forecast…" if country == "US"
                                         else "NWS point forecasts cover the contiguous US")
            self.local_forecast_label.set_text("Loading local NWS forecast…" if country == "US"
                                               else "NWS point forecasts cover the contiguous US")
            self.local_hourly_label.set_text("Loading local NWS hourly forecast…" if country == "US"
                                             else "NWS hourly forecasts cover the contiguous US")
            self.local_alert_label.set_text("Local official warnings and watches loading…")
            self.hail_label.set_text("MRMS MESH hail estimate: select Check hail for this point")
            if self.tabs.get_current_page() in (0, 3, 5):
                self.refresh_guidance()

    def refresh_guidance(self):
        place, lat, lon, country = self.guidance_point
        self.refresh_local_alert_summary()
        if country != "US":
            return
        target = self.guidance_point
        now = datetime.now(timezone.utc)
        if "spc" not in self.guidance_last_fetch or now - self.guidance_last_fetch["spc"] >= timedelta(minutes=10):
            self.submit("spc-guidance", lambda: (target, spc.point_guidance(lat, lon).summary(place)), self.show_spc_guidance)
        if "nws" not in self.guidance_last_fetch or now - self.guidance_last_fetch["nws"] >= timedelta(minutes=10):
            self.submit("point-forecast", lambda: (target, data.point_forecast(lat, lon)), self.show_nws_forecast)
        if "hourly" not in self.guidance_last_fetch or now - self.guidance_last_fetch["hourly"] >= timedelta(minutes=10):
            self.submit("hourly-forecast", lambda: (target, data.hourly_forecast(lat, lon)), self.show_hourly_forecast)

    def refresh_station_trend(self):
        station = self.valid_station()
        now = datetime.now(timezone.utc)
        if (getattr(self, "station_trend_station", None) == station
                and "station-trend" in self.guidance_last_fetch
                and now - self.guidance_last_fetch["station-trend"] < timedelta(minutes=10)):
            return
        self.submit("station-trend", lambda: (station, data.station_trend(station)), self.show_station_trend)

    def show_station_trend(self, result):
        station, trend = result
        if station != self.valid_station():
            self.refresh_station_trend()
            return
        self.station_trend_station = station
        self.guidance_last_fetch["station-trend"] = datetime.now(timezone.utc)
        self.station_trend_label.set_text(trend.summary())

    def show_spc_guidance(self, result):
        target, outlook = result
        if target != self.guidance_point:
            self.refresh_guidance()
            return
        self.guidance_last_fetch["spc"] = datetime.now(timezone.utc)
        for item in self.guidance_labels.values():
            item.set_text(outlook)

    def show_nws_forecast(self, result):
        target, forecast = result
        if target != self.guidance_point:
            self.refresh_guidance()
            return
        self.guidance_last_fetch["nws"] = datetime.now(timezone.utc)
        self.forecast_label.set_text(forecast)
        self.local_forecast_label.set_text(forecast)

    def show_hourly_forecast(self, result):
        target, forecast = result
        if target != self.guidance_point:
            self.refresh_guidance()
            return
        self.guidance_last_fetch["hourly"] = datetime.now(timezone.utc)
        self.local_hourly_label.set_text(forecast)

    def check_hail(self):
        target = self.guidance_point
        place, lat, lon, country = target
        if country != "US":
            self.hail_label.set_text("MRMS MESH currently covers the contiguous US")
            return
        self.hail_label.set_text("Loading current NOAA MRMS MESH hail estimate…")
        self.submit("mrms-hail", lambda: (target, mrms.near_point(lat, lon).summary(place)), self.show_hail)

    def show_hail(self, result):
        target, summary = result
        if target == self.guidance_point:
            self.hail_label.set_text(summary)

    def refresh_local_alert_summary(self):
        target = self.guidance_point
        _place, lat, lon, country = target
        now = datetime.now(timezone.utc)
        if "alerts" in self.guidance_last_fetch and now - self.guidance_last_fetch["alerts"] < timedelta(minutes=5):
            return
        action = data.point_alerts if country == "US" else data.canadian_point_alerts
        self.submit("local-alert-summary", lambda: (target, action(lat, lon)), self.show_local_alert_summary)

    def show_local_alert_summary(self, result):
        target, alerts = result
        if target != self.guidance_point:
            return
        self.guidance_last_fetch["alerts"] = datetime.now(timezone.utc)
        warnings = [item for item in alerts if item.level == "warning"]
        watches = [item for item in alerts if item.level == "watch"]
        summary = f"Official local alerts: {len(warnings)} warning(s), {len(watches)} watch(es)"
        if warnings or watches:
            summary += " · " + (warnings or watches)[0].headline[:130]
        self.local_alert_label.set_text(summary)

    def set_radar_zoom(self, factor: int):
        if factor not in radar.ZOOMS:
            return
        if self.tabs.get_current_page() == 1 and self.radar_product.get_active_text() == "National reflectivity":
            self.radar_product.set_active(1)
        self.radar_zoom = factor
        for item in self.zoom_labels:
            item.set_text(f"{factor}×")
        if self.tabs.get_current_page() in (1, 4, 5):
            self.refresh()

    def timeline_changed(self):
        self.radar_frame = self.radar_timeline.get_active()
        if self.tabs.get_current_page() == 1:
            self.refresh()

    def show_level3(self, token, result):
        picture, stamp, field = result
        if self.image_requests.get("radar") != token:
            self.refresh()
            return
        self.radar_field = field
        self.show_product("radar", token, (picture, stamp), "Decoded scan")

    def radar_press(self, _widget, event):
        self.radar_drag = (event.x, event.y)
        return True

    def radar_release(self, _widget, event):
        if self.radar_drag is None or self.radar_product.get_active_text() == "National reflectivity":
            return False
        start_x, start_y = self.radar_drag
        self.radar_drag = None
        site = self.radar_site.get_active_text()
        west, south, east, north = map(float, radar._bbox(site, self.radar_sites, self.radar_zoom, self.radar_center).split(","))
        width = max(1, self.image_targets["radar"].get_allocated_width())
        height = max(1, self.image_targets["radar"].get_allocated_height())
        dx, dy = event.x - start_x, event.y - start_y
        if abs(dx) + abs(dy) > 8:
            self.radar_center = ((south + north) / 2 + dy / height * (north - south),
                                 (west + east) / 2 - dx / width * (east - west))
            self.refresh()
        elif self.radar_field:
            lat = north - event.y / height * (north - south)
            lon = west + event.x / width * (east - west)
            value = self.radar_field.value_at(lat, lon)
            unit = level3.PRODUCTS[self.radar_product.get_active_text()][2]
            self.status.set_text(f"K{self.radar_field.site} {self.radar_product.get_active_text()} at {lat:.3f}, {lon:.3f}: "
                                 + (f"{value:.2f} {unit}" if value is not None else "no valid return"))
        return True

    def step_radar_zoom(self, direction: int):
        index = radar.ZOOMS.index(self.radar_zoom)
        self.set_radar_zoom(radar.ZOOMS[max(0, min(len(radar.ZOOMS) - 1, index + direction))])

    def radar_key(self, _window, event):
        if self.tabs.get_current_page() not in (1, 4, 5) or isinstance(self.window.get_focus(), (Gtk.Entry, Gtk.TextView)):
            return False
        key = Gdk.keyval_name(event.keyval)
        if key in ("plus", "equal", "KP_Add"):
            self.step_radar_zoom(1)
            return True
        if key in ("minus", "underscore", "KP_Subtract"):
            self.step_radar_zoom(-1)
            return True
        return False

    def radar_site_changed(self):
        if self.updating_radar_catalog or self.setting_nearest_radar or not self.radar_site.get_active_text():
            return
        self.radar_center = None
        if self.radar_product.get_active_text() == "National reflectivity":
            self.radar_product.set_active(1)
        if self.tabs.get_current_page() == 1:
            self.refresh()

    def set_nearest_radar(self, lat: float, lon: float):
        site = radar.nearest_site(lat, lon, self.radar_sites)
        self.setting_nearest_radar = True
        if self.radar_site.get_active_text() != site:
            self.radar_site.set_active(list(self.radar_sites).index(site))
        self.setting_nearest_radar = False
        self.radar_center = (lat, lon)
        if self.radar_product.get_active_text() == "National reflectivity":
            self.radar_product.set_active(1)
        if self.tabs.get_current_page() == 1:
            self.refresh()

    def load_radar_catalog(self):
        self.submit("radar-catalog", radar.available_sites, self.accept_radar_catalog)
        return False

    def accept_radar_catalog(self, sites):
        selected = self.radar_site.get_active_text()
        selected_id = selected.split(" · ")[0] if selected else "GRR"
        self.radar_sites = sites
        self.updating_radar_catalog = True
        self.radar_site.remove_all()
        active = 0
        for index, name in enumerate(sites):
            self.radar_site.append_text(name)
            if name.startswith(selected_id + " · "):
                active = index
        self.radar_site.set_active(active)
        self.updating_radar_catalog = False
        self.status.set_text(f"Loaded {len(sites)} NWS radar sites")
        if self.tabs.get_current_page() == 1:
            self.refresh()

    def load_image(self, key: str, url: str):
        self.begin_image_request(key, url)
        def fetch():
            raw, updated = data.image_record(url)
            with Image.open(io.BytesIO(raw)) as opened:
                opened.seek(0)
                picture = opened.convert("RGB")
                picture.thumbnail((960, 500), Image.Resampling.LANCZOS)
            return picture, updated
        self.submit(key, fetch, lambda result: self.show_product(key, url, result, "Source updated"))

    def begin_image_request(self, key: str, token: str):
        if self.image_requests.get(key) != token:
            self.image_targets[key].clear()
            self.image_stamps[key].set_text("Loading current source…")
        self.image_requests[key] = token

    def show_product(self, key, token, result, prefix):
        if self.image_requests.get(key) != token:
            self.refresh()
            return
        picture, valid = result
        self.images[key] = (token, picture)
        output = io.BytesIO()
        picture.save(output, format="PNG")
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(output.getvalue())
        loader.close()
        self.image_targets[key].set_from_pixbuf(loader.get_pixbuf())
        stamp = valid.strftime("%d %b %Y %H:%M UTC") if isinstance(valid, datetime) else str(valid)
        self.image_stamps[key].set_text(f"{prefix} {stamp} · {key.upper()}")

    def show_observations(self, rows):
        self.store.clear()
        self.rows = {item.station: item for item in rows}
        for item in sorted(rows, key=lambda item: (item.station != self.valid_station(), item.station)):
            self.store.append((item.station, item.name, item.observed,
                               f"{item.temp_c:.1f}" if item.temp_c is not None else "—",
                               item.wind, item.visibility, item.flight_category))
        current = self.rows.get(self.valid_station())
        if current and self.postal_location is None:
            temperature = f"{current.temp_c:.1f} °C" if current.temp_c is not None else "temperature unavailable"
            self.local_current_label.set_text(f"{current.station} · {temperature} · {current.conditions} · observed {current.observed}")

    def select_station(self, selection):
        model_store, iterator = selection.get_selected()
        if iterator is not None:
            item = self.rows.get(model_store[iterator][0])
            if item:
                self.station.set_text(item.station)
                self.set_details(f"{item.name} · {item.observed}\n\n{item.raw}")
                if item.lat is not None and item.lon is not None:
                    self.set_guidance_point(item.station, item.lat, item.lon)
                    self.set_nearest_radar(item.lat, item.lon)

    def open_selected_radar(self):
        item = self.rows.get(self.station.get_text().strip().upper())
        if item and item.lat is not None and item.lon is not None:
            self.set_nearest_radar(item.lat, item.lon)
            self.tabs.set_current_page(1)
        elif self.postal_location:
            self.set_nearest_radar(self.postal_location.lat, self.postal_location.lon)
            self.tabs.set_current_page(1)
        else:
            self.status.set_text("Load or select a station with coordinates to view nearby radar")

    def set_details(self, text):
        self.details.get_buffer().set_text(text)

    def load_station(self):
        try:
            station = data.validate_station(self.station.get_text())
        except data.DataError as exc:
            self.status.set_text(str(exc))
            return
        self.submit("station", lambda: (data.metars((station,)), data.taf(station)), self.show_station)

    def show_station(self, result):
        rows, forecast = result
        if rows:
            item = rows[0]
            if item.station not in self.rows:
                self.store.prepend((item.station, item.name, item.observed,
                                   f"{item.temp_c:.1f}" if item.temp_c is not None else "—",
                                   item.wind, item.visibility, item.flight_category))
            self.rows[item.station] = item
            saved = preferences.load()
            saved["station"] = item.station
            preferences.save(saved)
            self.saved["station"] = item.station
            if item.lat is not None and item.lon is not None:
                self.set_guidance_point(item.station, item.lat, item.lon)
                self.set_nearest_radar(item.lat, item.lon)
        self.set_details((f"{rows[0].name} · {rows[0].observed}\n\n{rows[0].raw}\n\nFORECAST\n" if rows else "No observation.\n\n") + forecast)

    def load_alerts(self):
        state = self.state.get_text().strip().upper()
        self.tabs.set_current_page(0)
        self.submit("alerts", lambda: data.alerts(state), lambda items: self.show_alerts(state, items))

    def show_alerts(self, state, items):
        self.alert_button.set_label(f"NWS {state} alerts: {len(items)}")
        self.set_details("ACTIVE NWS ALERTS\n\n" + "\n\n".join(
            f"{event}: {headline}\n{description}" for event, headline, description in items[:5]) if items
            else "No active NWS alerts returned for this state.")

    def refresh_alert_count(self):
        state = self.state.get_text().strip().upper()
        if len(state) == 2 and state.isascii() and state.isalpha():
            self.submit("alert-count", lambda: data.alerts(state),
                        lambda items: self.alert_button.set_label(f"NWS {state} alerts: {len(items)}"))
        return False

    def open_official(self):
        webbrowser.open("https://weather.gc.ca/" if self.country.get_active_text() == "CA" else "https://www.weather.gov/")

    def set_location(self):
        try:
            country, code = location.validate_postal(self.country.get_active_text(), self.postal.get_text())
        except data.DataError as exc:
            self.point_status.set_text(str(exc))
            return False
        street = self.street.get_text().strip()
        self.point_status.set_text("Resolving postal area…")
        self.submit("location", lambda: location.resolve(country, code, street), self.accept_location)
        return False

    def location_edited(self):
        if self.setting_postal:
            return
        if self.postal_location is not None:
            previous = self.postal_location
            self.postal_location = None
            self.monitor_seen.clear()
            preferences.save({"station": self.valid_station(), "country": previous.country,
                              "postal_code": previous.code, "street": previous.street,
                              "monitor_enabled": False})
            self.monitor.set_active(False)
            self.point_status.set_text("Set the new ZIP or postal code to resume local weather and alerts")

    def valid_station(self):
        try:
            return data.validate_station(self.station.get_text())
        except data.DataError:
            return self.saved.get("station", "KDTW")

    def save_preferences(self):
        preferences.save({"station": self.valid_station(),
                          "country": self.country.get_active_text(), "postal_code": self.postal.get_text(),
                          "street": self.street.get_text(), "monitor_enabled": self.monitor.get_active()})

    def accept_location(self, resolved):
        try:
            current = location.validate_postal(self.country.get_active_text(), self.postal.get_text())
        except data.DataError:
            return
        if (resolved.country, resolved.code, resolved.street) != (*current, self.street.get_text().strip()):
            return
        self.postal_location = resolved
        self.set_guidance_point(resolved.locality or resolved.code, resolved.lat, resolved.lon, resolved.country)
        self.set_nearest_radar(resolved.lat, resolved.lon)
        self.latest_local_weather = None
        self.setting_postal = True
        self.postal.set_text(resolved.code)
        self.setting_postal = False
        self.point_status.set_text(resolved.label)
        self.save_preferences()
        self.submit("local-weather", lambda: (resolved, data.nearby_metar(resolved.lat, resolved.lon)), self.show_weather)
        self.refresh_point_alerts()
        if self.open_mini_on_location:
            self.open_mini_on_location = False
            self.show_mini()

    def show_weather(self, result):
        target, observation = result
        if target != self.postal_location:
            return
        temperature = f"{observation.temp_c:.1f} °C" if observation.temp_c is not None else "Temperature unavailable"
        text = f"{temperature} · {observation.conditions}\nNearby airport {observation.station} · {observation.observed}"
        self.latest_local_weather = text
        self.point_status.set_text(text.replace("\n", " · "))
        self.local_current_label.set_text(text.replace("\n", " · "))
        if self.mini:
            self.mini_label.set_text(text)

    def show_mini(self):
        if not self.postal_location:
            self.point_status.set_text("Set a ZIP or postal code first")
            return
        if self.mini:
            self.mini.present()
            return
        self.mini = Gtk.Window(title="CAVE Portable · local weather")
        self.mini.set_default_size(340, 120)
        self.mini.set_icon_from_file(str(files("cave_portable").joinpath("assets/icon-64.png")))
        self.mini.set_transient_for(self.window)
        self.mini.connect("destroy", lambda *_args: setattr(self, "mini", None))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        self.mini.add(box)
        self.mini_label = label(self.latest_local_weather or "Loading nearby airport weather…")
        box.pack_start(self.mini_label, True, True, 0)
        box.pack_start(button("Open main view", self.window.present), False, False, 0)
        self.mini.show_all()
        if self.latest_local_weather is None:
            target = self.postal_location
            self.submit("local-weather", lambda: (target, data.nearby_metar(target.lat, target.lon)), self.show_weather)

    def toggle_monitor(self, widget):
        if widget.get_active() and not self.postal_location:
            widget.set_active(False)
            self.point_status.set_text("Set a ZIP or postal code before monitoring")
            return
        if not self.postal_location:
            return
        self.save_preferences()
        if widget.get_active():
            self.refresh_point_alerts()
        else:
            self.set_indicator_level("normal")

    def toggle_autostart(self, widget):
        if widget.get_active() and not self.postal_location:
            widget.set_active(False)
            self.point_status.set_text("Set a ZIP or postal code before enabling start at login")
            return
        try:
            preferences.set_autostart(widget.get_active())
        except OSError as exc:
            widget.set_active(not widget.get_active())
            self.status.set_text(f"Could not update login startup: {exc}")

    def refresh_point_alerts(self):
        if self.monitor.get_active() and self.postal_location:
            target = self.postal_location
            action = data.point_alerts if target.country == "US" else data.canadian_point_alerts
            self.submit("point-alerts", lambda: (target, action(target.lat, target.lon)), self.show_point_alerts)

    def show_point_alerts(self, result):
        target, alerts = result
        if target != self.postal_location or not self.monitor.get_active():
            return
        warnings = [item for item in alerts if item.level == "warning"]
        watches = [item for item in alerts if item.level == "watch"]
        self.set_indicator_level("warning" if warnings else "watch" if watches else "normal")
        self.point_status.set_text(f"{target.code} centroid · {len(warnings)} official warning(s), {len(watches)} watch(es)")
        fresh = [item for item in alerts if item.identifier not in self.monitor_seen]
        self.monitor_seen.update(item.identifier for item in alerts)
        if fresh:
            if any(item.level == "warning" for item in fresh):
                Gdk.Display.get_default().beep()
            text = "\n\n".join(f"{item.event}: {item.headline}\n{item.description[:500]}" for item in fresh[:3])
            dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                       message_type=Gtk.MessageType.WARNING if any(item.level == "warning" for item in fresh) else Gtk.MessageType.INFO,
                                       buttons=Gtk.ButtonsType.OK,
                                       text="New official weather alert near " + target.code)
            dialog.format_secondary_text(text + "\n\nCheck official local guidance.")
            dialog.run()
            dialog.destroy()

    def setup_indicator(self):
        if AyatanaAppIndicator3 is None:
            return
        try:
            base = Image.open(str(files("cave_portable").joinpath("assets/icon-64.png"))).convert("RGBA")
            self.indicator_icons = tempfile.TemporaryDirectory(prefix="cave-tray-")
            paths = {}
            for level, color in (("normal", None), ("watch", "#f5c542"), ("warning", "#da3030")):
                icon = base.copy()
                if color:
                    draw = ImageDraw.Draw(icon)
                    draw.ellipse((36, 36, 62, 62), fill=color, outline="white", width=2)
                paths[level] = f"{self.indicator_icons.name}/{level}.png"
                icon.save(paths[level])
            self.tray_paths = paths
            self.indicator = AyatanaAppIndicator3.Indicator.new(
                "cave-portable", paths["normal"], AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS)
            menu = Gtk.Menu()
            for title, action in (("Show CAVE Portable", self.window.present),
                                  ("Mini weather window", self.show_mini),
                                  ("Official warnings", self.open_official), ("Quit", self.close)):
                item = Gtk.MenuItem(label=title)
                item.connect("activate", lambda _item, callback=action: callback())
                menu.append(item)
            menu.show_all()
            self.indicator.set_menu(menu)
            self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        except Exception as exc:
            self.indicator = None
            self.status.set_text(f"System tray unavailable: {exc}")

    def set_indicator_level(self, level):
        if self.indicator:
            self.indicator.set_icon_full(self.tray_paths[level], f"CAVE Portable · {level}")

    def minimize_to_tray(self):
        if self.indicator:
            self.window.hide()
        else:
            self.status.set_text("System tray is unavailable in this desktop session")

    def periodic(self):
        if self.closed:
            return False
        self.refresh()
        self.refresh_alert_count()
        self.refresh_point_alerts()
        if self.postal_location:
            target = self.postal_location
            self.submit("local-weather", lambda: (target, data.nearby_metar(target.lat, target.lon)), self.show_weather)
        return True

    def close(self, *_args):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.indicator:
            self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.PASSIVE)
        if self.indicator_icons:
            self.indicator_icons.cleanup()
        Gtk.main_quit()


def main():
    App()
    Gtk.main()
