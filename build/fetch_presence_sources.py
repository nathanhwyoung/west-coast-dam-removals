"""Species-present tier: snapshot every distribution source on one date (rule 2).

The native migratory species list is in PORTFOLIO_NOTES/DAM_TRACKER_NEW/
SPECIES_LIST_DRAFT.md. Sources were chosen, and checked for newer versions, on
2026-09-11 (the "Versions checked" table there). Already on disk and not fetched
here: ODFW FHD 1167_5 (current), CDFW ds326 coho, and PISCES 2.0.4 (Nathan's
download, identical to CDFW's 2014 copies).

Downloads, all public, no login:
  WDFW SWIFD, the official zipped file geodatabase (Last-Modified 2026-04-17).
      Not the REST service: the zip is WDFW's own published snapshot.
  CDFW BIOS file library zips: ds340 winter steelhead, ds341 summer steelhead,
      ds1325 eulachon range, ds981 and ds982 NOAA Chinook distribution (2005),
      ds2673 USFWS Pacific lamprey, California.
  USFWS Columbia River office, Pacific lamprey WA/OR/ID 2022: distribution
      lines (layer 45) and observation points (layer 41). Only a REST service,
      so it is paged out to GeoJSON.

Every file is recorded in WORKING/PRESENCE_SOURCES_MANIFEST.json with its URL,
the server's Last-Modified, size and SHA-256, so the snapshot can be verified
later. Cached: re-running fetches nothing already on disk.
"""

import datetime
import hashlib
import json
import ssl
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parent.parent.parent
WORK = ROOT / "WORKING"
STAMP = "2026-09-11"
MANIFEST = WORK / "PRESENCE_SOURCES_MANIFEST.json"

# python.org Python on macOS needs certifi passed explicitly (see snapshot_agol.py).
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

BIOS = "https://filelib.wildlife.ca.gov/Public/BDB/GIS/BIOS/Public_Datasets"
ZIPS = [
    # (local folder, local name, url, what)
    ("WDFW", f"SWIFD_WDFWFishDistribution_{STAMP}.zip",
     "https://fortress.wa.gov/dfw/public/PublicDownload/Fish/WDFWFishDistribution.zip",
     "WDFW SWIFD, Washington fish distribution"),
    ("CDFW", f"ds340_{STAMP}.zip", f"{BIOS}/300_399/ds340.zip",
     "CDFW winter steelhead distribution (June 2012)"),
    ("CDFW", f"ds341_{STAMP}.zip", f"{BIOS}/300_399/ds341.zip",
     "CDFW summer steelhead distribution (October 2009)"),
    ("CDFW", f"ds1325_{STAMP}.zip", f"{BIOS}/1300_1399/ds1325.zip",
     "CDFW eulachon range"),
    ("CDFW", f"ds981_{STAMP}.zip", f"{BIOS}/900_999/ds981.zip",
     "NOAA California Coastal Chinook distribution (2005)"),
    ("CDFW", f"ds982_{STAMP}.zip", f"{BIOS}/900_999/ds982.zip",
     "NOAA Central Valley spring-run Chinook distribution (2005)"),
    ("CDFW", f"ds2673_{STAMP}.zip", f"{BIOS}/2600_2699/ds2673.zip",
     "USFWS Pacific lamprey historical range and current distribution, California (2021)"),
]

LAMPREY = ("https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/"
           "Pacific_Lamprey_Known_Observations_And_Distribution_201805/FeatureServer")
LAYERS = [
    (45, f"usfws_lamprey_NW_distribution_2022_{STAMP}.geojson",
     "USFWS Pacific lamprey distribution, WA/OR/ID (2022), lines"),
    (41, f"usfws_lamprey_NW_observations_2022_{STAMP}.geojson",
     "USFWS Pacific lamprey observations (2022), points"),
]


def open_url(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "dam-tracker-fetch"})
    return urllib.request.urlopen(req, context=SSL_CTX, timeout=600)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_zip(folder: str, name: str, url: str, what: str) -> dict:
    dest = WORK / folder / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open_url(url, "HEAD") as r:
        last_mod = r.headers.get("Last-Modified")
    if not dest.exists():
        tmp = dest.with_suffix(".part")
        with open_url(url) as r, tmp.open("wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
        status = "downloaded"
    else:
        status = "cached"
    out = dest.with_suffix("")                     # unzip beside it, same stem
    if not out.exists():
        with zipfile.ZipFile(dest) as z:
            z.extractall(out)
    return {"what": what, "url": url, "local": str(dest.relative_to(ROOT)),
            "extracted_to": str(out.relative_to(ROOT)), "server_last_modified": last_mod,
            "bytes": dest.stat().st_size, "sha256": sha256(dest), "status": status}


def fetch_layer(layer: int, name: str, what: str) -> dict:
    dest = WORK / "USFWS_LAMPREY" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = WORK / "USFWS_LAMPREY" / f"layer{layer}_service_metadata_{STAMP}.json"
    if not meta.exists():
        with open_url(f"{LAMPREY}/{layer}?f=json") as r:
            meta.write_bytes(r.read())
    if not dest.exists():
        feats, offset = [], 0
        while True:
            q = urllib.parse.urlencode({
                "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                "orderByFields": "OBJECTID", "resultOffset": offset,
                "resultRecordCount": 2000})
            with open_url(f"{LAMPREY}/{layer}/query?{q}") as r:
                page = json.loads(r.read())
            got = page.get("features", [])
            feats += got
            # Page on exceededTransferLimit, not on a short page: a server can
            # cap below the requested count (lesson from snapshot_agol.py).
            if not got or not page.get("properties", {}).get("exceededTransferLimit") and len(got) < 2000:
                break
            offset += len(got)
        dest.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        status = "downloaded"
    else:
        status = "cached"
    with open_url(f"{LAMPREY}/{layer}/query?where=1%3D1&returnCountOnly=true&f=json") as r:
        expected = json.loads(r.read()).get("count")
    n = len(json.loads(dest.read_text())["features"])
    return {"what": what, "url": f"{LAMPREY}/{layer}", "local": str(dest.relative_to(ROOT)),
            "features": n, "service_count": expected, "complete": n == expected,
            "bytes": dest.stat().st_size, "sha256": sha256(dest), "status": status}


def main() -> int:
    rows, bad = [], 0
    for folder, name, url, what in ZIPS:
        try:
            r = fetch_zip(folder, name, url, what)
            print(f"  {r['status']:10} {r['bytes']/1048576:8.1f} MB  {r['server_last_modified']}  {name}")
            rows.append(r)
        except Exception as e:
            print(f"  ! {name}: {e}", file=sys.stderr); bad += 1
    for layer, name, what in LAYERS:
        try:
            r = fetch_layer(layer, name, what)
            flag = "" if r["complete"] else "  <-- INCOMPLETE"
            print(f"  {r['status']:10} {r['features']:>8,} of {r['service_count']:,} features  {name}{flag}")
            bad += 0 if r["complete"] else 1
            rows.append(r)
        except Exception as e:
            print(f"  ! {name}: {e}", file=sys.stderr); bad += 1
    MANIFEST.write_text(json.dumps({
        "snapshot": STAMP,
        "written_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "purpose": "species-present tier sources; see SPECIES_LIST_DRAFT.md",
        "not_fetched_here": ["ODFW FHD 1167_5 (on disk, current)", "CDFW ds326 coho (WORKING/CDFW)",
                             "PISCES 2.0.4 (WORKING/pisces_2.0.4_all_ranges_shp_and_png)"],
        "files": rows}, indent=2))
    print(f"\nwrote {MANIFEST.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
