"""Location -> map data for generated levels (downloaded once, cached in the work folder).

Location forms: a full plus code ("9C6WQCGF+QP"), a short plus code with a place ("QCGF+QP Durham"), or
"lat, lon". Services (free, no key): Nominatim (place names), Overpass (OpenStreetMap features), OpenTopoData
(elevation: EU-DEM 25 m in Europe, SRTM 30 m elsewhere). Map data (c) OpenStreetMap contributors (ODbL).
"""
import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "thaw-super-dx/0.1 (level generator)"}
OLC = "23456789CFGHJMPQRVWX"
N_ELEV = 13


OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter")


def _get(url, data=None, timeout=90, tries=3):
    """GET/POST JSON with retries (busy public servers answer 429/502/504 now and then)."""
    urls = [url] if not isinstance(url, (list, tuple)) else list(url)
    err = None
    for attempt in range(tries):
        for u in urls:
            try:
                req = urllib.request.Request(u, data=data, headers=UA)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.load(r)
            except Exception as e:  # network error, HTTP 429/5xx, bad JSON
                err = e
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download failed ({err}); check the internet connection or try again later")


def _olc_decode(code):
    """Full plus code -> centre (lat, lon)."""
    c = code.upper().replace("+", "").rstrip("0")
    lat = lon = 0.0
    res = 20.0
    for i in range(0, min(len(c), 10), 2):
        lat += OLC.index(c[i]) * res
        lon += OLC.index(c[i + 1]) * res
        if i + 2 < min(len(c), 10):
            res /= 20
    return lat - 90 + res / 2, lon - 180 + res / 2


def _olc_prefix(lat, lon):
    lat, lon = lat + 90, lon + 180
    out, res = "", 20.0
    for _ in range(4):
        a, b = int(lat // res), int(lon // res)
        out += OLC[a] + OLC[b]
        lat -= a * res
        lon -= b * res
        res /= 20
    return out


def encode(lat, lon):
    """Full 10-digit plus code for a point."""
    lat, lon = min(max(lat + 90, 0), 179.999999), (lon + 180) % 360
    out, res = "", 20.0
    for i in range(5):
        a, b = int(lat // res), int(lon // res)
        out += OLC[a] + OLC[b]
        lat -= a * res
        lon -= b * res
        res /= 20
        if i == 3:
            out += "+"
    return out


def candidates(location):
    """[(label, lat, lon)]: one for a full code or 'lat, lon'; for a short code, one per distinct place match."""
    s = location.strip()
    m = re.match(r"([23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{2,3})\s*,?\s*(.*)$", s, re.I)
    if not m or m.group(1).index("+") == 8 or not m.group(2).strip():
        lat, lon = resolve(s)
        return [(s, lat, lon)]
    code, place = m.group(1).upper(), m.group(2).strip()
    r = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": place, "format": "json",
                                                                                     "limit": 8}))
    out = []
    for x in r:
        rlat, rlon = float(x["lat"]), float(x["lon"])
        lat, lon = _olc_decode(_olc_prefix(rlat, rlon)[:8 - code.index("+")] + code)
        if all(math.hypot(lat - a, (lon - b) * math.cos(math.radians(lat))) > 0.2 for _, a, b in out):
            out.append((x["display_name"], lat, lon))
    if not out:
        raise ValueError(f"place not found: {place}")
    return out


def geocode(place):
    r = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": place, "format": "json",
                                                                                     "limit": 1}))
    if not r:
        raise ValueError(f"place not found: {place}")
    return float(r[0]["lat"]), float(r[0]["lon"])


def resolve(location):
    """-> (lat, lon) for a plus code (full, or short + place) or 'lat, lon'."""
    s = location.strip()
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"([23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{2,3})\s*,?\s*(.*)$", s, re.I)
    if not m:
        raise ValueError("enter a plus code (e.g. 9C6WQCGF+QP or QCGF+QP Durham) or 'lat, lon'")
    code, place = m.group(1).upper(), m.group(2).strip()
    if code.index("+") == 8:
        return _olc_decode(code)
    if not place:
        raise ValueError("a short plus code needs a town after it (e.g. QCGF+QP Durham)")
    rlat, rlon = geocode(place)
    full = _olc_prefix(rlat, rlon)[:8 - code.index("+")] + code
    return _olc_decode(full)


def fetch(lat, lon, radius, cache_dir, log=print):
    """-> (osm json, elevation samples) for the square of half size radius (m) around lat, lon."""
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(f"{lat:.6f},{lon:.6f},{radius:.0f}".encode()).hexdigest()[:12]
    po, pe = os.path.join(cache_dir, f"osm_{key}.json"), os.path.join(cache_dir, f"elev_{key}.json")
    if not os.path.exists(po):
        log("downloading OpenStreetMap data ...")
        d = radius * 1.45  # covers the square's corners
        q = (f"[out:json][timeout:90];(way(around:{d:.0f},{lat},{lon});"
             f"node(around:{d:.0f},{lat},{lon})[~\".\"~\".\"];);out body geom;")
        osm = _get(OVERPASS, urllib.parse.urlencode({"data": q}).encode(), 180)
        json.dump(osm, open(po, "w"))
    if not os.path.exists(pe):
        log("downloading elevation ...")
        pts = []
        for i in range(N_ELEV):
            for j in range(N_ELEV):
                dy, dx = -radius + 2 * radius * i / (N_ELEV - 1), -radius + 2 * radius * j / (N_ELEV - 1)
                pts.append((lat + dy / 111320, lon + dx / (111320 * math.cos(math.radians(lat)))))
        out = []
        for k in range(0, len(pts), 100):
            loc = "|".join(f"{a:.6f},{b:.6f}" for a, b in pts[k:k + 100])
            out += _get(f"https://api.opentopodata.org/v1/eudem25m,srtm30m?locations={loc}")["results"]
            time.sleep(1.1)
        json.dump(out, open(pe, "w"))
    return json.load(open(po)), json.load(open(pe))
