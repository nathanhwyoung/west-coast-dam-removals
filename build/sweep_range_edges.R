#!/usr/bin/env Rscript
# The containment sweep: how close does each dam sit to the EDGE of a species' range?
#
# Written 2026-09-13 for PHASE2_AUDIT.md section 2, "Containment, 20 rows to 50".
#
# WHY. Nine of the twenty-one species reach California only as PISCES HUC12 ranges:
# whole-watershed polygons meaning "this fish is somewhere in this drainage", not a
# mapped reach. The join matches those by CONTAINMENT, plus the 75 m tolerance that
# standing rule 41 added after Iron Gate was found sitting 0.238 m outside the Chinook
# range and reading as a dam with no Chinook.
#
# Containment has a hard edge, and hard edges are dangerous here for two reasons that
# compound: a dam point carries about 40 m of coordinate error, and HUC12 boundaries are
# drainage divides whose outlet is a point on the mainstem, which is exactly where dams
# get built. Dams land on these edges by construction rather than by accident.
#
# Phase 1 had two range species and the answer was comfortable: one dam inside 75 m, the
# next 27 km away, so any tolerance between about 1 m and 400 m gave the same result.
# Phase 2 has nine, so this re-measures it.
#
# BOTH DIRECTIONS, which is the point. A dam just OUTSIDE an edge is a fish we fail to
# record (the Iron Gate case). A dam just INSIDE one is a match balanced on the rim: a
# later coordinate correction, of the kind CA-133 got, drops it out and takes its fish
# with it. The second kind is invisible in the join output, because everything contained
# reports 0 m.
#
# MEASURED AGAINST THE UNION OF EACH SPECIES' POLYGONS, NOT AGAINST EACH POLYGON.
# This is the whole correctness argument of the script. The join tests HUC12s one at a
# time, but a species' range is their union, so a dam sitting 1 m from the seam between
# two adjacent HUC12s OF THE SAME SPECIES is not fragile at all: nudge it and it lands in
# the neighbour, still in range. Only the OUTER boundary of the union can flip an answer.
# Measuring per polygon would report every internal seam as a near miss and bury the real
# ones.
#
# Reads the same built layer the join reads, so it cannot disagree with it about what a
# range is. Writes nothing but its own report.
#
# USAGE
#   Rscript build/sweep_range_edges.R
#
# OUTPUT, WORKING/JOIN/audit/
#   range_edge_sweep.csv   one row per dam/species where the dam is inside, or within
#                          REPORT_M of, that species' range
#   range_edge_sweep.txt   the readable version

suppressMessages({library(sf); library(dplyr)})
sf_use_s2(FALSE)

args <- commandArgs(trailingOnly = FALSE)
HERE <- dirname(normalizePath(sub("^--file=", "", args[grep("^--file=", args)])))
ROOT <- normalizePath(file.path(HERE, "..", ".."))
P <- function(...) file.path(ROOT, ...)

# BASE_M is the tolerance under test, so it is read from the shared file rather than
# typed here (standing rule 44).
source(file.path(HERE, "rules_shared.R"))

CRS      <- 5070
REPORT_M <- 5000   # how far out to report a near miss before it stops being interesting

SHEET <- P("WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv")
PRES  <- P("WORKING/LAYERS/presence/presence_fullres.gpkg")
OUT   <- P("WORKING/JOIN/audit")

say <- function(...) cat(sprintf(...), "\n", sep = "")

# ---- dams ------------------------------------------------------------------
sheet <- read.csv(SHEET, colClasses = "character", fileEncoding = "UTF-8-BOM")
has <- function(v) !is.na(v) & nzchar(trimws(v))
dams <- sheet |>
  filter(!has(Duplicate_Of_DRP), !has(Coordinate_Void_DRP)) |>
  mutate(lat = as.numeric(ifelse(has(Latitude_DRP), Latitude_DRP, Latitude)),
         lon = as.numeric(ifelse(has(Longitude_DRP), Longitude_DRP, Longitude))) |>
  filter(!is.na(lat), !is.na(lon)) |>
  st_as_sf(coords = c("lon", "lat"), crs = 4326) |> st_transform(CRS)
say("dams: %d mapped", nrow(dams))

# ---- ranges ----------------------------------------------------------------
ranges <- st_read(PRES, layer = "presence_ranges", quiet = TRUE) |> st_transform(CRS)
say("range polygons: %d across %d species", nrow(ranges), n_distinct(ranges$species))

rows <- list()
for (sp in sort(unique(ranges$species))) {
  r <- ranges[ranges$species == sp, ]
  # The union is the species' actual range; its boundary is the only edge that can flip
  # a containment answer. st_make_valid first, because unioning HUC12s that share edges
  # can otherwise trip GEOS on a self-intersection.
  u <- st_union(st_make_valid(st_geometry(r)))
  b <- st_boundary(u)
  inside <- lengths(st_within(dams, u)) > 0
  d_edge <- as.numeric(st_distance(dams, b))     # to the rim, whichever side we are on
  d_poly <- as.numeric(st_distance(dams, u))     # 0 when inside, the gap when outside
  keep <- which(inside | d_poly <= REPORT_M)
  say("  %-28s %4d HUC12s, %3d dams inside, %2d near but outside",
      sp, nrow(r), sum(inside), sum(!inside & d_poly <= REPORT_M))
  for (i in keep) {
    rows[[length(rows) + 1]] <- data.frame(
      AR_ID = dams$AR_ID[i], dam = dams$Dam_Name[i], state = dams$State[i],
      lat = round(st_coordinates(st_transform(dams[i, ], 4326))[1, 2], 5),
      lon = round(st_coordinates(st_transform(dams[i, ], 4326))[1, 1], 5),
      species = sp,
      position = if (inside[i]) "inside" else "outside",
      # For an inside dam this is its margin: how far it could move before falling out.
      # For an outside dam it is the same number the join's tolerance is compared against.
      edge_m = round(d_edge[i], 2),
      matches_now = if (inside[i] || d_poly[i] <= BASE_M) "yes" else "no",
      fragile = if (inside[i] && d_edge[i] <= BASE_M) "INSIDE EDGE, within tolerance of falling out"
                else if (!inside[i] && d_poly[i] <= BASE_M) "matched BY the tolerance (rule 41)"
                else "", stringsAsFactors = FALSE)
  }
}

res <- bind_rows(rows) |> arrange(edge_m)
dir.create(OUT, showWarnings = FALSE, recursive = TRUE)
write.csv(res, file.path(OUT, "range_edge_sweep.csv"), row.names = FALSE)

ins <- res |> filter(position == "inside")
out <- res |> filter(position == "outside")

txt <- capture.output({
  cat(sprintf("Range edge sweep, %s. Tolerance under test: %d m (standing rule 41).\n",
              format(Sys.Date()), BASE_M))
  cat("Distance is to the edge of the UNION of each species' HUC12s, not to one HUC12.\n\n")

  cat(sprintf("INSIDE a range: %d dam/species pairs.\n", nrow(ins)))
  cat("  How far each could move before falling out of range.\n")
  cat(sprintf("  Closest to an edge: %s\n", if (nrow(ins)) sprintf("%.2f m", min(ins$edge_m)) else "n/a"))
  cat(sprintf("  Within the %d m tolerance of the edge: %d\n\n", BASE_M, sum(ins$edge_m <= BASE_M)))
  if (nrow(ins)) {
    cat("  The ten closest to an edge:\n")
    h <- head(ins, 10)
    for (k in seq_len(nrow(h)))
      cat(sprintf("    %-9s %-30s %-26s %10.1f m  %s\n", h$AR_ID[k], substr(h$dam[k], 1, 30),
                  h$species[k], h$edge_m[k], h$fragile[k]))
  }

  cat(sprintf("\nOUTSIDE but within %d m: %d dam/species pairs.\n", REPORT_M, nrow(out)))
  cat(sprintf("  Matched by the tolerance: %d\n", sum(out$matches_now == "yes")))
  cat(sprintf("  Nearest one NOT matched: %s\n\n",
              if (any(out$matches_now == "no")) sprintf("%.1f m", min(out$edge_m[out$matches_now == "no"]))
              else "none within the report distance"))
  if (nrow(out)) {
    cat("  The ten nearest:\n")
    h <- head(out, 10)
    for (k in seq_len(nrow(h)))
      cat(sprintf("    %-9s %-30s %-26s %10.1f m  %s\n", h$AR_ID[k], substr(h$dam[k], 1, 30),
                  h$species[k], h$edge_m[k],
                  if (h$matches_now[k] == "yes") h$fragile[k] else "not matched"))
  }

  # The safe window: move the tolerance anywhere inside it and no dam changes answer.
  lo <- if (any(out$matches_now == "yes")) max(out$edge_m[out$matches_now == "yes"]) else 0
  hi <- if (any(out$matches_now == "no")) min(out$edge_m[out$matches_now == "no"]) else Inf
  cat(sprintf("\nSAFE WINDOW FOR THE TOLERANCE: above %.1f m (to keep every dam it currently\n", lo))
  cat(sprintf("matches) and below %.1f m (to admit no new one). Current value %d m %s.\n",
              hi, BASE_M, if (BASE_M > lo && BASE_M < hi) "sits inside it" else "DOES NOT SIT INSIDE IT"))
})
writeLines(txt, file.path(OUT, "range_edge_sweep.txt"))
cat(paste(txt, collapse = "\n"), "\n")
say("wrote %s (%d rows)", file.path("WORKING/JOIN/audit", "range_edge_sweep.csv"), nrow(res))
