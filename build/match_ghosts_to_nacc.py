"""Match the coordinate-less American Rivers rows ("ghosts") to NACC dams by name,
then VALIDATE each candidate on river name and removal year before anything is
written into a _DRP column.

Nothing here writes to the working sheet. It prints a report for a human pass.

Inputs
  WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv
  WORKING/NACC/dams_{OR,CA,WA}/dams.csv   (read as str: NHDPlusID is in sci notation)
"""

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
AR_PATH = ROOT / "WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv"
NACC_DIR = ROOT / "WORKING/NACC"

STATE_NAME = {"OR": "Oregon", "CA": "California", "WA": "Washington"}

# Names too generic to trust a match on. "Unnamed Dam #1" matching "Unnamed" is
# not a match; neither is one of the many "Mill Dam"s.
JUNK_TOKENS = {"unnamed", "unknown", "unnamed dam", "dam", "no name", "none"}


def norm_name(s):
    """Lowercase, strip a trailing 'dam'/'diversion dam', squash punctuation."""
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9#]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(dam|dams)$", "", s).strip()
    return s


def norm_river(s):
    """Normalize a river/creek name for agreement checking."""
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(river|creek|crk|ck|fork|slough|brook|run|branch)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def river_agrees(a, b):
    """None = one side is blank, so nothing to check."""
    na, nb = norm_river(a), norm_river(b)
    if not na or not nb:
        return None
    if na == nb:
        return True
    # allow one to contain the other ("evans" vs "evans north")
    return na in nb.split() or nb in na.split() or na in nb or nb in na


def load_nacc():
    frames = []
    for code, full in STATE_NAME.items():
        p = NACC_DIR / f"dams_{code}/dams.csv"
        df = pd.read_csv(p, dtype=str, low_memory=False)
        df["_state"] = code
        frames.append(df)
    keep = [
        "SARPID", "Name", "River", "State", "County", "lat", "lon",
        "NHDPlusID", "NIDID", "Removed", "YearRemoved", "YearCompleted",
        "Height", "Snapped", "HUC8", "Source", "_state",
    ]
    out = pd.concat([f[[c for c in keep if c in f.columns]] for f in frames],
                    ignore_index=True)
    out["_norm"] = out["Name"].map(norm_name)
    return out


def main():
    ar = pd.read_csv(AR_PATH, dtype=str)
    nacc = load_nacc()

    ghosts = ar[ar["Latitude"].isna() & ar["Latitude_DRP"].isna()].copy()
    ghosts["_norm"] = ghosts["Dam_Name"].map(norm_name)

    print(f"AR rows: {len(ar)}   ghosts (no coords, no fill): {len(ghosts)}")
    print(f"NACC rows: {len(nacc)}  "
          f"({nacc['_state'].value_counts().to_dict()})\n")

    rows = []
    for _, g in ghosts.iterrows():
        state = g["State"]
        code = {v: k for k, v in STATE_NAME.items()}.get(
            state, state if state in STATE_NAME else None)
        if code is None:
            code = state
        pool = nacc[nacc["_state"] == code]
        n = g["_norm"]

        if not n or n in JUNK_TOKENS:
            rows.append(dict(ar_id=g["AR_ID"], name=g["Dam_Name"], state=code,
                             verdict="SKIP_GENERIC_NAME", n_hits=0))
            continue

        hits = pool[pool["_norm"] == n]
        if len(hits) == 0:
            rows.append(dict(ar_id=g["AR_ID"], name=g["Dam_Name"], state=code,
                             verdict="NO_MATCH", n_hits=0))
            continue

        for _, h in hits.iterrows():
            agree = river_agrees(g.get("River"), h.get("River"))
            yr_ar = (g.get("Year_Removed") or "")[:4]
            yr_na = (h.get("YearRemoved") or "")
            yr_na = "" if not isinstance(yr_na, str) else yr_na[:4]
            year_ok = None
            if yr_ar and yr_na and yr_na != "0":
                try:
                    year_ok = abs(int(yr_ar) - int(yr_na)) <= 1
                except ValueError:
                    year_ok = None

            if len(hits) > 1:
                verdict = "AMBIGUOUS_MULTI_HIT"
            elif agree is True and (year_ok is not False):
                verdict = "ACCEPT"
            elif agree is False:
                verdict = "REJECT_RIVER_MISMATCH"
            elif agree is None:
                verdict = "UNVERIFIABLE_RIVER_BLANK"
            else:
                verdict = "REVIEW"
            if verdict == "ACCEPT" and h.get("Removed") not in ("yes", "Yes", "1", "true"):
                verdict = "ACCEPT_BUT_NOT_FLAGGED_REMOVED"

            rows.append(dict(
                ar_id=g["AR_ID"], name=g["Dam_Name"], state=code,
                ar_river=g.get("River"), nacc_river=h.get("River"),
                ar_year=yr_ar, nacc_year=yr_na,
                sarpid=h.get("SARPID"), nacc_name=h.get("Name"),
                lat=h.get("lat"), lon=h.get("lon"),
                nhdplusid=h.get("NHDPlusID"), removed=h.get("Removed"),
                snapped=h.get("Snapped"), county=h.get("County"),
                n_hits=len(hits), verdict=verdict))

    res = pd.DataFrame(rows)
    print("VERDICTS")
    print(res["verdict"].value_counts().to_string(), "\n")

    cols = ["ar_id", "name", "state", "ar_river", "nacc_river", "ar_year",
            "nacc_year", "removed", "sarpid", "lat", "lon", "verdict"]
    show = res[res["verdict"] != "NO_MATCH"]
    if len(show):
        with pd.option_context("display.width", 250, "display.max_colwidth", 26):
            print(show[[c for c in cols if c in show.columns]].to_string(index=False))

    print("\nNO_MATCH rows (need SARP tool / hand research):")
    nm = res[res["verdict"] == "NO_MATCH"]
    for _, r in nm.iterrows():
        print(f"  {r['ar_id']:8} {r['state']}  {r['name']}")

    out = ROOT / "D3/build/ghost_match_candidates.csv"
    res.to_csv(out, index=False)
    print(f"\nwrote {out.relative_to(ROOT)}  ({len(res)} candidate rows, NOT applied)")


if __name__ == "__main__":
    sys.exit(main())
