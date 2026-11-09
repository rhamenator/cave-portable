"""Native Wayland desktop view for Linux. Weather operations stay off the UI thread."""

from __future__ import annotations

import io
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib.resources import files

import gi
from PIL import Image

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from . import __version__, data, location, model, preferences, radar


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
        self.saved = preferences.load()
        self.open_mini_on_location = bool(self.saved.get("monitor_enabled"))

        self.window = Gtk.Window(title=f"CAVE Portable {__version__}")
        self.window.set_default_size(1000, 680)
        self.window.set_size_request(860, 550)
        self.window.set_icon_from_file(str(files("cave_portable").joinpath("assets/icon-64.png")))
        self.window.connect("destroy", self.close)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_border_width(12)
        self.window.add(outer)

        header = row(Gtk.Image.new_from_file(str(files("cave_portable").joinpath("assets/icon-32.png"))),
                     label("CAVE PORTABLE · NOAA / NWS / SPC"))
        header.pack_end(button("Refresh", self.refresh), False, False, 0)
        header.pack_end(button("Official warnings", self.open_official), False, False, 0)
        self.alert_button = button("NWS alerts", self.load_alerts)
        header.pack_end(self.alert_button, False, False, 0)
        outer.pack_start(header, False, False, 0)

        self.tabs = Gtk.Notebook()
        outer.pack_start(self.tabs, True, True, 0)
        self.observations_ui()
        self.image_ui("radar", "Radar", "NOAA/NWS national radar and current single-site products")
        self.image_ui("satellite", "Satellite", "NOAA/NESDIS GOES GeoColor")
        self.image_ui("severe", "Severe outlook & CAPE", "SPC categorical outlooks and Southern Plains MLCAPE")
        self.image_ui("model", "Forecast CAPE", "GFS surface-based CAPE · NSF Unidata THREDDS / USGS map")
        self.tabs.connect("switch-page", lambda *_args: GLib.idle_add(self.refresh))

        self.status = label("Ready · For urgent decisions, use official warnings and local instructions")
        outer.pack_start(self.status, False, False, 0)
        self.window.show_all()
        GLib.timeout_add(200, self.refresh)
        GLib.timeout_add(500, self.refresh_alert_count)
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
                            label("US state alerts:"), self.state, button("Load alerts", self.load_alerts)), False, False, 0)
        self.monitor = Gtk.CheckButton(label="Monitor official warnings at postal area")
        self.monitor.set_active(bool(self.saved.get("monitor_enabled") and self.saved.get("postal_code")))
        self.monitor.connect("toggled", self.toggle_monitor)
        self.autostart = Gtk.CheckButton(label="Start at login")
        self.autostart.set_active(preferences.is_autostart_enabled())
        self.autostart.connect("toggled", self.toggle_autostart)
        page.pack_start(row(self.monitor, button("Mini weather window", self.show_mini), self.autostart), False, False, 0)
        self.point_status = label("Set a ZIP or postal code for local weather and alerts")
        page.pack_start(self.point_status, False, False, 0)

        self.store = Gtk.ListStore(str, str, str, str, str, str, str)
        self.table = Gtk.TreeView(model=self.store)
        for idx, title in enumerate(("ICAO", "Location", "Observed", "°C", "Wind", "Vis. mi", "Flight")):
            column = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=idx)
            column.set_resizable(True)
            column.set_min_width(45)
            self.table.append_column(column)
        self.table.get_selection().connect("changed", self.select_station)
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
        image = Gtk.Image()
        image.set_size_request(700, 350)
        self.image_targets[key] = image
        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        viewport.add_with_viewport(image)
        page.pack_start(viewport, True, True, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.pack_start(controls, False, False, 0)
        if key == "radar":
            self.radar_product = choice(("National reflectivity", *radar.PRODUCTS), "National reflectivity", self.refresh)
            self.radar_site = choice(tuple(radar.SITES), "DTX · Detroit", self.refresh)
            controls.pack_start(self.radar_product, False, False, 0)
            controls.pack_start(self.radar_site, False, False, 0)
        elif key == "satellite":
            self.satellite_choice = choice(tuple(data.SATELLITE), "GOES East", self.refresh)
            controls.pack_start(self.satellite_choice, False, False, 0)
        elif key == "severe":
            self.severe_choice = choice((*data.OUTLOOK, "Southern Plains MLCAPE"), "Day 1", self.refresh)
            controls.pack_start(self.severe_choice, False, False, 0)
            controls.pack_start(label("CAPE is instability, not a standalone severe forecast."), False, False, 0)
        else:
            controls.pack_start(label("Hours after next 3-hour UTC slot:"), False, False, 0)
            self.model_hour = choice(tuple(str(hour) for hour in model.HOURS), "24", self.refresh)
            controls.pack_start(self.model_hour, False, False, 0)
        stamp = label("Source time pending. Images show source-provided valid times and legends when present.")
        page.pack_start(stamp, False, False, 0)
        self.image_stamps[key] = stamp

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
        return False

    def refresh(self):
        tab = self.tabs.get_current_page()
        if tab == 0:
            self.submit("observations", data.metars, self.show_observations)
        elif tab == 1:
            product = self.radar_product.get_active_text()
            if product == "National reflectivity":
                self.load_image("radar", data.RADAR_URL)
            else:
                site = self.radar_site.get_active_text()
                token = f"{site}:{product}"
                self.image_requests["radar"] = token
                self.submit("site-radar", lambda: radar.site_map(site, product),
                            lambda result: self.show_product("radar", token, result, "Iowa Environmental Mesonet radar scan"))
        elif tab == 2:
            self.load_image("satellite", data.SATELLITE[self.satellite_choice.get_active_text()])
        elif tab == 3:
            selected = self.severe_choice.get_active_text()
            self.load_image("severe", data.MLCAPE_URL if selected == "Southern Plains MLCAPE" else data.OUTLOOK[selected])
        elif tab == 4:
            hours = int(self.model_hour.get_active_text())
            token = f"GFS:{hours}"
            self.image_requests["model"] = token
            self.submit("model", lambda: model.cape_map(hours),
                        lambda result: self.show_product("model", token, result, "GFS forecast valid"))
        return False

    def load_image(self, key: str, url: str):
        self.image_requests[key] = url
        def fetch():
            raw, updated = data.image_record(url)
            with Image.open(io.BytesIO(raw)) as opened:
                opened.seek(0)
                picture = opened.convert("RGB")
                picture.thumbnail((960, 500), Image.Resampling.LANCZOS)
            return picture, updated
        self.submit(key, fetch, lambda result: self.show_product(key, url, result, "Source updated"))

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
        for item in rows:
            self.store.append((item.station, item.name, item.observed,
                               f"{item.temp_c:.1f}" if item.temp_c is not None else "—",
                               item.wind, item.visibility, item.flight_category))

    def select_station(self, selection):
        model_store, iterator = selection.get_selected()
        if iterator is not None:
            item = self.rows.get(model_store[iterator][0])
            if item:
                self.station.set_text(item.station)
                self.set_details(f"{item.name} · {item.observed}\n\n{item.raw}")

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
        self.setting_postal = True
        self.postal.set_text(resolved.code)
        self.setting_postal = False
        self.point_status.set_text(resolved.label)
        self.save_preferences()
        self.submit("local-weather", lambda: data.nearby_metar(resolved.lat, resolved.lon), self.show_weather)
        self.refresh_point_alerts()
        if self.open_mini_on_location:
            self.open_mini_on_location = False
            self.show_mini()

    def show_weather(self, observation):
        temperature = f"{observation.temp_c:.1f} °C" if observation.temp_c is not None else "Temperature unavailable"
        text = f"{temperature} · {observation.conditions}\nNearby airport {observation.station} · {observation.observed}"
        self.point_status.set_text(text.replace("\n", " · "))
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
        self.mini_label = label("Loading nearby airport weather…")
        box.pack_start(self.mini_label, True, True, 0)
        box.pack_start(button("Open main view", self.window.present), False, False, 0)
        self.mini.show_all()

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
        self.point_status.set_text(f"{target.code} centroid · {len(alerts)} official warning(s)")
        fresh = [item for item in alerts if item.identifier not in self.monitor_seen]
        self.monitor_seen.update(item.identifier for item in alerts)
        if fresh:
            Gdk.Display.get_default().beep()
            text = "\n\n".join(f"{item.event}: {item.headline}\n{item.description[:500]}" for item in fresh[:3])
            dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                       message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK,
                                       text="New official weather warning near " + target.code)
            dialog.format_secondary_text(text + "\n\nCheck official local guidance immediately.")
            dialog.run()
            dialog.destroy()

    def periodic(self):
        if self.closed:
            return False
        self.refresh()
        self.refresh_alert_count()
        self.refresh_point_alerts()
        if self.postal_location:
            target = self.postal_location
            self.submit("local-weather", lambda: data.nearby_metar(target.lat, target.lon), self.show_weather)
        return True

    def close(self, *_args):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()


def main():
    App()
    Gtk.main()
