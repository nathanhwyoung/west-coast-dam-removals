#!/usr/bin/env python3
"""
Build display-only habitat geometry for the dashboard sketch.

WHY THIS EXISTS
---------------
The habitat layers in WORKING/LAYERS/ hold 86,825 features but only about
878,000 coordinate pairs: the average NMFS reach is 4.3 points long. So the
problem for a browser is the FEATURE COUNT, not the data volume. One SVG
element per feature is 86,825 DOM nodes and will not render. Merging every
feature of a species into one flat array of polylines removes the DOM problem
entirely, and the result draws to a canvas in a single pass.

WHAT IT DOES
------------
For each species, flattens every geometry into plain coordinate arrays,
rounds to 4 decimal places, and drops consecutive duplicate points created by
that rounding. Writes one .js file per species that assigns into a global, so
the sketch can lazy-load a species by injecting a <script> tag. That works
from file:// as well as over http, which plain fetch() does not.

STANDING RULE THIS OBEYS
------------------------
Display only. The source layers were already simplified at 0.0003 degrees for
display, and this adds ~11 m of rounding on top. Neither output is ever an
input to a join or a measurement. Joins and mileage read the full-resolution
source. That rule is repeated in the manifest and shown in the sketch UI.

OFF-MAP PARTS ARE DROPPED (added 2026-09-13)
--------------------------------------------
Bull trout critical habitat runs into Idaho, Montana and Nevada: 1,599 of its
3,401 rings, 56% of its points, sat wholly outside the three project states and
were redrawn on every pan and zoom frame for nothing. A part (one line or one
ring) is now dropped only if EVERY vertex is inside a non-project state in the
sketch's own outline file AND none is within BORDER_KM of CA, OR or WA.
Deliberately not a geometric clip:
  - a clip to the CA/OR/WA outlines would delete offshore habitat (green
    sturgeon's coastal marine polygons lie outside every land outline);
  - parts crossing a border stay whole, so nothing is cut down the middle;
  - the outlines are Census 1:20m, generalised by about a kilometre, so
    habitat on a border river (the Snake) could fall on the wrong side of the
    coarse line. BORDER_KM keeps it.
The count dropped is recorded per group in the manifest.

Stdlib only, matching the rest of build/.
"""

import gzip
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LAYERS = os.path.join(ROOT, "WORKING", "LAYERS")
OUT = os.path.join(ROOT, "D3", "habitat")
STATES_JS = os.path.join(ROOT, "D3", "base.js")

PROJECT_STATES = {"CA", "OR", "WA"}
BORDER_KM = 3.0

# Rounding for display. 0.0001 degrees is about 8 m of longitude and 11 m of
# latitude at 45 N, well below the 0.0003 degree simplification already applied
# upstream, so this discards nothing that was still visible.
PRECISION = 4

# Which layers make up each toggle in the sketch, in the order they should be
# listed. Grouped so that a species split across a line file and a polygon file
# (the estuary portions) arrives as one entry.
GROUPS = [
    # key,             label,                    source files
    ("coho",           "Coho salmon",            ["nmfs/coho_line.geojson"]),
    ("soncc",          "Coho, SONCC (derived)",  ["derived/soncc_coho_derived.geojson"]),
    ("chinook",        "Chinook salmon",         ["nmfs/chinook_line.geojson",
                                                  "nmfs/chinook_poly.geojson"]),
    ("steelhead",      "Steelhead",              ["nmfs/steelhead_line.geojson"]),
    ("chum",           "Chum salmon",            ["nmfs/chum_line.geojson",
                                                  "nmfs/chum_poly.geojson"]),
    ("sockeye",        "Sockeye salmon",         ["nmfs/sockeye_line.geojson",
                                                  "nmfs/sockeye_poly.geojson"]),
    ("green_sturgeon", "Green sturgeon",         ["nmfs/green_sturgeon_line.geojson",
                                                  "nmfs/green_sturgeon_poly.geojson"]),
    ("eulachon",       "Eulachon",               ["nmfs/eulachon_line.geojson"]),
    ("bull_trout",     "Bull trout",             ["usfws/bull_trout.geojson"]),
    # One group per species (Nathan, 2026-09-15: the ESA-only species are listed the same way as every
    # other species). Until then Lost River + shortnose shared "Klamath suckers" and the six ESA-only
    # species shared "Other USFWS listed fish".
    ("lost_river_sucker", "Lost River sucker",   ["usfws/lost_river_sucker.geojson"]),
    ("shortnose_sucker", "Shortnose sucker",     ["usfws/shortnose_sucker.geojson"]),
    ("warner_sucker",  "Warner sucker",          ["usfws/warner_sucker.geojson"]),
    ("santa_ana_sucker", "Santa Ana sucker",     ["usfws/santa_ana_sucker.geojson"]),
    ("tidewater_goby", "Tidewater goby",         ["usfws/tidewater_goby.geojson"]),
    ("delta_smelt",    "Delta smelt",            ["usfws/delta_smelt.geojson"]),
    ("little_kern_golden_trout", "Little Kern golden trout", ["usfws/little_kern_golden_trout.geojson"]),
    ("owens_tui_chub", "Owens tui chub",         ["usfws/owens_tui_chub.geojson"]),
]

# Which agency designated each group, for the citation line in the sketch.
AGENCY = {
    "coho": "NMFS", "chinook": "NMFS", "steelhead": "NMFS", "chum": "NMFS",
    "sockeye": "NMFS", "green_sturgeon": "NMFS", "eulachon": "NMFS",
    "soncc": "derived", "bull_trout": "USFWS",
    "lost_river_sucker": "USFWS", "shortnose_sucker": "USFWS", "warner_sucker": "USFWS",
    "santa_ana_sucker": "USFWS", "tidewater_goby": "USFWS", "delta_smelt": "USFWS",
    "little_kern_golden_trout": "USFWS", "owens_tui_chub": "USFWS",
}


def dedupe(ring):
    """Drop consecutive duplicate points left behind by rounding."""
    if not ring:
        return []
    out = [ring[0]]
    for pt in ring[1:]:
        if pt != out[-1]:
            out.append(pt)
    return out


def load_states():
    """Rings per state from the sketch's outline file, split project / other."""
    with open(STATES_JS, encoding="utf-8") as fh:
        s = fh.read()
    data = json.loads(s[s.index("{"):s.rindex("}") + 1])
    project, other = [], []
    for feat in data["features"]:
        g = feat["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = [r for poly in polys for r in poly]
        xs = [c[0] for r in rings for c in r]
        ys = [c[1] for r in rings for c in r]
        entry = (rings, (min(xs), min(ys), max(xs), max(ys)))
        (project if feat["properties"]["STUSPS"] in PROJECT_STATES else other).append(entry)
    return project, other


def inside(x, y, state):
    """Even-odd point in polygon, holes included, with a bounding box test first."""
    rings, (x0, y0, x1, y1) = state
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    hit = False
    for r in rings:
        for (ax, ay), (bx, by) in zip(r, r[1:]):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                hit = not hit
    return hit


def near(x, y, state, km):
    """True if the point is within km of the state's outline (or inside it)."""
    rings, (x0, y0, x1, y1) = state
    dlat = km / 111.0
    dlon = dlat / max(math.cos(math.radians(y)), 0.1)
    if not (x0 - dlon <= x <= x1 + dlon and y0 - dlat <= y <= y1 + dlat):
        return False
    if inside(x, y, state):
        return True
    # distance to each edge, in a local frame scaled to km
    kx = 111.0 * math.cos(math.radians(y))
    for r in rings:
        for (ax, ay), (bx, by) in zip(r, r[1:]):
            px, py = (x - ax) * kx, (y - ay) * 111.0
            ex, ey = (bx - ax) * kx, (by - ay) * 111.0
            L = ex * ex + ey * ey
            t = 0.0 if L == 0 else max(0.0, min(1.0, (px * ex + py * ey) / L))
            if (px - t * ex) ** 2 + (py - t * ey) ** 2 <= km * km:
                return True
    return False


def off_map(part, project, other):
    """Every vertex inside some non-project state and none near a project state."""
    # An empty part has no vertex anywhere, so it is not off the map; without this the loop never runs and
    # it returned True. Harmless here (flatten drops parts under 2 points first) but it made
    # make_presence_display.py report 1,120 empty lines as "off-map" on 2026-09-14.
    if not part:
        return False
    for x, y in part:
        if not any(inside(x, y, s) for s in other):
            return False
        if any(near(x, y, s, BORDER_KM) for s in project):
            return False
    return True


def flatten(path, lines, polys, states):
    """Append every geometry in one GeoJSON file to the shared arrays."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    n = PRECISION
    kept = dropped = offmap = 0

    def rd(coords):
        return dedupe([[round(x, n), round(y, n)] for x, y, *_ in coords])

    for feat in data.get("features", []):
        geom = feat.get("geometry")
        if geom is None:
            dropped += 1
            continue
        gtype, coords = geom["type"], geom["coordinates"]

        if gtype == "LineString":
            parts = [rd(coords)]
            target = lines
        elif gtype == "MultiLineString":
            parts = [rd(p) for p in coords]
            target = lines
        elif gtype == "Polygon":
            parts = [rd(r) for r in coords]
            target = polys
        elif gtype == "MultiPolygon":
            parts = [rd(r) for poly in coords for r in poly]
            target = polys
        else:
            dropped += 1
            continue

        # A line needs 2 points and a ring needs 3; rounding can collapse the
        # shortest segments below that. They are invisible at any display scale.
        floor = 3 if target is polys else 2
        for part in parts:
            if len(part) < floor:
                dropped += 1
            elif off_map(part, *states):
                offmap += 1
            else:
                target.append(part)
                kept += 1

    return kept, dropped, offmap


def main():
    os.makedirs(OUT, exist_ok=True)
    states = load_states()
    manifest = {
        "generated_by": "build/make_habitat_display.py",
        "purpose": "display only",
        "warning": "Rounded to %d dp on top of the 0.0003 degree simplification "
                   "already applied upstream. NEVER use as an input to a join or "
                   "a measurement; those read the full-resolution source."
                   % PRECISION,
        "groups": [],
    }

    total_raw = total_out = total_gz = 0
    print(f"{'group':18s} {'lines':>8s} {'rings':>7s} {'off-map':>8s} {'raw':>8s} {'out':>8s} {'gz':>8s}")
    print("-" * 71)

    for key, label, files in GROUPS:
        lines, polys = [], []
        raw = kept = dropped = offmap = 0
        sources = []
        for rel in files:
            src = os.path.join(LAYERS, rel)
            if not os.path.exists(src):
                print(f"  MISSING, skipped: {rel}")
                continue
            raw += os.path.getsize(src)
            k, d, o = flatten(src, lines, polys, states)
            kept += k
            dropped += d
            offmap += o
            sources.append(rel)

        if not sources:
            continue

        payload = {"lines": lines, "polys": polys}
        body = json.dumps(payload, separators=(",", ":"))
        js = "HABITAT[%s]=%s;\n" % (json.dumps(key), body)

        dest = os.path.join(OUT, key + ".js")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(js)

        out_b = len(js.encode())
        gz_b = len(gzip.compress(js.encode()))
        total_raw += raw
        total_out += out_b
        total_gz += gz_b

        print(f"{key:18s} {len(lines):8,} {len(polys):7,} {offmap:8,} "
              f"{raw/1e6:7.1f}M {out_b/1e6:7.1f}M {gz_b/1e6:7.1f}M")

        manifest["groups"].append({
            "key": key,
            "label": label,
            "agency": AGENCY.get(key, ""),
            "file": "habitat/%s.js" % key,
            "sources": sources,
            "lines": len(lines),
            "rings": len(polys),
            "parts_dropped_as_degenerate": dropped,
            "parts_dropped_off_map": offmap,
            "bytes": out_b,
            "bytes_gzipped": gz_b,
        })

    print("-" * 71)
    print(f"{'TOTAL':18s} {'':8s} {'':7s} {'':8s} "
          f"{total_raw/1e6:7.1f}M {total_out/1e6:7.1f}M {total_gz/1e6:7.1f}M")

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    # The sketch reads this to build its species list, so it never hardcodes one.
    index = "var HABITAT_INDEX=%s;\n" % json.dumps(
        [{k: g[k] for k in ("key", "label", "agency", "file", "lines", "rings", "bytes")}
         for g in manifest["groups"]], separators=(",", ":"))
    with open(os.path.join(OUT, "index.js"), "w", encoding="utf-8") as fh:
        fh.write(index)

    print("\nWrote %d groups to %s" % (len(manifest["groups"]), OUT))


if __name__ == "__main__":
    main()
