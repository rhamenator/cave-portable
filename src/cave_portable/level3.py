"""Bounded NEXRAD Level III digital radial decoder and local renderer.

Implements the NOAA RPG Class 1 User ICD's product header, product description
block, and packet 16 for the selected digital radial products below. No AWIPS
or third-party decoder code is included.
"""

from __future__ import annotations

import bz2
import math
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from PIL import Image, ImageDraw

from .data import DataError, _fetch
from .model import HEIGHT, WIDTH, _basemap

BUCKET = "https://unidata-nexrad-level3.s3.us-east-1.amazonaws.com/"
PRODUCTS = {
    "Digital reflectivity": ("N0B", 153, "dBZ"),
    "Digital velocity": ("N0G", 154, "m/s"),
    "Correlation coefficient (CC)": ("N0C", 161, "ρhv"),
    "Differential reflectivity (ZDR)": ("N0X", 159, "dB"),
    "Specific differential phase (KDP)": ("N0K", 163, "°/km"),
}
TILTS = (0, 1, 2, 3)
MAX_FILE = 1_500_000
MAX_BLOCK = 2_000_000
KEY = re.compile(r"^(?P<site>[A-Z0-9]{3})_(?P<product>N[0-3][BCGKUX])_(?P<time>\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})$")


def product_for_tilt(name: str, tilt: int) -> tuple[str, int, str]:
    if name not in PRODUCTS or tilt not in TILTS:
        raise DataError("Unknown NEXRAD field or elevation")
    code, number, unit = PRODUCTS[name]
    if name == "Digital velocity":
        return (f"N{tilt}G", 154, unit) if tilt < 2 else (f"N{tilt}U", 99, unit)
    return f"N{tilt}{code[-1]}", number, unit


def _product_number(product: str) -> int | None:
    for name in PRODUCTS:
        for tilt in TILTS:
            code, number, _unit = product_for_tilt(name, tilt)
            if code == product:
                return number
    return None


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _i16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">h", data, offset)[0]


def _day_keys(site: str, product: str, day: str, bucket: int) -> list[str]:
    # The bucket argument expires the small listing cache every 30 seconds.
    del bucket
    prefix = f"{site}_{product}_{day}"
    raw = _fetch(BUCKET + "?" + urlencode({"list-type": "2", "prefix": prefix,
                                           "max-keys": "1000"}), 300_000, "application/xml")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise DataError("NEXRAD product listing was invalid") from exc
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    if root.findtext("s:IsTruncated", default="false", namespaces=ns) == "true":
        raise DataError("NEXRAD product listing was truncated")
    keys = []
    for item in root.findall("s:Contents", ns):
        name = item.findtext("s:Key", namespaces=ns)
        if name and name.startswith(prefix) and KEY.fullmatch(name):
            keys.append(name)
    return sorted(keys)


_day_keys = lru_cache(maxsize=24)(_day_keys)


def recent_keys(site: str, product: str, now: datetime | None = None) -> list[str]:
    if not re.fullmatch(r"[A-Z0-9]{3}", site) or _product_number(product) is None:
        raise DataError("Unknown NEXRAD site or product")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    days = (current, current - timedelta(days=1)) if current.hour == 0 else (current,)
    keys = []
    for day in days:
        keys.extend(_day_keys(site, product, day.strftime("%Y_%m_%d"),
                              int(current.timestamp()) // 30))
    recent = []
    for key in keys:
        scan = datetime.strptime(KEY.fullmatch(key)["time"], "%Y_%m_%d_%H_%M_%S").replace(tzinfo=timezone.utc)
        if -timedelta(minutes=5) <= current - scan <= timedelta(minutes=45):
            recent.append(key)
    return sorted(set(recent), reverse=True)[:8]


@dataclass(frozen=True)
class Radial:
    start: float
    width: float
    bins: bytes


@dataclass(frozen=True)
class Field:
    site: str
    product: str
    time: datetime
    latitude: float
    longitude: float
    elevation: float
    first_bin: int
    range_scale: float
    threshold: int
    scale: float
    offset: float
    radials: tuple[Radial, ...]

    def _radial_index(self) -> list[int]:
        lookup = [-1] * 3600
        for index, radial in enumerate(self.radials):
            start = int(round(radial.start * 10))
            width = max(1, int(round(radial.width * 10)))
            for step in range(width):
                lookup[(start + step) % 3600] = index
        return lookup

    def value_at(self, latitude: float, longitude: float) -> float | None:
        dx = (longitude - self.longitude) * 111.32 * math.cos(math.radians(self.latitude))
        dy = (latitude - self.latitude) * 111.32
        angle = int(math.degrees(math.atan2(dx, dy)) * 10) % 3600
        return self._sample(dx, dy, angle, self._radial_index())

    def _sample(self, dx: float, dy: float, angle: int, lookup: list[int]) -> float | None:
        index = lookup[angle]
        if index < 0:
            return None
        bin_index = int(math.hypot(dx, dy) / (0.25 * self.range_scale)) - self.first_bin
        radial = self.radials[index]
        if bin_index < 0 or bin_index >= len(radial.bins):
            return None
        code = radial.bins[bin_index]
        if code < self.threshold:
            return None
        return self._value(code)

    def _value(self, code: int) -> float:
        if self.product[-1] in "BGU":
            return (code - 2) * self.scale + self.offset
        return (code - self.offset) / self.scale


def decode(raw: bytes, site: str, product: str) -> Field:
    """Decode only validated digital radial products; reject unknown layouts."""
    expected = _product_number(product)
    if expected is None or not re.fullmatch(r"[A-Z0-9]{3}", site) or len(raw) > MAX_FILE:
        raise DataError("Unsupported NEXRAD radial product")
    first = raw.find(b"\r\r\n")
    second = raw.find(b"\r\r\n", first + 3)
    start = second + 3
    # The WMO originator names the forecast office and can differ from the
    # radar site (for example KJAN for KDGX, or KFWD for KFWS).
    if (first < 0 or second < 0 or start + 120 > len(raw)
            or raw[first + 3:second] != f"{product}{site}".encode()):
        raise DataError("NEXRAD product header was invalid")
    try:
        code, julian, seconds, length, _source, _dest, _blocks = struct.unpack_from(">HHIIHHH", raw, start)
        pdb = start + 18
        latitude = struct.unpack_from(">i", raw, pdb + 2)[0] / 1000
        longitude = struct.unpack_from(">i", raw, pdb + 6)[0] / 1000
        product_code = _i16(raw, pdb + 12)
        elevation = _i16(raw, pdb + 40) / 10
        threshold = 2 if product[-1] in "BGU" else _u16(raw, pdb + 54)
        if product[-1] in "BGU":
            scale = _i16(raw, pdb + 44) / 10
            offset = _i16(raw, pdb + 42) / 10
        else:
            scale = struct.unpack_from(">f", raw, pdb + 42)[0]
            offset = struct.unpack_from(">f", raw, pdb + 46)[0]
        payload = raw[pdb + 102:]
        if (code != expected or product_code != expected or length != len(raw) - start
                or _i16(raw, pdb) != -1 or not (-90 <= latitude <= 90 and -180 <= longitude <= 180)
                or not (0 < scale < 1000) or not math.isfinite(offset) or not (1 <= threshold <= 255)
                or not payload.startswith(b"BZh")):
            raise ValueError("product description mismatch")
        decompressor = bz2.BZ2Decompressor()
        block = decompressor.decompress(payload, max_length=MAX_BLOCK + 1)
        if not decompressor.eof or len(block) > MAX_BLOCK:
            raise ValueError("decompressed block exceeded limit")
        divider, block_id, block_length, layers = struct.unpack_from(">hhIH", block)
        layer_divider, layer_length = struct.unpack_from(">hI", block, 10)
        packet, first_bin, count, _x, _y, range_raw, radial_count = struct.unpack_from(">HHHhhHH", block, 16)
        if (divider != -1 or block_id != 1 or block_length != len(block) or layers != 1
                or layer_divider != -1 or layer_length != len(block) - 16 or packet != 16
                or count < 1 or count > 1840 or radial_count < 1 or radial_count > 720
                or not 1 <= range_raw <= 1000):
            raise ValueError("unsupported radial packet")
        cursor = 30
        radials = []
        for _ in range(radial_count):
            byte_count, start_angle, delta_angle = struct.unpack_from(">HHH", block, cursor)
            cursor += 6
            if not count <= byte_count <= 1840 or cursor + byte_count > len(block) or not 1 <= delta_angle <= 3600:
                raise ValueError("invalid radial length or angle")
            radials.append(Radial(start_angle / 10, delta_angle / 10, block[cursor:cursor + count]))
            cursor += byte_count
        if cursor != len(block):
            raise ValueError("radial packet length mismatch")
        timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=julian - 1, seconds=seconds)
    except (ValueError, OverflowError, struct.error, OSError, EOFError) as exc:
        raise DataError("NEXRAD digital radial data was invalid or unsupported") from exc
    return Field(site, product, timestamp, latitude, longitude, elevation,
                 first_bin, range_raw / 1000, threshold, scale, offset, tuple(radials))


def fetch_field(site: str, product: str, frame: int = 0,
                now: datetime | None = None) -> Field:
    keys = recent_keys(site, product, now)
    if not keys or frame < 0 or frame >= len(keys):
        raise DataError("No recent NEXRAD scan for this site and product")
    raw = _fetch(BUCKET + quote(keys[frame]), MAX_FILE, "application/octet-stream")
    field = decode(raw, site, product)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if field.time > current + timedelta(minutes=5) or current - field.time > timedelta(minutes=30):
        raise DataError("NEXRAD scan is too old for the selected timeline")
    if frame == 0 and current - field.time > timedelta(minutes=15):
        raise DataError("Latest NEXRAD scan is stale; showing no radar data")
    return field


def fetch_field_near(site: str, product: str, scan_time: datetime,
                     now: datetime | None = None, latest: bool = False) -> Field:
    """Fetch a product from the same radar volume, never a frame-index substitute."""
    keys = recent_keys(site, product, now)
    if not keys:
        raise DataError(f"No recent {product} scans for this radar")
    candidates = sorted(keys, key=lambda key: abs(_key_time(key) - scan_time))
    key = candidates[0]
    if abs(_key_time(key) - scan_time) > timedelta(minutes=2):
        raise DataError(f"No {product} scan matches the selected reflectivity volume")
    field = decode(_fetch(BUCKET + quote(key), MAX_FILE, "application/octet-stream"), site, product)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (abs(field.time - scan_time) > timedelta(minutes=2)
            or field.time > current + timedelta(minutes=5)
            or current - field.time > timedelta(minutes=30)
            or (latest and current - field.time > timedelta(minutes=15))):
        raise DataError(f"No timely {product} scan matches the selected volume")
    return field


def _key_time(key: str) -> datetime:
    match = KEY.fullmatch(key)
    if match is None:
        raise DataError("Invalid NEXRAD object key")
    return datetime.strptime(match["time"], "%Y_%m_%d_%H_%M_%S").replace(tzinfo=timezone.utc)


def _color(product: str, value: float) -> tuple[int, int, int, int]:
    if product[-1] in "GU":
        if value < -35: return 22, 110, 50, 220
        if value < -3: return 86, 208, 169, 190
        if value < 3: return 198, 202, 204, 165
        if value < 15: return 242, 183, 88, 190
        if value < 35: return 231, 104, 61, 210
        return 180, 45, 66, 220
    if product[-1] == "C":
        if value < 0.7: return 166, 34, 179, 220
        if value < 0.85: return 226, 54, 74, 220
        if value < 0.95: return 245, 189, 55, 210
        return 67, 184, 211, 160
    if product[-1] == "B":
        if value < 5: return 64, 140, 196, 150
        if value < 25: return 52, 184, 104, 180
        if value < 45: return 238, 201, 57, 210
        if value < 60: return 235, 87, 50, 220
        return 172, 54, 179, 230
    if product[-1] == "X":
        if value < 0: return 74, 113, 208, 210
        if value < 1: return 102, 213, 162, 180
        if value < 3: return 230, 209, 65, 210
        return 231, 92, 54, 220
    if value < 0: return 65, 106, 208, 200
    if value < 1: return 88, 196, 132, 190
    if value < 3: return 233, 199, 65, 215
    return 226, 76, 62, 220


def render(field: Field, bbox: str, reflectivity: Field | None = None) -> Image.Image:
    """Sample decoded polar bins into a bounded geographic viewport."""
    west, south, east, north = (float(part) for part in bbox.split(","))
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise DataError("Invalid radar viewport")
    lookup = field._radial_index()
    mask_lookup = reflectivity._radial_index() if reflectivity else None
    cos_lat = math.cos(math.radians(field.latitude))
    columns = [((west + (x + 0.5) * (east - west) / WIDTH) - field.longitude) * 111.32 * cos_lat
               for x in range(WIDTH)]
    rgba = bytearray(WIDTH * HEIGHT * 4)
    colors = [_color(field.product, field._value(code)) if code >= field.threshold else (0, 0, 0, 0)
              for code in range(256)]
    for y in range(HEIGHT):
        latitude = north - (y + 0.5) * (north - south) / HEIGHT
        dy = (latitude - field.latitude) * 111.32
        for x, dx in enumerate(columns):
            distance = math.hypot(dx, dy)
            bin_index = int(distance / (0.25 * field.range_scale)) - field.first_bin
            if bin_index < 0:
                continue
            angle = int(math.degrees(math.atan2(dx, dy)) * 10) % 3600
            if mask_lookup is not None:
                mask_dx = dx + (field.longitude - reflectivity.longitude) * 111.32 * cos_lat
                mask_dy = dy + (field.latitude - reflectivity.latitude) * 111.32
                mask_angle = int(math.degrees(math.atan2(mask_dx, mask_dy)) * 10) % 3600
                mask_value = reflectivity._sample(mask_dx, mask_dy, mask_angle, mask_lookup)
                if mask_value is None or mask_value < 10:
                    continue
            radial_index = lookup[angle]
            if radial_index < 0:
                continue
            bins = field.radials[radial_index].bins
            if bin_index < len(bins):
                at = (y * WIDTH + x) * 4
                rgba[at:at + 4] = bytes(colors[bins[bin_index]])
    picture = _basemap(bbox).copy()
    picture.alpha_composite(Image.frombytes("RGBA", (WIDTH, HEIGHT), bytes(rgba)))
    draw = ImageDraw.Draw(picture)
    site_x = int((field.longitude - west) / (east - west) * WIDTH)
    site_y = int((north - field.latitude) / (north - south) * HEIGHT)
    if 0 <= site_x < WIDTH and 0 <= site_y < HEIGHT:
        draw.ellipse((site_x - 4, site_y - 4, site_x + 4, site_y + 4), fill="white", outline="black")
        draw.text((site_x + 7, site_y + 5), "K" + field.site, fill="black", stroke_width=2, stroke_fill="white")
    draw.rectangle((7, 7, 329, 57), fill=(15, 27, 41, 225))
    title = next(name for name in PRODUCTS if product_for_tilt(name, int(field.product[1]))[0] == field.product)
    draw.text((14, 11), f"K{field.site} {title} · {field.elevation:.1f}°", fill="white")
    draw.text((14, 32), f"Scan {field.time:%H:%M UTC} · NOAA Level III", fill="white")
    legends = {
        "velocity": ((-45, "<-35 m/s"), (-25, "-35 to -15"), (-8, "-15 to -3"),
                     (0, "near zero"), (8, "+3 to +15"), (25, "+15 to +35"), (45, ">+35")),
        "N0C": ((0.6, "<0.70"), (0.8, "0.70–0.85"), (0.9, "0.85–0.95"), (0.99, "≥0.95")),
        "N0B": ((0, "<5 dBZ"), (15, "5–25"), (35, "25–45"), (50, "45–60"), (65, "≥60")),
        "N0X": ((-1, "<0 dB"), (0.5, "0–1"), (2, "1–3"), (4, "≥3")),
        "N0K": ((-1, "<0 °/km"), (0.5, "0–1"), (2, "1–3"), (4, "≥3")),
    }
    entries = legends["velocity" if field.product[-1] in "GU" else "N0" + field.product[-1]]
    left = WIDTH - 176
    draw.rectangle((left - 7, 7, WIDTH - 7, 27 + 18 * len(entries)), fill=(15, 27, 41, 225))
    draw.text((left, 11), "Display palette", fill="white")
    for index, (value, meaning) in enumerate(entries):
        top = 29 + index * 18
        draw.rectangle((left, top, left + 14, top + 12), fill=_color(field.product, value)[:3])
        draw.text((left + 20, top), meaning, fill="white")
    return picture.convert("RGB")


def field_map(site_name: str, product_name: str, sites: dict, zoom: int = 1,
              center: tuple[float, float] | None = None, frame: int = 0,
              include_overlays: bool = True, tilt: int = 0,
              alert_point: tuple[float, float] | None = None,
              include_us_alerts: bool = True, unit_mode: str = "Hybrid"):
    from .radar import _bbox

    if site_name not in sites or product_name not in PRODUCTS:
        raise DataError("Unknown radar site or product")
    product, _code, unit = product_for_tilt(product_name, tilt)
    radar_site = sites[site_name][0]
    # A single reflectivity volume anchors the timeline for every field.
    # Product-specific frame indices can otherwise silently mix scan times.
    anchor = fetch_field(radar_site, f"N{tilt}B", frame)
    field = anchor if product == anchor.product else fetch_field_near(radar_site, product, anchor.time, latest=frame == 0)
    reflectivity = anchor if product[-1] in "CXK" else None
    bbox = _bbox(site_name, sites, zoom, center)
    image = render(field, bbox, reflectivity)
    stamp = (f"Volume {anchor.time:%d %b %Y %H:%M UTC} · "
             f"{product_name} field {field.time:%H:%M UTC} · {field.elevation:.1f}° · {unit} · NOAA Level III")
    if reflectivity:
        stamp += " · masked below 10 dBZ"
    if include_overlays:
        from . import overlays
        image, note = overlays.draw(image, bbox, alert_point or center or (field.latitude, field.longitude),
                                    include_local_alerts=include_us_alerts, scan_time=field.time,
                                    radar_point=(field.latitude, field.longitude),
                                    include_canadian_alerts=not include_us_alerts, unit_mode=unit_mode)
        stamp += " · " + note
    return image, stamp, field
