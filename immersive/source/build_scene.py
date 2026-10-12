#!/usr/bin/env python3
"""
Builds immersive/source/index.html from the cited data.

    python immersive/source/build_scene.py

Reads   data/earthquakes_indonesia_2016_2025_original.xlsx   (USGS ComCat, M5+, 2016-2025)
        data/ne_50m_land.geojson                             (Natural Earth 1:50m land, public domain)
        immersive/source/scene.template.html
Writes  immersive/source/index.html

Every mark in the scene is computed here from the USGS rows. Nothing is typed in by hand.
"""
import json
import math
import os
import re
import statistics

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XLSX = os.path.join(ROOT, "data", "earthquakes_indonesia_2016_2025_original.xlsx")
LAND = os.path.join(ROOT, "data", "ne_50m_land.geojson")
TEMPLATE = os.path.join(HERE, "scene.template.html")
OUT = os.path.join(HERE, "index.html")

# The bounding box of the USGS query.
LON0, LON1, LAT0, LAT1 = 95.0, 141.0, -11.0, 6.0

# Q5: what counts as "nearby" and "the next month".
NEAR_KM = 100.0        # the same radius as panel 5 of the 2D dashboard
WINDOW_DAYS = 30


def depth_class(depth_km):
    """s = shallow (0-70 km), i = intermediate (70-300 km), d = deep (over 300 km)."""
    if depth_km <= 70:
        return "s"
    if depth_km <= 300:
        return "i"
    return "d"


# Regions, tested in this order. Boxes in degrees; a quake belongs to the first rule it meets.
REGIONS = [
    ("sum", "Sumatra"),
    ("phi", "Philippines"),
    ("pap", "Papua"),
    ("jnt", "Java-Nusa Tenggara"),
    ("mal", "Maluku-Banda Sea"),
    ("sul", "Sulawesi"),
]
REGION_NAME = dict(REGIONS)


def region(lon, lat):
    if lon < 106.5:
        return "sum"
    if lat > 3.5 and lon >= 117:
        return "phi"
    if lon >= 132:
        return "pap"
    if lat <= -5.5 and lon < 126:
        return "jnt"
    if lon >= 124:
        return "mal"
    return "sul"            # 106.5-124 E, 5.5 S-3.5 N: Sulawesi, with Kalimantan (almost no quakes)


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def short_place(place):
    """'72 km N of Palu, Indonesia' -> 'Palu'; 'Banda Sea' -> 'Banda Sea'."""
    name = place.split(" of ", 1)[1] if " of " in place else place
    name = name.split(",")[0].strip()
    return re.sub(r"^Pulau Pulau ", "", name)


def coastline():
    """Natural Earth land rings, cut to the query box, as runs of [lon, lat]."""
    pad = 0.5
    runs = []
    for feat in json.load(open(LAND, encoding="utf-8"))["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for ring in poly:
                run = []
                for lon, lat in ring:
                    inside = LON0 - pad <= lon <= LON1 + pad and LAT0 - pad <= lat <= LAT1 + pad
                    if inside:
                        lon_c = min(max(lon, LON0), LON1)
                        lat_c = min(max(lat, LAT0), LAT1)
                        run.append([round(lon_c, 2), round(lat_c, 2)])
                    elif run:
                        if len(run) > 1:
                            runs.append(run)
                        run = []
                if len(run) > 1:
                    runs.append(run)
    return runs


def land_polygons():
    """Natural Earth land rings clipped to the query box (Sutherland-Hodgman), as closed rings of [lon, lat]."""
    edges = [
        (lambda p: p[0] >= LON0, lambda a, b: [LON0, a[1] + (b[1] - a[1]) * (LON0 - a[0]) / (b[0] - a[0])]),
        (lambda p: p[0] <= LON1, lambda a, b: [LON1, a[1] + (b[1] - a[1]) * (LON1 - a[0]) / (b[0] - a[0])]),
        (lambda p: p[1] >= LAT0, lambda a, b: [a[0] + (b[0] - a[0]) * (LAT0 - a[1]) / (b[1] - a[1]), LAT0]),
        (lambda p: p[1] <= LAT1, lambda a, b: [a[0] + (b[0] - a[0]) * (LAT1 - a[1]) / (b[1] - a[1]), LAT1]),
    ]
    out = []
    for feat in json.load(open(LAND, encoding="utf-8"))["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            ring = [list(p) for p in poly[0]]          # outer ring only
            if not any(LON0 <= x <= LON1 and LAT0 <= y <= LAT1 for x, y in ring):
                continue
            for inside, cross in edges:
                nxt = []
                for i, cur in enumerate(ring):
                    prev = ring[i - 1]
                    if inside(cur):
                        if not inside(prev):
                            nxt.append(cross(prev, cur))
                        nxt.append(cur)
                    elif inside(prev):
                        nxt.append(cross(prev, cur))
                ring = nxt
                if not ring:
                    break
            pts = []
            for x, y in ring:
                q = [round(x, 2), round(y, 2)]
                if not pts or pts[-1] != q:
                    pts.append(q)
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) >= 3:
                out.append(pts)
    return out


def main():
    df = pd.read_excel(XLSX, sheet_name=0)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    df["year"] = df["time"].dt.year
    df["cls"] = df["depth"].map(depth_class)

    df["region"] = [region(lo, la) for lo, la in zip(df["longitude"], df["latitude"])]
    all_years = sorted(int(y) for y in df["year"].unique())
    regions = []
    for key, name in REGIONS:
        sub = df[df["region"] == key]
        by_year = sub["year"].value_counts()
        regions.append({
            "key": key, "name": name, "total": int(len(sub)),
            "s": int((sub["cls"] == "s").sum()), "i": int((sub["cls"] == "i").sum()), "d": int((sub["cls"] == "d").sum()),
            "lon": round(float(sub["longitude"].median()), 2), "lat": round(float(sub["latitude"].median()), 2),
            "years": [int(by_year.get(y, 0)) for y in all_years],
        })
    regions.sort(key=lambda r: -r["total"])

    quakes = [[round(r.longitude, 3), round(r.latitude, 3), round(r.depth, 1), round(r.mag, 1), int(r.year)]
              for r in df.itertuples()]

    years = {int(y): int(n) for y, n in df["year"].value_counts().sort_index().items()}

    m7 = []
    window = pd.Timedelta(days=WINDOW_DAYS)
    for r in df[df["mag"] >= 7.0].itertuples():
        dist = df.apply(lambda q: haversine_km(r.latitude, r.longitude, q.latitude, q.longitude), axis=1)
        near = dist <= NEAR_KM
        after = int((near & (df["time"] > r.time) & (df["time"] <= r.time + window)).sum())
        before = int((near & (df["time"] < r.time) & (df["time"] >= r.time - window)).sum())
        m7.append({
            "name": short_place(r.place), "year": int(r.year), "mag": round(r.mag, 1),
            "depth": round(r.depth), "lon": round(r.longitude, 3), "lat": round(r.latitude, 3),
            "cls": r.cls, "after": after, "before": before,
        })
    m7.sort(key=lambda e: e["depth"])

    groups = {}
    for c in "sid":
        rows = [e for e in m7 if e["cls"] == c]
        groups[c] = {
            "n": len(rows),
            "median_after": statistics.median(e["after"] for e in rows) if rows else 0,
            "median_before": statistics.median(e["before"] for e in rows) if rows else 0,
        }

    data = {
        "n": len(df),
        "box": [LON0, LON1, LAT0, LAT1],
        "near_km": NEAR_KM,
        "window_days": WINDOW_DAYS,
        "class_counts": {c: int((df["cls"] == c).sum()) for c in "sid"},
        "quakes": quakes,
        "years": years,
        "year_list": all_years,
        "regions": regions,
        "m7": m7,
        "groups": groups,
        "coast": coastline(),
        "land": land_polygons(),
        "deep_lon": [round(float(df.loc[df["cls"] == "d", "longitude"].min()), 1),
                     round(float(df.loc[df["cls"] == "d", "longitude"].max()), 1)],
    }

    html = open(TEMPLATE, encoding="utf-8").read()
    html = html.replace("__DATA_JSON__", json.dumps(data, separators=(",", ":")))
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)

    print("rows:", data["n"], "| classes:", data["class_counts"], "| years:", years)
    for r in regions:
        print("  %-20s total %4d  s %4d  i %3d  d %3d  at %.1fE %.1fN  years %s" %
              (r["name"], r["total"], r["s"], r["i"], r["d"], r["lon"], r["lat"], r["years"]))
    print("  in the Sulawesi box but west of 117.5E (Kalimantan):",
          int(((df["region"] == "sul") & (df["longitude"] < 117.5)).sum()))
    print("coast runs:", len(data["coast"]), "| points:", sum(len(r) for r in data["coast"]))
    for e in m7:
        print("  M%.1f %-22s %d  depth %3d km  after %2d  before %2d" %
              (e["mag"], e["name"], e["year"], e["depth"], e["after"], e["before"]))
    print("groups:", groups)
    print("wrote", OUT, "(%d KB)" % (os.path.getsize(OUT) // 1024))


if __name__ == "__main__":
    main()
