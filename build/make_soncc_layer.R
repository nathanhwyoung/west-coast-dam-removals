#!/usr/bin/env Rscript
# Stage 5: reconstruct SONCC coho critical habitat from the regulation, BOTH STATES.
#
# NMFS has never published spatial data for the Southern Oregon / Northern
# California Coast coho ESU. The designation still legally exists, and
# 50 CFR 226.210 defines it in words. Four clauses, four steps:
#
#   "all river reaches accessible to listed coho salmon"      -> DISTRIBUTION
#   "in hydrologic units AND COUNTIES identified in Table 6"  -> UNITS, COUNTIES
#   "between Cape Blanco, Oregon, and Punta Gorda, California"-> ESU EXTENT
#   "Inaccessible reaches are those above specific dams
#    identified in Table 6"                                   -> BOUNDARY DAMS
#
# So: habitat = distribution ∩ Table 6 unit ∩ that unit's listed counties
#               ∩ ESU extent − basins above the 11 boundary dams.
#
# ESU EXTENT, added the same day after the first run showed why: the Sixes unit
# (17100306) straddles Cape Blanco. Its northern streams (Sixes River, Floras
# Creek, Edson Creek) are OREGON COAST coho, and 140 km of them sat on NMFS's
# published Oregon Coast coho critical habitat: one stream, two ESUs. Table 6
# works in whole HUC8s and cannot split a watershed at a cape. NOAA's own ESU
# range (ds803, HUC12 polygons, 2025) does: it keeps only the 7 Sixes-unit
# HUC12s south of the cape. It is used here ONLY for where the ESU begins and
# ends. Its accessibility flags are NOT used; they do not match Table 6.
# Measured: outside the two capes it removes nothing but edge slivers (<10 m).
#
# DISTRIBUTION, two sources with two different claim types (never merge them
# without saying so; the claim_type field carries it on every reach):
#   Oregon      ODFW Fish Habitat Distribution 1167_5, fhd_Coho, filtered on the
#               rule's four clauses (below). Documented distribution WITH an
#               accessibility attribute.
#   California  CDFW BIOS ds326 Coho Distribution, August 2025. OBSERVED
#               distribution: every sighting since 1990 traced DOWNSTREAM to the
#               sea. Nothing above the highest sighting is ever included, so it
#               UNDERSTATES the designation (the unflattering direction).
# Each source is used only inside its own state. The seam is the TIGER state
# line, because the footprint pieces are built from counties.
#
# FOOTPRINT: Table 6 lists counties per unit, and the rule is "units AND
# counties", so a unit's area outside its listed counties is not designated.
# This bites in exactly two places: Upper Klamath lists Jackson OR but NOT
# Klamath OR (which holds John C. Boyle Dam), and Lower Klamath lists only
# California counties although its watershed crosses into Oregon.
#
# BOUNDARY DAMS: basins from build/fetch_boundary_basins.py (StreamStats from
# the exact dam point, NLDI for Dwinnell), each checked against an independent
# drainage area. Iron Gate stays a boundary although it was removed in 2024:
# the designation has never been amended. That is the finding, not a defect.
#
# Transcription of Table 6 verified row for row against the current eCFR
# (Table 6 to Part 226) on 2026-09-11: every county and every dam matches.
#
# OUTPUTS, in WORKING/LAYERS/derived/:
#   soncc_coho_derived_fullres.gpkg  FULL RESOLUTION. Joins read this (rule 35).
#   soncc_coho_derived.geojson       ~33 m simplified, DISPLAY ONLY.
#   soncc_footprint.gpkg             the designation polygons + boundary basins
#   soncc_stage_accounting.csv       km by state and unit at every step (A to D)
#   soncc_boundary_dam_effect.csv    km removed by each boundary dam
#   soncc_dam_checks.csv             removed dams within 250 m, old vs new
#   soncc_manifest.json
#
# Replaces build/make_soncc_layer.py (Oregon only, boundary dams advisory, no
# county clause), kept at build/_old/make_soncc_layer_pre_rebuild_2026-09-11.py.

suppressMessages({library(sf); library(dplyr)})
sf_use_s2(FALSE)

args <- commandArgs(trailingOnly = FALSE)
HERE <- dirname(normalizePath(sub("^--file=", "", args[grep("^--file=", args)])))
ROOT <- normalizePath(file.path(HERE, "..", ".."))
P <- function(...) file.path(ROOT, ...)

FHD      <- P("_OLD/DOCS/DAM_DATA/ODFW/ODFW_1167_5_FHD_Publication.gdb/FHD_Publication_Streams.gdb")
DS326    <- P("WORKING/CDFW/ds326_2026-09-11/ds326.gdb")
DS803    <- P("WORKING/CDFW/ds803_2026-09-11.geojson")
WBD      <- P("WORKING/WBD/wbd_huc8_table6_2026-09-11.geojson")
COUNTIES <- P("WORKING/CENSUS/counties_table6_2026-09-11.geojson")
STATES   <- P("WORKING/CENSUS/states_CA_OR_2026-09-11.geojson")
BASINS   <- P("WORKING/SS_BASINS/boundary_basins.geojson")
SHEET    <- P("WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv")
OLD      <- P("WORKING/LAYERS/derived_pre_rebuild_2026-09-11/soncc_coho_derived.geojson")
OUT      <- P("WORKING/LAYERS/derived")

CRS <- 5070        # CONUS Albers, metres: one CRS for every overlay and length
KM  <- function(x) round(sum(as.numeric(st_length(x))) / 1000, 1)
lines_only <- function(x) {
  x <- x[!st_is_empty(x), ]
  suppressWarnings(st_collection_extract(x, "LINESTRING"))
}

# Table 6 to Part 226, units and counties. Long form: one row per listed county.
T6 <- read.csv(text = "
huc8,unit,state,county
18010101,Smith,CA,Del Norte
18010101,Smith,OR,Curry
18010102,Mad-Redwood,CA,Humboldt
18010102,Mad-Redwood,CA,Trinity
18010103,Upper Eel,CA,Mendocino
18010103,Upper Eel,CA,Glenn
18010103,Upper Eel,CA,Lake
18010104,Middle Fork Eel,CA,Mendocino
18010104,Middle Fork Eel,CA,Trinity
18010104,Middle Fork Eel,CA,Glenn
18010104,Middle Fork Eel,CA,Lake
18010105,Lower Eel,CA,Mendocino
18010105,Lower Eel,CA,Humboldt
18010105,Lower Eel,CA,Trinity
18010106,South Fork Eel,CA,Mendocino
18010106,South Fork Eel,CA,Humboldt
18010107,Mattole,CA,Humboldt
18010107,Mattole,CA,Mendocino
18010206,Upper Klamath,CA,Siskiyou
18010206,Upper Klamath,OR,Jackson
18010207,Shasta,CA,Siskiyou
18010208,Scott,CA,Siskiyou
18010209,Lower Klamath,CA,Del Norte
18010209,Lower Klamath,CA,Humboldt
18010209,Lower Klamath,CA,Siskiyou
18010210,Salmon,CA,Siskiyou
18010211,Trinity,CA,Humboldt
18010211,Trinity,CA,Trinity
18010212,South Fork Trinity,CA,Humboldt
18010212,South Fork Trinity,CA,Trinity
17100306,Sixes,OR,Curry
17100307,Upper Rogue,OR,Jackson
17100307,Upper Rogue,OR,Klamath
17100307,Upper Rogue,OR,Douglas
17100308,Middle Rogue,OR,Josephine
17100308,Middle Rogue,OR,Jackson
17100309,Applegate,OR,Josephine
17100309,Applegate,OR,Jackson
17100309,Applegate,CA,Siskiyou
17100310,Lower Rogue,OR,Curry
17100310,Lower Rogue,OR,Josephine
17100310,Lower Rogue,OR,Jackson
17100311,Illinois,OR,Curry
17100311,Illinois,OR,Josephine
17100311,Illinois,CA,Del Norte
17100312,Chetco,OR,Curry
17100312,Chetco,CA,Del Norte
", colClasses = "character", strip.white = TRUE)
T6$key <- paste(T6$huc8, T6$state, T6$county)

# The rule's clauses as ODFW fields (unchanged from the 2026-09-08 Oregon build).
ODFW_WHERE <- paste("fhdAccess = 'Unassisted'",     # accessible, no trap-and-haul
                    "AND fhdUseTy <> 'Historical'",  # current, not former, habitat
                    "AND fhdLifeHst = 'Anadromous'", # the anadromous ESU
                    "AND fhdOrig = 'NativeLocal'")   # native, not introduced

say <- function(...) cat(sprintf(...), "\n", sep = "")

# ---- 1. inputs -------------------------------------------------------------
say("1. reading inputs")
units <- st_read(WBD, quiet = TRUE) |> st_transform(CRS) |> st_make_valid() |>
  transmute(huc8 = as.character(huc8), unit_name = name)
states <- st_read(STATES, quiet = TRUE) |> st_transform(CRS) |> st_make_valid() |>
  transmute(state = STUSAB)
counties <- st_read(COUNTIES, quiet = TRUE) |> st_transform(CRS) |> st_make_valid() |>
  transmute(state = ifelse(STATE == "06", "CA", "OR"), county = BASENAME)
basins <- st_read(BASINS, quiet = TRUE) |> st_transform(CRS) |> st_make_valid()
basin_union <- st_union(basins)
esu_range <- st_read(DS803, quiet = TRUE) |> st_transform(CRS) |> st_make_valid() |> st_union()

odfw <- st_read(FHD, query = paste("SELECT * FROM fhd_Coho WHERE", ODFW_WHERE), quiet = TRUE) |>
  st_zm() |> st_transform(CRS) |>
  transmute(stream_name = fhdStNm, odfw_use_type = fhdUseTy, odfw_run = fhdRun,
            cdfw_waterid = NA_integer_, source_state = "OR",
            source_data = "ODFW Fish Habitat Distribution 1167_5, fhd_Coho",
            claim_type = "documented distribution, accessible (fhdAccess = Unassisted)")
cdfw <- st_read(DS326, layer = "ds326", quiet = TRUE) |> st_zm() |> st_transform(CRS) |>
  transmute(stream_name = Stream_Name, odfw_use_type = NA_character_, odfw_run = NA_character_,
            cdfw_waterid = as.integer(DFGWATERID), source_state = "CA",
            source_data = "CDFW BIOS ds326 Coho Distribution, August 2025",
            claim_type = "observed distribution, sightings since 1990 traced to the sea")
st_geometry(odfw) <- "geometry"; st_geometry(cdfw) <- "geometry"
dist <- rbind(odfw, cdfw)
say("   ODFW coho passing the four clauses: %s reaches, %s km (statewide)", format(nrow(odfw), big.mark = ","), KM(odfw))
say("   CDFW ds326: %s reaches, %s km (all California coho, both ESUs)", nrow(cdfw), KM(cdfw))
say("   boundary basins: %d", nrow(basins))

# ---- 2. footprint ----------------------------------------------------------
say("2. building the footprint: Table 6 units ∩ listed counties ∩ ESU extent − boundary basins")
unit_state <- suppressWarnings(st_intersection(units, states))            # units only
pieces_all <- suppressWarnings(st_intersection(units, counties))
pieces_all$key <- paste(pieces_all$huc8, pieces_all$state, pieces_all$county)
missing <- setdiff(T6$key, pieces_all$key)
if (length(missing)) stop("Table 6 unit/county pairs with no overlap: ", paste(missing, collapse = "; "))
pieces <- pieces_all |> filter(key %in% T6$key) |> select(huc8, unit_name, state, county)
footprint <- suppressWarnings(st_difference(st_intersection(pieces, esu_range), basin_union))
say("   %d unit/county pieces, all %d Table 6 pairs present", nrow(pieces), nrow(T6))

# ---- 3. clip distribution, stage by stage ----------------------------------
say("3. clipping distribution")
in_own_state <- function(x) x[x$state == x$source_state, ]
# A: units only (what the 2026-09-08 Oregon build did, now for both states)
A <- lines_only(in_own_state(suppressWarnings(st_intersection(dist, unit_state))))
# B: units AND listed counties
B <- lines_only(in_own_state(suppressWarnings(st_intersection(dist, pieces))))
# C: inside the ESU's own extent, Cape Blanco to Punta Gorda
Cx <- lines_only(suppressWarnings(st_intersection(B, esu_range)))
# D: minus everything above a boundary dam = the designation
D <- lines_only(suppressWarnings(st_difference(Cx, basin_union)))

acct <- bind_rows(
  st_drop_geometry(A)  |> mutate(stage = "A_units_only", km = as.numeric(st_length(A)) / 1000),
  st_drop_geometry(B)  |> mutate(stage = "B_plus_counties", km = as.numeric(st_length(B)) / 1000),
  st_drop_geometry(Cx) |> mutate(stage = "C_plus_esu_extent", km = as.numeric(st_length(Cx)) / 1000),
  st_drop_geometry(D)  |> mutate(stage = "D_minus_boundary_dams", km = as.numeric(st_length(D)) / 1000)) |>
  group_by(stage, state, huc8, unit_name) |> summarise(km = round(sum(km), 2), .groups = "drop")
by_state <- acct |> group_by(stage, state) |> summarise(km = round(sum(km), 1), .groups = "drop")
print(as.data.frame(by_state), row.names = FALSE)

# What each boundary dam removes, two ways. MARGINAL: from stage C, i.e. what
# this clause removes that no earlier clause already did. ALONE: from stage A,
# i.e. what the dam clause would remove on its own. The difference shows where
# two clauses independently exclude the same reach (John C. Boyle).
# Basins overlap only in slivers where neighbouring delineations meet
# (Dwinnell x Lewiston 0.055 km2, Lost Creek x Iron Gate 0), none holding habitat.
km_in <- function(x, poly) { y <- lines_only(suppressWarnings(st_intersection(x, poly)))
                             list(n = nrow(y), km = if (nrow(y)) KM(y) else 0,
                                  s = if (nrow(y)) paste(head(sort(unique(na.omit(y$stream_name))), 8), collapse = "; ") else "") }
dam_effect <- do.call(rbind, lapply(seq_len(nrow(basins)), function(i) {
  m <- km_in(Cx, basins[i, ]); a <- km_in(A, basins[i, ])
  data.frame(key = basins$key[i], dam = basins$dam[i], table6_unit = basins$table6_unit[i],
             basin_sqmi = basins$basin_sqmi[i], km_removed_marginal = m$km,
             km_removed_alone = a$km, streams_alone = a$s)
}))
say("   boundary dams, km removed (marginal / alone):")
print(dam_effect[dam_effect$km_removed_alone > 0, c("dam", "km_removed_marginal", "km_removed_alone", "streams_alone")], row.names = FALSE)

# ---- 4. write --------------------------------------------------------------
say("4. writing outputs")
C_out <- D |> mutate(source = "derived", esu = "SONCC coho",
                     authority = "50 CFR 226.210; 64 FR 24049 (1999); Table 6 to Part 226") |>
  select(stream_name, state, huc8, unit_name, county, source_data, claim_type,
         odfw_use_type, odfw_run, cdfw_waterid, source, esu, authority) |>
  st_transform(4326)
fullres <- file.path(OUT, "soncc_coho_derived_fullres.gpkg")
display <- file.path(OUT, "soncc_coho_derived.geojson")
fp_gpkg <- file.path(OUT, "soncc_footprint.gpkg")
for (f in c(fullres, display, fp_gpkg)) if (file.exists(f)) file.remove(f)
st_write(C_out, fullres, layer = "soncc_coho", quiet = TRUE)
st_write(st_transform(footprint, 4326), fp_gpkg, layer = "designation_footprint", quiet = TRUE)
st_write(st_transform(basins, 4326), fp_gpkg, layer = "boundary_basins", quiet = TRUE, append = TRUE)
# Display copy: same ogr2ogr simplification as every other habitat layer.
# Never RFC7946=YES (it turned 24% of NMFS lines into points; make_species_layers.py).
rc <- system2("ogr2ogr", c("-f", "GeoJSON", shQuote(display), shQuote(fullres), "soncc_coho",
                           "-simplify", "0.0003", "-lco", "COORDINATE_PRECISION=5"))
if (rc != 0) stop("ogr2ogr display export failed")
write.csv(acct, file.path(OUT, "soncc_stage_accounting.csv"), row.names = FALSE)
write.csv(dam_effect, file.path(OUT, "soncc_boundary_dam_effect.csv"), row.names = FALSE)

# ---- 5. checks -------------------------------------------------------------
say("5. checks")
sheet <- read.csv(SHEET, colClasses = "character", fileEncoding = "UTF-8-BOM")
has <- function(v) !is.na(v) & nzchar(trimws(v))
sheet <- sheet |> filter(!has(Duplicate_Of_DRP), !has(Coordinate_Void_DRP)) |>
  mutate(lat = as.numeric(ifelse(has(Latitude_DRP), Latitude_DRP, Latitude)),
         lon = as.numeric(ifelse(has(Longitude_DRP), Longitude_DRP, Longitude))) |>
  filter(!is.na(lat), !is.na(lon))
dams <- st_as_sf(sheet, coords = c("lon", "lat"), crs = 4326) |> st_transform(CRS) |>
  select(AR_ID, Dam_Name)
old <- st_read(OLD, quiet = TRUE) |> st_transform(CRS)
C_m <- st_transform(C_out, CRS)
near <- function(layer) as.numeric(apply(st_distance(dams, layer), 1, min))
dams$old_m <- round(near(old)); dams$new_m <- round(near(C_m))
chk <- st_drop_geometry(dams) |> filter(old_m <= 250 | new_m <= 250) |>
  mutate(change = case_when(old_m <= 250 & new_m <= 250 ~ "both",
                            old_m <= 250 ~ "dropped", TRUE ~ "added")) |> arrange(change, AR_ID)
write.csv(chk, file.path(OUT, "soncc_dam_checks.csv"), row.names = FALSE)
say("   removed dams within 250 m: old %d, new %d (added %d, dropped %d)",
    sum(chk$old_m <= 250), sum(chk$new_m <= 250), sum(chk$change == "added"), sum(chk$change == "dropped"))
print(chk[chk$change != "both", ], row.names = FALSE)
jcb <- dams[dams$AR_ID == "OR-096", ]
say("   OR-096 John C. Boyle: nearest habitat %s m before, %s m after", jcb$old_m, jcb$new_m)

# Regression, like for like: the 09-08 method's own full-resolution inputs
# (statewide filtered coho, its Oregon HUC8 selection) against stage A Oregon.
old_f <- st_read(file.path(dirname(OLD), "_work/coho_filtered.geojson"), quiet = TRUE) |> st_transform(CRS)
old_u <- st_read(file.path(dirname(OLD), "_work/table6_units.geojson"), quiet = TRUE) |> st_transform(CRS) |> st_make_valid()
old_full <- lines_only(suppressWarnings(st_intersection(old_f, st_union(old_u))))
a_or_km <- by_state$km[by_state$stage == "A_units_only" & by_state$state == "OR"]
say("   regression: 09-08 method at full resolution %s km vs stage A Oregon %s km", KM(old_full), a_or_km)

# Neighbouring ESUs: NMFS publishes Oregon Coast and Central California Coast
# coho critical habitat. After the ESU-extent clause, almost nothing should lie
# on either.
nm <- st_read(P("WORKING/LAYERS/nmfs/coho_line.geojson"), quiet = TRUE) |> st_transform(CRS)
on_nm <- lines_only(suppressWarnings(st_intersection(C_m, st_union(st_buffer(nm, 50)))))
say("   km within 50 m of NMFS published coho habitat (other ESUs): %s%s", if (nrow(on_nm)) KM(on_nm) else 0,
    if (nrow(on_nm)) paste0(" (", paste(unique(na.omit(on_nm$stream_name)), collapse = "; "), ")") else "")

bog <- C_m[grepl("Bogus", C_m$stream_name), ]
say("   Bogus Creek (coho, joins the Klamath just below Iron Gate) kept: %s km", if (nrow(bog)) KM(bog) else 0)

d803 <- st_read(DS803, quiet = TRUE) |> st_transform(CRS) |> st_make_valid()
ab <- d803[d803$FEATURE_ACCESS == "AB", ]
in_ab <- lines_only(suppressWarnings(st_intersection(C_m, ab)))
say("   NOAA ds803 cross-check: %s km of the result falls in 'AB' (inaccessible) HUC12s%s",
    if (nrow(in_ab)) KM(in_ab) else 0,
    if (nrow(in_ab)) paste0(": ", paste(unique(trimws(in_ab$HUC12_NAME)), collapse = "; ")) else "")
ca_ac <- d803[d803$FEATURE_ACCESS == "AC" & substr(d803$HUC12, 1, 4) == "1801", ]
hit <- lengths(st_intersects(ca_ac, C_m[C_m$state == "CA", ])) > 0
say("   California 'AC' HUC12s holding any derived reach: %d of %d (%.0f%%)",
    sum(hit), nrow(ca_ac), 100 * mean(hit))

# ---- 6. manifest -----------------------------------------------------------
js <- function(x) paste0('"', gsub('"', '\\\\"', x), '"')
kv <- function(k, v) paste0("  ", js(k), ": ", v)
sk <- function(stage, st) by_state$km[by_state$stage == stage & by_state$state == st]
writeLines(c("{",
  paste(c(
    kv("layer", js("soncc_coho_derived_fullres.gpkg (joins) / soncc_coho_derived.geojson (display)")),
    kv("what", js("Reconstructed SONCC coho critical habitat, BOTH STATES. DERIVED, not an official NMFS layer.")),
    kv("why", js("NMFS has never published spatial data for this ESU's critical habitat")),
    kv("authority", js("50 CFR 226.210; 64 FR 24049 (1999-05-05); Table 6 to Part 226, verified against eCFR 2026-09-11")),
    kv("built", js(format(Sys.Date()))),
    kv("method", js("distribution ∩ Table 6 unit ∩ listed counties ∩ ESU extent (NOAA ds803 range, Cape Blanco to Punta Gorda) − basins above the 11 Table 6 boundary dams")),
    kv("oregon_distribution", js(paste("ODFW FHD 1167_5 fhd_Coho WHERE", ODFW_WHERE))),
    kv("california_distribution", js("CDFW BIOS ds326 Coho Distribution, August 2025 (observed since 1990)")),
    kv("boundary_basins", js("WORKING/SS_BASINS/boundary_basins.geojson, from build/fetch_boundary_basins.py")),
    kv("km_OR", sprintf('{"A_units_only": %s, "B_plus_counties": %s, "C_plus_esu_extent": %s, "D_final": %s}',
                        sk("A_units_only", "OR"), sk("B_plus_counties", "OR"), sk("C_plus_esu_extent", "OR"), sk("D_minus_boundary_dams", "OR"))),
    kv("km_CA", sprintf('{"A_units_only": %s, "B_plus_counties": %s, "C_plus_esu_extent": %s, "D_final": %s}',
                        sk("A_units_only", "CA"), sk("B_plus_counties", "CA"), sk("C_plus_esu_extent", "CA"), sk("D_minus_boundary_dams", "CA"))),
    kv("reaches_final", nrow(C_out)),
    kv("caveats", paste0("[", paste(js(c(
      "DERIVED, not an official NMFS layer. Label it everywhere; never render it like the NOAA layers.",
      "Two claim types: ODFW documented-accessible distribution (OR), CDFW observed distribution (CA). claim_type on every reach.",
      "California half understates the designation: observed is a subset of accessible.",
      "Current distribution is not 1999 accessibility.",
      "Circular as an input to miles-opened: some reaches exist because a dam was removed and coho recolonised.",
      "Iron Gate is still the legal boundary although removed in 2024; the designation has not been amended.",
      "Display copy is simplified ~33 m. Joins use the full-resolution GeoPackage only (standing rule 35).")), collapse = ", "), "]"))
  ), collapse = ",\n"),
  "}"), file.path(OUT, "soncc_manifest.json"))

say("\nwrote %s reaches: %s (full res) and %s (display)", nrow(C_out), basename(fullres), basename(display))
