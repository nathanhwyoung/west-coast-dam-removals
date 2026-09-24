"""Link every American Rivers West Coast row to its NACC (SARP) record.

Three tiers, most trustworthy first. A row is linked once, by the highest tier
that reaches it, and the tier is recorded so the methods note can say how each
value was obtained.

  T1  AR.NABI_ID  == NACC.SARPID
      The documented cross-reference. AR carries SARP's own ID.

  T2  AR.AR_ID    == NACC.SourceID  where NACC.Source == the AR database
      SARP ingested the American Rivers database and kept the AR row id.
      Deterministic, and it reaches rows that carry no NABI_ID.

  T3  normalised dam name, same state, validated on river name and year
      Only accepted when exactly one candidate survives validation.
      Generic names ("Unnamed", "Mill") are never matched this way.

Writes build/ar_nacc_links.csv. Applies nothing to the working sheet.
"""

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
AR_PATH = ROOT / "WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv"
NACC_DIR = ROOT / "WORKING/NACC"
AR_SOURCE = "American Rivers Dam Removal Database"

JUNK_TOKENS = {"unnamed", "unknown", "dam", "no name", "none", "mill", "unnamed 1",
               "unnamed 2", "unnamed small 1", "unnamed small 2"}

NACC_KEEP = ["SARPID", "HasNetwork", "Name", "River", "State", "County", "lat", "lon",
             "NHDPlusID", "NIDID", "Removed", "YearRemoved", "Height",
             "Snapped", "HUC8", "HUC12", "Source", "SourceID", "Recon",
             "Estimated", "TotalUpstreamMiles", "PerennialUpstreamMiles",
             "GainMiles", "FunctionalNetworkMiles", "UpstreamBarrier",
             "UpstreamBarrierMiles", "StreamSizeClass", "FlowsToOcean"]


def norm_name(s):
    if not isinstance(s, str):
        return ""
    s = re.sub(r"[^a-z0-9#]+", " ", s.lower().strip())
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\b(dam|dams|removal)$", "", s).strip()


def norm_river(s):
    if not isinstance(s, str):
        return ""
    s = re.sub(r"[^a-z0-9]+", " ", s.lower().strip())
    s = re.sub(r"\b(river|creek|crk|ck|fork|slough|brook|run|branch|trib|to|the)\b",
               " ", s)
    return re.sub(r"\s+", " ", s).strip()


def river_agrees(a, b):
    na, nb = norm_river(a), norm_river(b)
    if not na or not nb:
        return None
    return na == nb or na in nb or nb in na


def load_nacc():
    frames = []
    for code in ("OR", "CA", "WA"):
        df = pd.read_csv(NACC_DIR / f"dams_{code}/dams.csv", dtype=str,
                         low_memory=False)
        df["_st"] = code
        frames.append(df[[c for c in NACC_KEEP if c in df.columns] + ["_st"]])
    n = pd.concat(frames, ignore_index=True)
    n["_norm"] = n["Name"].map(norm_name)
    return n


def main():
    ar = pd.read_csv(AR_PATH, dtype=str)
    nacc = load_nacc()
    # keep SARPID as a column as well as an index, so it survives the lookup
    by_sarpid = nacc.set_index("SARPID", drop=False)

    ar_sourced = nacc[nacc["Source"].eq(AR_SOURCE)].drop_duplicates("SourceID")
    by_srcid = ar_sourced.set_index("SourceID", drop=False)

    links = []
    for _, row in ar.iterrows():
        arid, state = row["AR_ID"], row["State"]
        hit, tier, note = None, None, ""

        nabi = row.get("NABI_ID") or row.get("NABI_ID_DRP")
        if isinstance(nabi, str) and nabi in by_sarpid.index:
            hit, tier = by_sarpid.loc[nabi], "T1_NABI"

        if hit is None and arid in by_srcid.index:
            hit, tier = by_srcid.loc[arid], "T2_SOURCEID"

        if hit is None:
            n = norm_name(row.get("Dam_Name"))
            if n and n not in JUNK_TOKENS:
                pool = nacc[(nacc["_st"] == state) & (nacc["_norm"] == n)]
                ok = []
                for _, c in pool.iterrows():
                    if river_agrees(row.get("River"), c.get("River")) is True:
                        ok.append(c)
                if len(ok) == 1:
                    hit, tier = ok[0], "T3_NAME_VALIDATED"
                elif len(pool) > 0:
                    note = f"{len(pool)} name hits, {len(ok)} survived validation"

        rec = dict(AR_ID=arid, State=state, Dam_Name=row.get("Dam_Name"),
                   ar_river=row.get("River"), ar_year=row.get("Year_Removed"),
                   ar_lat=row.get("Latitude"), ar_lon=row.get("Longitude"),
                   tier=tier or "UNLINKED", note=note)
        if hit is not None:
            for c in ("SARPID", "Name", "River", "lat", "lon", "NHDPlusID",
                      "NIDID", "Removed", "YearRemoved", "Snapped", "HUC12",
                      "Source", "TotalUpstreamMiles", "PerennialUpstreamMiles",
                      "GainMiles", "FunctionalNetworkMiles", "HasNetwork",
                      "UpstreamBarrier", "UpstreamBarrierMiles"):
                rec["nacc_" + c] = hit.get(c)
        links.append(rec)

    out = pd.DataFrame(links)
    print("LINK TIER")
    print(out["tier"].value_counts().to_string())
    print(f"\nlinked: {(out.tier != 'UNLINKED').sum()} of {len(out)}")

    ghost = out["ar_lat"].isna()
    print(f"\nGhost rows (no AR coordinate): {ghost.sum()}")
    g = out[ghost]
    print(g["tier"].value_counts().to_string())
    got = g[g["nacc_lat"].notna()] if "nacc_lat" in g else g.iloc[0:0]
    print(f"ghosts that gain a coordinate from NACC: {len(got)}")
    if len(got):
        print(got[["AR_ID", "Dam_Name", "ar_river", "nacc_River", "nacc_lat",
                   "nacc_lon", "nacc_Snapped", "tier"]].to_string(index=False))

    # coordinate QA on rows where both sides have a point
    both = out[out["ar_lat"].notna() & out.get("nacc_lat").notna()].copy()
    if len(both):
        import math
        def hav(la1, lo1, la2, lo2):
            r = 6371000.0
            p1, p2 = math.radians(la1), math.radians(la2)
            dp, dl = p2 - p1, math.radians(lo2 - lo1)
            a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
            return 2*r*math.asin(math.sqrt(a))
        d = []
        for _, r in both.iterrows():
            try:
                d.append(hav(float(r.ar_lat), float(r.ar_lon),
                             float(r.nacc_lat), float(r.nacc_lon)))
            except (TypeError, ValueError):
                d.append(float("nan"))
        both["dist_m"] = d
        print(f"\nCoordinate QA on {len(both)} rows with a point on both sides")
        print(both["dist_m"].describe().round(1).to_string())
        far = both[both.dist_m > 1000].sort_values("dist_m", ascending=False)
        print(f"\ndisagree by more than 1 km: {len(far)}")
        if len(far):
            print(far[["AR_ID", "Dam_Name", "ar_river", "nacc_River",
                       "dist_m", "tier"]].head(25).to_string(index=False))
        out = out.merge(both[["AR_ID", "dist_m"]], on="AR_ID", how="left")

    p = ROOT / "D3/build/ar_nacc_links.csv"
    out.to_csv(p, index=False)
    print(f"\nwrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
