"""Build the natural-features data behind D3/index.html (was WORKING/DASHBOARD_SKETCH/natural_features_test.html).

Added 2026-09-14 as a test at Nathan's request (he likes the sketch's clean look but wanted
some natural features). Now the map's real natural-features layer: relief always on, range
and valley labels always on (2026-09-15), rivers removed, lakes still undecided. Renamed from
make_natural_features_test.py, with D3/natural_test/ -> D3/natural/ and WORKING/BASEMAP_TEST/
-> WORKING/BASEMAP/, on 2026-09-15. Display only; nothing here is read by the join or the audits.

Inputs (downloaded 2026-09-14 into WORKING/BASEMAP/):
  terrarium_z8/   AWS Open Data "Terrain Tiles" (Mapzen terrarium encoding), zoom 8,
                  x 38-54, y 87-104. Keyless. Sources include USGS 3DEP/NED and SRTM;
                  attribution required if ever published.
  ne_10m_*        Natural Earth 1:10m lakes, geography regions. Public domain. (The rivers downloads
                  are no longer read: rivers removed 2026-09-14, Nathan.)

Outputs (D3/natural/):
  relief.jpg      shadow-only hillshade, white = no shade, for canvas 'multiply'
  natural.js      lakes, range labels, and the relief image's placement

THE PROJECTION HAS TO MATCH D3 EXACTLY. The sketch uses
  d3.geoAlbers().rotate([120, 0]).center([0, 41.5]).parallels([34, 48])
which is a SPHERICAL Albers with origin (-120, 41.5). PROJ's
  +proj=aea +lat_1=34 +lat_2=48 +lat_0=41.5 +lon_0=-120 +R=<R>
uses the same formulas on a sphere of radius R, so a D3 screen position is exactly
  x = tx + k * X / R,   y = ty - k * Y / R
for PROJ metres (X, Y), D3 scale k and translate (tx, ty). The page uses that to place
the image. An ellipsoidal Albers (EPSG:5070 and friends) would NOT line up.
"""

import json
import math
import subprocess
from pathlib import Path

import sys

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_habitat_display import STATES_JS, load_states, inside  # noqa: E402  same outlines, same test

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "WORKING/BASEMAP"
OUT = ROOT / "D3/natural"
R = 6371008.8
AEA = f"+proj=aea +lat_1=34 +lat_2=48 +lat_0=41.5 +lon_0=-120 +x_0=0 +y_0=0 +R={R} +units=m +no_defs"
# Since 2026-09-14 (Nathan: the six neighbouring states become flat outlines, no relief, lakes or labels)
# everything here covers ONLY CA, OR and WA. It was (-126.0, 31.0, -104.0, 49.5), all nine states.
PROJECT = load_states()[0]
BBOX = (min(b[0] for _, b in PROJECT) - 0.2, min(b[1] for _, b in PROJECT) - 0.2,
        max(b[2] for _, b in PROJECT) + 0.2, max(b[3] for _, b in PROJECT) + 0.2)
RELIEF_M = 500                            # output pixel size, metres
WEB = 20037508.342789244


def run(*args):
    subprocess.run([str(a) for a in args], check=True, capture_output=True)


def build_relief():
    z, x0, x1, y0, y1 = map(int, (SRC / "terrarium_z8/range.txt").read_text().split())
    w, h = (x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256
    dem = np.zeros((h, w), dtype=np.float32)
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            rgb = np.asarray(Image.open(SRC / f"terrarium_z8/{x}_{y}.png").convert("RGB"), dtype=np.float32)
            elev = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768   # terrarium decoding
            dem[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = elev
    work = SRC / "work"
    work.mkdir(exist_ok=True)
    dem.tofile(work / "dem_3857.bin")
    res = 2 * WEB / (256 * 2 ** z)
    ox, oy = -WEB + x0 * 256 * res, WEB - y0 * 256 * res
    (work / "dem_3857.vrt").write_text(f"""<VRTDataset rasterXSize="{w}" rasterYSize="{h}">
  <SRS>EPSG:3857</SRS>
  <GeoTransform>{ox}, {res}, 0, {oy}, 0, {-res}</GeoTransform>
  <VRTRasterBand dataType="Float32" band="1" subClass="VRTRawRasterBand">
    <SourceFilename relativeToVRT="1">dem_3857.bin</SourceFilename>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
</VRTDataset>
""")
    run("gdalwarp", "-overwrite", "-q", "-t_srs", AEA, "-tr", RELIEF_M, RELIEF_M, "-r", "bilinear",
        "-te_srs", "EPSG:4326", "-te", *BBOX, "-dstnodata", "-32768",
        work / "dem_3857.vrt", work / "dem_aea.tif")
    # Vertical exaggeration 3 because each pixel is 500 m; standard NW sun at 45 degrees.
    run("gdaldem", "hillshade", "-q", "-z", "3", "-az", "315", "-alt", "45", "-compute_edges",
        work / "dem_aea.tif", work / "hs_aea.tif")
    run("gdal_translate", "-q", "-of", "PNG", work / "hs_aea.tif", work / "hs_aea.png")
    info = json.loads(subprocess.run(["gdalinfo", "-json", str(work / "dem_aea.tif")],
                                     check=True, capture_output=True, text=True).stdout)
    gt = info["geoTransform"]
    width, height = info["size"]

    hs = np.asarray(Image.open(work / "hs_aea.png"), dtype=np.float32)
    if hs.ndim == 3:
        hs = hs[..., 0]
    flat = 255 * math.sin(math.radians(45))          # value gdaldem gives level ground
    shadow = np.clip((flat - hs) / flat, 0, 1) ** 0.8  # keep shadows only, soften the curve
    out = (255 * (1 - shadow)).astype(np.uint8)
    out[hs == 0] = 255                                 # nodata edges draw as no shade
    # Blank (no shade) outside CA/OR/WA, grown by 3 px (1.5 km) so the page's clip at the drawn border,
    # not this raster's edge, is what the eye sees. The page clips to the same outlines.
    mask = project_mask(work, width, height, gt)
    out[mask == 0] = 255
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, mode="L").save(OUT / "relief.jpg", quality=82, optimize=True)
    return {"file": "natural/relief.jpg", "originX": gt[0], "originY": gt[3],
            "pixel": gt[1], "width": width, "height": height, "R": R}


def project_mask(work, width, height, gt):
    s = Path(STATES_JS).read_text()
    gj = json.loads(s[s.index("{"):s.rindex("}") + 1])
    gj["features"] = [f for f in gj["features"] if f["properties"]["STUSPS"] in ("CA", "OR", "WA")]
    (work / "project_states.geojson").write_text(json.dumps(gj))
    (work / "project_states_aea.geojson").unlink(missing_ok=True)   # the GeoJSON driver cannot overwrite
    run("ogr2ogr", "-t_srs", AEA, work / "project_states_aea.geojson", work / "project_states.geojson")
    x0, y0 = gt[0], gt[3]
    run("gdal_rasterize", "-q", "-burn", "255", "-init", "0", "-ot", "Byte", "-te", x0, y0 + height * gt[5],
        x0 + width * gt[1], y0, "-ts", width, height, work / "project_states_aea.geojson", work / "project_mask.tif")
    run("gdal_translate", "-q", "-of", "PNG", work / "project_mask.tif", work / "project_mask.png")
    return np.asarray(Image.open(work / "project_mask.png").filter(ImageFilter.MaxFilter(7)))


def ogr_json(path, *extra):
    r = subprocess.run(["ogr2ogr", "-f", "GeoJSON", "/vsistdout/", str(path), "-spat", *map(str, BBOX),
                        "-lco", "COORDINATE_PRECISION=4", *extra], check=True, capture_output=True, text=True)
    return json.loads(r.stdout)["features"]


def parts(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        return [c]
    if t in ("MultiLineString", "Polygon"):
        return c
    if t == "MultiPolygon":
        return [ring for poly in c for ring in poly]
    return []


def build_vectors():
    lakes, labels = [], []
    for name in ("ne_10m_lakes", "ne_10m_lakes_north_america"):
        for f in ogr_json(SRC / name / f"{name}.shp"):
            if f["geometry"]:
                lakes += parts(f["geometry"])
    polys = SRC / "ne_10m_geography_regions_polys/ne_10m_geography_regions_polys.shp"
    sql = ("SELECT NAME, FEATURECLA, SCALERANK, ST_X(ST_PointOnSurface(geometry)) AS x, "
           "ST_Y(ST_PointOnSurface(geometry)) AS y FROM ne_10m_geography_regions_polys "
           "WHERE FEATURECLA IN ('Range/mtn', 'Valley', 'Basin', 'Plateau')")
    r = subprocess.run(["ogr2ogr", "-f", "CSV", "/vsistdout/", str(polys), "-dialect", "SQLite", "-sql", sql],
                       check=True, capture_output=True, text=True)
    for line in r.stdout.splitlines()[1:]:
        name, cla, rank, x, y = line.rsplit(",", 4)
        x, y = float(x), float(y)
        # Only labels whose point falls inside CA, OR or WA (was a lon/lat box, which let in Great Basin,
        # Bitterroot, Salmon River Mts. and Rocky Mountains).
        if any(inside(x, y, st) for st in PROJECT):
            labels.append({"name": name.strip('"').upper(), "kind": cla, "rank": int(float(rank)),
                           "lon": round(x, 3), "lat": round(y, 3)})
    return {"lakes": lakes, "labels": labels}


def main():
    relief = build_relief()
    vec = build_vectors()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "natural.js").write_text(
        "// generated by build/make_natural_features.py, do not edit.\n"
        f"const NATURAL = {json.dumps({'relief': relief, **vec}, separators=(',', ':'))};\n")
    kb = lambda p: (OUT / p).stat().st_size / 1024
    print(f"relief.jpg {relief['width']}x{relief['height']} px at {RELIEF_M} m, {kb('relief.jpg'):.0f} KB")
    print(f"natural.js {kb('natural.js'):.0f} KB: {len(vec['lakes'])} lake rings, "
          f"{len(vec['labels'])} labels: {', '.join(l['name'] for l in vec['labels'])}")


if __name__ == "__main__":
    main()
