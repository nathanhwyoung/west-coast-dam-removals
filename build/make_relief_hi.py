"""Build the sharp shaded-relief tiles for D3/index.html: CA, OR and WA at 115 m.

Added 2026-09-14 (Nathan: "can we sharpen all of the shaded relief now?"), after the Klamath test
patch (09-14_WORKING s18a; its script and files deleted once this build replaced it) showed a zoom 10 level is clearly sharper and
small enough to ship. The 500 m image (make_natural_features.py) stays for the far view; the
page swaps in these tiles, for the part of the map on screen, once that image would be upsampled.

Steps:
  1. Download every zoom 10 AWS Terrain Tile (terrarium) touching CA/OR/WA, about 1,131 tiles and
     65 MB, with curl (Python's certificate store is broken on this machine), into
     WORKING/BASEMAP/terrarium_z10/. Tiles already on disk are not fetched again.
  2. Mosaic into one Web Mercator grid ON DISK (memmap). Tiles not downloaded are NODATA, not zero,
     so no false cliff is shaded at the edge of the data.
  3. Warp to the sketch's SPHERICAL Albers at 115 m, hillshade ONCE over the whole area (so tile
     edges carry no seams), same sun and shadow-only curve as the 500 m relief, vertical
     exaggeration 2 (calibrated on the Klamath test against the 500 m image).
  4. Blank everything outside CA/OR/WA (outlines rasterised all-touched, so the page's clip at the
     drawn border is the visible edge), cut into 512 px tiles, skip tiles with no shade at all.

Outputs: D3/natural/relief_hi/{col}_{row}.jpg and D3/natural/relief_hi.js (grid
placement and the tile list). The large intermediates in WORKING/BASEMAP/work_hi/ (about
1.2 GB) are deleted at the end; the downloads are kept so a rebuild needs no network.
"""

import json
import math
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_habitat_display import STATES_JS, load_states  # noqa: E402  same outlines as everything else

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "WORKING/BASEMAP"
TILES = SRC / "terrarium_z10"
WORK = SRC / "work_hi"
OUT = ROOT / "D3/natural"
R = 6371008.8
AEA = f"+proj=aea +lat_1=34 +lat_2=48 +lat_0=41.5 +lon_0=-120 +x_0=0 +y_0=0 +R={R} +units=m +no_defs"
WEB = 20037508.342789244
Z, RES, EXAGGERATION, TILE = 10, 115, 2, 512
NODATA = -32768


def run(*args):
    subprocess.run([str(a) for a in args], check=True, capture_output=True)


def merc(lon, lat, z):
    n = 2 ** z
    r = math.radians(lat)
    return (lon + 180) / 360 * n, (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n


def tile_set(project):
    """Zoom 10 tiles touching any CA/OR/WA ring (rasterised 8 px per tile, outline included)."""
    rings = [r for rs, _ in project for r in rs]
    xs = [merc(lo, la, Z)[0] for r in rings for lo, la in r]
    ys = [merc(lo, la, Z)[1] for r in rings for lo, la in r]
    x0, x1, y0, y1 = int(min(xs)), int(max(xs)), int(min(ys)), int(max(ys))
    sub = 8
    im = Image.new("L", ((x1 - x0 + 1) * sub, (y1 - y0 + 1) * sub), 0)
    d = ImageDraw.Draw(im)
    for r in rings:
        d.polygon([((merc(lo, la, Z)[0] - x0) * sub, (merc(lo, la, Z)[1] - y0) * sub) for lo, la in r], fill=1, outline=1)
    a = np.asarray(im).reshape(y1 - y0 + 1, sub, x1 - x0 + 1, sub).max(axis=(1, 3))
    return [(x0 + tx, y0 + ty) for ty, tx in zip(*np.nonzero(a))]


def download(tiles):
    TILES.mkdir(parents=True, exist_ok=True)

    def one(t):
        x, y = t
        p = TILES / f"{x}_{y}.png"
        if not p.exists():
            tmp = p.with_suffix(".part")
            run("curl", "-sf", "--retry", "3", "-o", tmp, f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png")
            tmp.rename(p)
        return p.stat().st_size

    with ThreadPoolExecutor(8) as ex:
        return sum(ex.map(one, tiles))


def mosaic(tiles):
    xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
    x0, y0 = min(xs), min(ys)
    w, h = (max(xs) - x0 + 1) * 256, (max(ys) - y0 + 1) * 256
    WORK.mkdir(parents=True, exist_ok=True)
    dem = np.memmap(WORK / "dem_3857.bin", dtype="<f4", mode="w+", shape=(h, w))
    dem[:] = NODATA
    for x, y in tiles:
        rgb = np.asarray(Image.open(TILES / f"{x}_{y}.png").convert("RGB"), dtype=np.float32)
        dem[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = \
            rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
    dem.flush()
    del dem
    res = 2 * WEB / (256 * 2 ** Z)
    ox, oy = -WEB + x0 * 256 * res, WEB - y0 * 256 * res
    (WORK / "dem_3857.vrt").write_text(f"""<VRTDataset rasterXSize="{w}" rasterYSize="{h}">
  <SRS>EPSG:3857</SRS>
  <GeoTransform>{ox}, {res}, 0, {oy}, 0, {-res}</GeoTransform>
  <VRTRasterBand dataType="Float32" band="1" subClass="VRTRawRasterBand">
    <NoDataValue>{NODATA}</NoDataValue>
    <SourceFilename relativeToVRT="1">dem_3857.bin</SourceFilename>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
</VRTDataset>
""")


def albers_box(project):
    t = Transformer.from_crs("EPSG:4326", AEA, always_xy=True)
    pts = [t.transform(lo, la) for rs, _ in project for r in rs for lo, la in r]
    xmin = math.floor((min(p[0] for p in pts) - 2000) / RES) * RES
    ymin = math.floor((min(p[1] for p in pts) - 2000) / RES) * RES
    xmax = math.ceil((max(p[0] for p in pts) + 2000) / RES) * RES
    ymax = math.ceil((max(p[1] for p in pts) + 2000) / RES) * RES
    return xmin, ymin, xmax, ymax


def to_raw(tif, name):
    """GDAL raster to a raw little-endian file numpy can memmap (PIL refuses images this large)."""
    run("gdal_translate", "-q", "-of", "ENVI", tif, WORK / name)
    return WORK / name


def main():
    project = load_states()[0]
    tiles = tile_set(project)
    got = download(tiles)
    print(f"{len(tiles)} zoom {Z} tiles on disk, {got / 1e6:.1f} MB")
    mosaic(tiles)

    xmin, ymin, xmax, ymax = albers_box(project)
    run("gdalwarp", "-overwrite", "-q", "-t_srs", AEA, "-tr", RES, RES, "-te", xmin, ymin, xmax, ymax,
        "-r", "cubic", "-srcnodata", NODATA, "-dstnodata", NODATA, "-wm", "2048", "-multi",
        "-co", "TILED=YES", "-co", "BIGTIFF=IF_NEEDED", WORK / "dem_3857.vrt", WORK / "dem_aea.tif")
    run("gdaldem", "hillshade", "-q", "-z", EXAGGERATION, "-az", "315", "-alt", "45", "-compute_edges",
        "-co", "TILED=YES", "-co", "BIGTIFF=IF_NEEDED", WORK / "dem_aea.tif", WORK / "hs_aea.tif")
    width, height = round((xmax - xmin) / RES), round((ymax - ymin) / RES)

    s = Path(STATES_JS).read_text()
    gj = json.loads(s[s.index("{"):s.rindex("}") + 1])
    gj["features"] = [f for f in gj["features"] if f["properties"]["STUSPS"] in ("CA", "OR", "WA")]
    (WORK / "project_states.geojson").write_text(json.dumps(gj))
    (WORK / "project_states_aea.geojson").unlink(missing_ok=True)
    run("ogr2ogr", "-t_srs", AEA, WORK / "project_states_aea.geojson", WORK / "project_states.geojson")
    run("gdal_rasterize", "-q", "-at", "-burn", "1", "-init", "0", "-ot", "Byte", "-te", xmin, ymin, xmax, ymax,
        "-ts", width, height, WORK / "project_states_aea.geojson", WORK / "mask.tif")

    hs = np.memmap(to_raw(WORK / "hs_aea.tif", "hs.raw"), dtype=np.uint8, mode="r", shape=(height, width))
    mask = np.memmap(to_raw(WORK / "mask.tif", "mask.raw"), dtype=np.uint8, mode="r", shape=(height, width))

    tile_dir = OUT / "relief_hi"
    if tile_dir.exists():
        shutil.rmtree(tile_dir)
    tile_dir.mkdir(parents=True)
    flat = 255 * math.sin(math.radians(45))
    written, total_bytes, land_px, shadow_sum = [], 0, 0, 0.0
    for row in range(math.ceil(height / TILE)):
        for col in range(math.ceil(width / TILE)):
            r0, c0 = row * TILE, col * TILE
            h_ = np.asarray(hs[r0:r0 + TILE, c0:c0 + TILE], dtype=np.float32)
            m_ = np.asarray(mask[r0:r0 + TILE, c0:c0 + TILE])
            if not m_.any():
                continue
            shadow = np.clip((flat - h_) / flat, 0, 1) ** 0.8     # same curve as the 500 m relief
            shadow[h_ == 0] = 0                                    # nodata draws as no shade
            shadow[m_ == 0] = 0                                    # outside CA/OR/WA
            land_px += int(m_.sum())
            shadow_sum += float(shadow[m_ == 1].sum())
            out = (255 * (1 - shadow)).astype(np.uint8)
            if out.min() == 255:
                continue
            p = tile_dir / f"{col}_{row}.jpg"
            Image.fromarray(out, mode="L").save(p, quality=82, optimize=True)
            written.append([col, row])
            total_bytes += p.stat().st_size
    del hs, mask

    placement = {"dir": "natural/relief_hi", "originX": xmin, "originY": ymax, "pixel": RES, "R": R,
                 "width": width, "height": height, "tile": TILE, "exaggeration": EXAGGERATION, "tiles": written}
    (OUT / "relief_hi.js").write_text("// generated by build/make_relief_hi.py, do not edit.\n"
                                      f"const RELIEF_HI = {json.dumps(placement, separators=(',', ':'))};\n")
    work_mb = sum(f.stat().st_size for f in WORK.rglob("*") if f.is_file()) / 1e6
    shutil.rmtree(WORK)
    print(f"grid {width} x {height} px at {RES} m; {len(written)} tiles of {TILE} px written, {total_bytes / 1e6:.1f} MB; "
          f"land {land_px:,} px; mean shadow over land {shadow_sum / land_px:.3f}; intermediates {work_mb:,.0f} MB deleted")


if __name__ == "__main__":
    main()
