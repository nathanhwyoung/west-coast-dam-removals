#!/usr/bin/env python3
"""Generate coordinate candidates for the unplaceable rows, for HUMAN review.

WHY RIVER FIRST. The 2026-09-08 pass matched on dam NAME and was never validated:
13 exact, 3 close, 30 nothing. On 2026-09-09 OR-076 Plainview Dam was found by
searching NACC for its RIVER instead, then reading the handful of results. River
names are far more standardised across agencies than dam names, which are local,
inconsistent, and often absent. So this searches river first and uses the dam name
only to rank what comes back.

WHAT THIS IS NOT. It writes nothing. Standing rule 4: matching scripts report, a
human accepts, a separate step applies. Everything here is a candidate to be read,
and the scoring is a sort order, not a verdict.

SCORING, and every component is a reason a human can check:
  +4  NACC says the barrier was removed          (a removal record should say so)
  +3  removal years agree exactly, +2 within 1   (see the Plainview 2021/2022 case)
  +3  strong dam-name similarity, +1 weak
  +1  NACC record is not already claimed by another AR row
  -3  NACC says NOT removed                      (weak evidence, see rule 23)

A high score is a reason to look, never a reason to write.
"""

import csv
import difflib
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SHEET = ROOT / "WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv"
LINKS = ROOT / "D3/build/ar_nacc_links.csv"
NACC = {s: ROOT / f"WORKING/NACC/dams_{s}/dams.csv" for s in ("CA", "OR", "WA")}

# Words that carry no discriminating power in a river or dam name.
NOISE = {"creek", "river", "fork", "north", "south", "east", "west", "middle",
         "upper", "lower", "dam", "the", "to", "of", "trib", "tributary",
         "unnamed", "co", "company", "mining", "mine", "removal"}


def norm(s):
    """Lowercase, strip punctuation and parentheses, collapse whitespace."""
    s = re.sub(r"\([^)]*\)", " ", (s or "").lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return {t for t in norm(s).split() if t not in NOISE and len(t) > 2}


def cell(r, c):
    return (r.get(c) or "").strip()


def year(v):
    v = (v or "").strip()
    try:
        return int(float(v))
    except ValueError:
        return None


def main():
    rows = list(csv.DictReader(open(SHEET, encoding="utf-8-sig")))
    claimed = {(r.get("nacc_SARPID") or "").strip()
               for r in csv.DictReader(open(LINKS, encoding="utf-8-sig"))}
    claimed.discard("")

    nacc = {}
    for st, path in NACC.items():
        nacc[st] = list(csv.DictReader(open(path, encoding="utf-8-sig")))

    unplaceable = [r for r in rows
                   if not cell(r, "Duplicate_Of_DRP")
                   and not cell(r, "Coordinate_Void_DRP")
                   and not (cell(r, "Latitude") or cell(r, "Latitude_DRP"))]

    print(f"{len(unplaceable)} unplaceable rows\n")
    found = 0

    for r in sorted(unplaceable, key=lambda r: (cell(r, "State"), r["AR_ID"])):
        st = cell(r, "State")
        river_t = tokens(cell(r, "River"))
        name_t = tokens(cell(r, "Dam_Name"))
        ar_yr = year(cell(r, "Year_Removed"))
        if not river_t:
            continue

        ar_river_n = norm(re.sub(r"\([^)]*\)", " ", cell(r, "River")))

        cands = []
        for n in nacc.get(st, []):
            nriver_t = tokens(n.get("River"))
            nriver_n = norm(n.get("River"))

            # A single shared token is not a river match. "Big Creek" shares "big"
            # with "Big Tujunga Creek" and they are different streams 500 km apart.
            # So: an exact normalised match always counts, otherwise require the AR
            # river to be a subset of the NACC river AND to carry two or more
            # distinctive tokens of its own.
            if ar_river_n and ar_river_n == nriver_n:
                pass
            elif len(river_t) >= 2 and river_t <= nriver_t:
                pass
            else:
                continue

            score = 0
            why = []
            removed = (n.get("Removed") or "").strip().lower()
            if removed == "yes":
                score += 4
                why.append("removed=yes")
            elif removed == "no":
                score -= 3
                why.append("removed=no")

            # A year mismatch is EVIDENCE, not merely an absent bonus. A 1949
            # mining dam is not a 2023 USFS fish passage project, however much
            # they share a creek. Only rewarding agreement let that noise through.
            n_yr = year(n.get("YearRemoved"))
            if ar_yr and n_yr:
                gap = abs(n_yr - ar_yr)
                if gap == 0:
                    score += 3
                    why.append(f"year exact {n_yr}")
                elif gap <= 1:
                    score += 2
                    why.append(f"year +-1 ({n_yr} vs {ar_yr})")
                elif gap <= 5:
                    why.append(f"year off by {gap}")
                else:
                    score -= 6
                    why.append(f"YEAR WRONG by {gap} ({n_yr} vs {ar_yr})")

            nname = n.get("Name") or ""
            if name_t and tokens(nname):
                ratio = difflib.SequenceMatcher(
                    None, norm(cell(r, "Dam_Name")), norm(nname)).ratio()
                if name_t & tokens(nname) or ratio > 0.75:
                    score += 3
                    why.append("name strong")
                elif ratio > 0.5:
                    score += 1
                    why.append("name weak")

            sid = (n.get("SARPID") or "").strip()
            if sid not in claimed:
                score += 1
            else:
                why.append("ALREADY CLAIMED")

            cands.append((score, sid, nname, n, why))

        if not cands:
            continue
        cands.sort(key=lambda c: -c[0])
        top = cands[0][0]
        if top < 4:                            # nothing worth a human's time
            continue

        found += 1
        print(f"=== {r['AR_ID']}  {cell(r,'Dam_Name') or '(unnamed)'}  "
              f"| {cell(r,'River')} | {st} {cell(r,'Year_Removed') or 'no year'} ===")
        for score, sid, nname, n, why in cands[:4]:
            if score < 2:
                continue
            print(f"    [{score:>3}] {sid:10s} {(nname or '(unnamed)')[:34]:36s} "
                  f"{n.get('lat','')},{n.get('lon','')}")
            print(f"          river={n.get('River','')!r} county={n.get('County','')!r} "
                  f"rm={n.get('Removed')}/{n.get('YearRemoved')} ht={n.get('Height')} "
                  f"src={(n.get('Source') or '')[:34]!r}")
            print(f"          {', '.join(why)}")
        print()

    print(f"{found} rows have at least one candidate scoring 4 or better.")
    print("NOTHING WRITTEN. Read these, decide, then add to build/apply_drp.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
