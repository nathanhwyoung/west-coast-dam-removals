#!/usr/bin/env Rscript
# Audit the join: why does a dam lack a species?
#
# Written 2026-09-12 for the phase 1 audit. EXTENDED TO ALL 21 SPECIES 2026-09-13,
# which PHASE2_AUDIT.md section 1 called the blocker: without it the project cannot
# answer "why is this dam blank" for any of the sixteen phase 2 species.
#
# `join_dams_to_habitat.R` reads the FILTERED presence layers, so when a dam comes out
# with no species there are FOUR quite different reasons and the join output cannot tell
# them apart:
#
#   1. the source has a feature right there, but our filter rules excluded it
#      (principle 1, evidence not a model; principle 5, resident life history)
#      -> a CAVEAT, the rule did what it was asked to
#   2. the source has a passing feature, but past the tolerance
#      -> a TOLERANCE question, and worth knowing how far past, and which of the
#         tolerance's rules it fell outside
#   3. the source has nothing near the dam at all
#      -> a genuine ABSENCE in that dataset, or a gap in it
#   4. there is NO SOURCE for that species in that state, by design
#      -> said so explicitly. Four of these are the NAMED WASHINGTON GAPS; the rest are
#         "strays only", "not native", and Californian bull trout being extirpated.
#         Without this the tool falls through to "nothing within 1 km", which reads as
#         an absence in the data when the project never sourced the species there.
#         See NO_SRC below. DECIDED (Nathan) 2026-09-13: name it, with the reason.
#
# So this script goes back to the RAW sources, unfiltered, and for each dam/species/source
# reports the nearest feature of any kind, the nearest one that would pass our filter, and
# whether each clause of the join's tolerance would have reached it.
#
# THE TOLERANCE IS THREE RULES, NOT ONE, and this tool computes all three (DECIDED by
# Nathan 2026-09-13). It used to test only the base 75 m, so a passing feature 300 m away
# on a name-equal stream was reported as a tolerance failure when the join would in fact
# have matched it: incomplete in gap mode, and flatly contradictory in named-dam mode.
#   base BASE_M | same-stream to EXT_M under name equality (rule 40) | ranges by
#   containment or within BASE_M (rule 41)
#
# WHERE THE RULES LIVE. The shared values and helpers come from `rules_shared.R`, so the
# evidence vocabulary (rule 38), the federal scope (39), the name normaliser (40), the
# tolerance constants (41) and the claim grades cannot drift from the build again. Three
# of them already had by 2026-09-13, and every drift was invisible because both copies
# ran clean and returned plausible answers; the history is in that file's header.
#
# THE PER-SOURCE FILTER PREDICATES BELOW ARE STILL COPIES of the rules in
# `make_presence_layers.R`, because the build pushes them into SQL for speed while this
# script needs them as R predicates over unfiltered features. COPY THEM, NEVER REINVENT
# THEM: a predicate that drifts makes this tool quietly lie about why a dam is blank,
# and that is the single thing most likely to go wrong here.
#
# It writes nothing to the working sheet and nothing to the join outputs.
#
# USAGE
#   Rscript build/audit_join_gaps.R                # the ESA-without-presence gaps
#   Rscript build/audit_join_gaps.R WA-004 OR-036  # named dams instead
# Naming dams audits them against all 21 species, so it reads every source and takes a
# few minutes. The no-argument gap mode reads only what the gaps ask for.
#
# OUTPUT, WORKING/JOIN/audit/
#   join_gap_audit.csv   one row per dam/species/source
#   join_gap_audit.txt   the readable version, grouped by dam

suppressMessages({library(sf); library(dplyr)})
sf_use_s2(FALSE)

args <- commandArgs(trailingOnly = FALSE)
HERE <- dirname(normalizePath(sub("^--file=", "", args[grep("^--file=", args)])))
ROOT <- normalizePath(file.path(HERE, "..", ".."))
P <- function(...) file.path(ROOT, ...)
ASK <- commandArgs(trailingOnly = TRUE)

# BASE_M, EXT_M, EVIDENCE_VALUES, FEDERAL, PROJECT_STATES and the name helpers
# (NOISE / trib_cut / toks / same_stream) all come from here.
source(file.path(HERE, "rules_shared.R"))

CRS    <- 5070
# How far out to look before calling it an absence. Comfortably past EXT_M (500 m), so
# the candidate set covers every clause of the tolerance and not just the base rule.
NEAR_M <- 1000

SHEET <- P("WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv")
JOIN  <- P("WORKING/JOIN")
OUT   <- file.path(JOIN, "audit")

FHD    <- P("_OLD/DOCS/DAM_DATA/ODFW/ODFW_1167_5_FHD_Publication.gdb/FHD_Publication_Streams.gdb")
SWIFD  <- P("WORKING/WDFW/SWIFD_WDFWFishDistribution_2026-09-11/WDFWFishDistribution.gdb")
LAMNW  <- P("WORKING/USFWS_LAMPREY/usfws_lamprey_NW_distribution_2022_2026-09-11.geojson")
CDFW   <- function(ds) P(sprintf("WORKING/CDFW/%s_2026-09-11/%s.gdb", ds, ds))
PISCES <- function(f) P("WORKING/pisces_2.0.4_all_ranges_shp_and_png", f)

say <- function(...) cat(sprintf(...), "\n", sep = "")

# All 21 species, spelled exactly as `make_presence_layers.R` labels them, because the
# join's presence labels are those strings and the gap comparison is made on them.
SPECIES <- c(
  # phase 1
  "Chinook salmon", "Coho salmon", "Steelhead", "Pacific lamprey",
  "Coastal cutthroat trout",
  # phase 2
  "Chum salmon", "Sockeye salmon", "Pink salmon", "Western river lamprey",
  "Green sturgeon", "White sturgeon", "Eulachon", "Bull trout", "Lost River sucker",
  "Shortnose sucker", "Klamath largescale sucker", "Redband trout",
  "Westslope cutthroat trout", "Largescale sucker", "Bridgelip sucker",
  "Mountain whitefish")

# ---- which dams ------------------------------------------------------------
sheet <- read.csv(SHEET, colClasses = "character", fileEncoding = "UTF-8-BOM")
has <- function(v) !is.na(v) & nzchar(trimws(v))
# River_DRP is a correction to American Rivers' own river name, used for the same-stream
# rule only. Applied here for the same reason the join applies it: without it this tool
# would test name agreement against a different name than the join did (OR-066, whose
# River reads "South Fork Little Butte" while the dam sits 5 m from South Fork Big Butte
# Creek). Tolerated as absent so this still runs against an older copy of the sheet.
if (!"River_DRP" %in% names(sheet)) sheet$River_DRP <- ""
dams_all <- sheet |>
  filter(!has(Duplicate_Of_DRP), !has(Coordinate_Void_DRP)) |>
  mutate(lat = as.numeric(ifelse(has(Latitude_DRP), Latitude_DRP, Latitude)),
         lon = as.numeric(ifelse(has(Longitude_DRP), Longitude_DRP, Longitude)),
         River = ifelse(has(River_DRP), River_DRP, River)) |>
  filter(!is.na(lat), !is.na(lon)) |>
  st_as_sf(coords = c("lon", "lat"), crs = 4326) |> st_transform(CRS)

matches <- read.csv(file.path(JOIN, "dam_species_matches.csv"), colClasses = "character")

# ESA label -> presence species. NMFS labels are LISTENTITY verbatim ("Salmon, Chinook
# [Puget Sound ESU]"); USFWS labels are title-cased COMNAME ("Bull Trout"); the SONCC
# layer is our own derived label.
#
# EXTENDED 2026-09-13 from the three phase 1 mappings to every ESA entity that also
# exists in the presence tier, which is what lets a phase 2 gap be found at all. The
# rest of the USFWS nine (tidewater goby, Warner sucker, delta smelt, Santa Ana sucker,
# Owens tui chub, Little Kern golden trout) are ESA-only BY DESIGN: barrier passage is
# not the mechanism, or there is no presence source. They map to NA and are dropped,
# rather than being reported as dams missing a species they were never given.
esa_species <- function(lbl) {
  case_when(
    grepl("^Salmon, Chinook",           lbl) ~ "Chinook salmon",
    grepl("^Salmon, coho|^Coho salmon", lbl) ~ "Coho salmon",
    grepl("^Salmon, chum",              lbl) ~ "Chum salmon",
    grepl("^Salmon, sockeye",           lbl) ~ "Sockeye salmon",
    grepl("^Steelhead",                 lbl) ~ "Steelhead",
    grepl("^Eulachon",                  lbl) ~ "Eulachon",
    grepl("^Sturgeon, green",           lbl) ~ "Green sturgeon",
    grepl("^Bull Trout$",               lbl) ~ "Bull trout",
    grepl("^Lost River Sucker$",        lbl) ~ "Lost River sucker",
    grepl("^Shortnose Sucker$",         lbl) ~ "Shortnose sucker",
    TRUE                                     ~ NA_character_)
}
want <- matches |> filter(kind == "ESA") |> mutate(sp = esa_species(label)) |>
  filter(!is.na(sp)) |> distinct(AR_ID, sp)
got <- matches |> filter(kind == "presence") |> distinct(AR_ID, sp = label)
gaps <- anti_join(want, got, by = c("AR_ID", "sp"))

if (length(ASK)) {
  targets <- expand.grid(AR_ID = ASK, sp = SPECIES, stringsAsFactors = FALSE)
  say("auditing %d named dams against all %d species", length(ASK), length(SPECIES))
} else {
  targets <- gaps
  say("auditing %d ESA-without-presence gaps across %d dams",
      nrow(gaps), n_distinct(gaps$AR_ID))
}
dams <- dams_all[dams_all$AR_ID %in% targets$AR_ID, ]
if (!nrow(dams)) stop("no mapped dams matched those AR_IDs")

# ---- raw sources -----------------------------------------------------------
# Each entry: the layer as published, plus `pass`, the filter predicate from
# `make_presence_layers.R`, and `attrs`, the fields that predicate reads.
#
# `st` is the source's scope: one of PROJECT_STATES, or FEDERAL for a federal layer used
# across the whole three-state extent (rule 39).
rd <- function(dsn, layer = NULL, query = NULL) {
  if (!is.null(query)) st_read(dsn, query = query, quiet = TRUE)
  else if (!is.null(layer)) st_read(dsn, layer = layer, quiet = TRUE)
  else st_read(dsn, quiet = TRUE)   # single-layer files: passing layer = NULL errors
}
kv <- function(df, cols) {
  cols <- intersect(cols, names(df))
  if (!length(cols)) return(rep("", nrow(df)))
  do.call(paste, c(lapply(cols, function(k) paste0(k, "=", df[[k]])), sep = "; "))
}

# Ported from `east_of_cascades()` in make_presence_layers.R, as a per-feature PREDICATE
# rather than a subset, because `pass` returns a logical vector. Same test: centroid
# longitude east of 121 W, the Cascade crest. Used only for the Washington redband
# inference (SWIFD carries no redband label, so east-side Rainbow Trout with a migratory
# life history is read as Columbia River redband). Without it this tool would report
# redband candidates west of the Cascades that the build would never accept.
# st_zm() first: SWIFD geometry is a MEASURED line string (XYM) and GEOS rejects those.
is_east <- function(x) {
  if (!nrow(x)) return(logical(0))
  g <- st_transform(st_zm(st_geometry(x)), 4326)
  lon <- suppressWarnings(st_coordinates(st_centroid(g)))[, 1]
  !is.na(lon) & lon > -121
}

# Constructors, so each entry reads as the same rule the build states in SQL, and so the
# repetition across 15 Oregon layers cannot hide a typo. Each call gets its own
# environment, so `layer` and `sp_value` are captured correctly.
odfw_src <- function(sp, layer, resident_rule = FALSE) {
  list(sp = sp, st = "OR", name = paste("ODFW", layer),
       get = function() rd(FHD, layer),
       # build: fhdUseTy <> 'Historical' [AND fhdLifeHst <> 'Resident']
       pass = if (resident_rule)
                function(x) x$fhdUseTy != "Historical" & x$fhdLifeHst != "Resident"
              else function(x) x$fhdUseTy != "Historical",
       attrs = c("fhdUseTy", "fhdRun", "fhdLifeHst", "fhdAccess", "fhdBasis"),
       stream = "fhdStNm")
}
swifd_src <- function(sp, sp_value, extra = NULL, east = FALSE) {
  list(sp = sp, st = "WA", name = paste("WDFW SWIFD", sp_value),
       get = function() rd(SWIFD, query = sprintf(
         "SELECT * FROM SWIFD WHERE SPECIES = '%s'", sp_value)),
       # build: DISTTYPE_DESC IN EVIDENCE_SQL [AND <extra>], then east_of_cascades()
       pass = function(x) {
         ok <- x$DISTTYPE_DESC %in% EVIDENCE_VALUES
         if (!is.null(extra)) ok <- ok & extra(x)
         if (east) ok <- ok & is_east(x)
         ok
       },
       attrs = c("DISTTYPE_DESC", "USETYPE_DESC", "LIFEHIST_DESC", "RUNTIME_DESC"),
       stream = "LLID_STRM_NAME")
}
not_resident <- function(x) x$LIFEHIST_DESC != "Resident"
migratory    <- function(x) x$LIFEHIST_DESC %in% c("Fluvial", "Adfluvial")

SRC <- c(list(
  # ---- California, and the federal layers -----------------------------------
  list(sp = "Chinook salmon", st = "CA", name = "NOAA ds981 CA Coastal Chinook",
       get = function() rd(CDFW("ds981"), "ds981"),
       pass = function(x) x$PRESENCE %in% c("Yes", "Likely"),
       attrs = c("PRESENCE", "ESU"), stream = NA),
  list(sp = "Chinook salmon", st = "CA", name = "NOAA ds982 CV spring Chinook",
       get = function() rd(CDFW("ds982"), "ds982"),
       pass = function(x) rep(TRUE, nrow(x)), attrs = c("HAB_UTIL"), stream = NA),
  list(sp = "Coho salmon", st = "CA", name = "CDFW ds326 coho",
       get = function() rd(CDFW("ds326"), "ds326"),
       pass = function(x) rep(TRUE, nrow(x)), attrs = c("DFGWATERID"), stream = "Stream_Name"),
  list(sp = "Steelhead", st = "CA", name = "CDFW ds340 winter steelhead",
       get = function() rd(CDFW("ds340"), "ds340"),
       pass = function(x) rep(TRUE, nrow(x)), attrs = c("Early_Yr", "Late_Yr"),
       stream = "GNIS_Name"),
  list(sp = "Steelhead", st = "CA", name = "CDFW ds341 summer steelhead",
       get = function() rd(CDFW("ds341"), "ds341"),
       pass = function(x) !is.na(x$Late_Yr) & x$Late_Yr >= 1990,
       attrs = c("Early_Yr", "Late_Yr"), stream = "GNIS_Name"),
  # FEDERAL (rule 39). Both USFWS lamprey layers are used across the whole project
  # extent, not clipped to one state. Until 2026-09-13 this script scoped them to WA and
  # CA respectively, so it was blind to Oregon lamprey from USFWS while the build was
  # using it: the drift that rule 39 exists to prevent. Read unclipped here, which is
  # harmless at NEAR_M = 1 km from a west-coast dam.
  list(sp = "Pacific lamprey", st = FEDERAL, name = "USFWS NW lamprey 2022 (federal)",
       get = function() rd(LAMNW),
       pass = function(x) !(x$Use_Type %in% c("Historical", "Historic")) &
                          !(x$Historical_Data %in% "Y") & !is.na(x$Basis) & x$Basis != "None",
       attrs = c("Basis", "Use_Type", "Origin"), stream = "Stream_Name"),
  list(sp = "Pacific lamprey", st = FEDERAL, name = "USFWS ds2673 lamprey (federal)",
       get = function() rd(CDFW("ds2673"), "ds2673"),
       pass = function(x) x$DistType == "Current",
       attrs = c("DistType", "HUC8Name"), stream = "Name")),

  # ---- Oregon, ODFW FHD ------------------------------------------------------
  # `fhdLifeHst <> 'Resident'` (principle 5) on coastal cutthroat, bull trout, redband
  # and westslope cutthroat only, exactly as the build has it.
  list(
  odfw_src("Chinook salmon",            "fhd_ChinookFall"),
  odfw_src("Chinook salmon",            "fhd_ChinookSpring"),
  odfw_src("Coho salmon",               "fhd_Coho"),
  odfw_src("Steelhead",                 "fhd_SteelheadWinter"),
  odfw_src("Steelhead",                 "fhd_SteelheadSummer"),
  odfw_src("Pacific lamprey",           "fhd_Lamprey_Pacific"),
  odfw_src("Coastal cutthroat trout",   "fhd_Cutthroat_Coastal",        resident_rule = TRUE),
  odfw_src("Chum salmon",               "fhd_Chum"),
  odfw_src("Sockeye salmon",            "fhd_Sockeye"),
  odfw_src("Western river lamprey",     "fhd_Lamprey_WesternRiver"),
  odfw_src("Green sturgeon",            "fhd_SturgeonGreen"),
  odfw_src("White sturgeon",            "fhd_SturgeonWhite"),
  odfw_src("Eulachon",                  "fhd_Eulachon"),
  odfw_src("Bull trout",                "fhd_Bulltrout",                resident_rule = TRUE),
  odfw_src("Lost River sucker",         "fhd_Sucker_LostRiver"),
  odfw_src("Shortnose sucker",          "fhd_Sucker_Shortnose"),
  odfw_src("Klamath largescale sucker", "fhd_Sucker_KlamathLargescale"),
  odfw_src("Redband trout",             "fhd_Redband",                  resident_rule = TRUE),
  odfw_src("Westslope cutthroat trout", "fhd_Cutthroat_Westslope",      resident_rule = TRUE),
  odfw_src("Largescale sucker",         "fhd_Sucker_Largescale"),
  odfw_src("Bridgelip sucker",          "fhd_Sucker_Bridgelip"),
  odfw_src("Mountain whitefish",        "fhd_MountainWhitefish"),

  # ---- Washington, WDFW SWIFD ------------------------------------------------
  # SWIFD has no lamprey, eulachon, largescale or bridgelip sucker: those are the four
  # named Washington gaps and are handled by NO_SRC, not here.
  swifd_src("Chinook salmon",            "Chinook Salmon"),
  swifd_src("Coho salmon",               "Coho Salmon"),
  swifd_src("Steelhead",                 "Steelhead Trout"),
  swifd_src("Coastal cutthroat trout",   "Cutthroat Trout",           extra = not_resident),
  swifd_src("Chum salmon",               "Chum Salmon"),
  swifd_src("Sockeye salmon",            "Sockeye Salmon"),
  swifd_src("Pink salmon",               "Pink Salmon"),
  swifd_src("Green sturgeon",            "Green Sturgeon"),
  swifd_src("White sturgeon",            "White Sturgeon"),
  swifd_src("Bull trout",                "Bull Trout",                extra = not_resident),
  swifd_src("Westslope cutthroat trout", "Westslope Cutthroat Trout", extra = not_resident),
  swifd_src("Mountain whitefish",        "Mountain Whitefish"),
  # THE INFERENCE, and the one entry that is not a plain SWIFD query: Rainbow Trout,
  # fluvial or adfluvial, east of the Cascades. Graded `inferred` in the build.
  swifd_src("Redband trout",             "Rainbow Trout",             extra = migratory,
            east = TRUE)))

# PISCES ranges are polygons matched by containment OR within BASE_M (rule 41), so they
# are reported separately: inside, within the tolerance, or outside and by how far.
#
# TWO SPELLING TRAPS, and they nearly cost two sources: river lamprey is filed as
# `Lampetra_ayersi`, not the accepted `ayresii`, and Lost River sucker as
# `Catostomus_luxatus`, not the accepted `Deltistes luxatus`. Searching the accepted name
# returns nothing, which reads as "no source exists" rather than "look under the old
# name". Also PISCES `SOM09` is COASTAL RAINBOW and is NOT redband; California's two
# redbands are `SOM10` McCloud and `SOM11` Goose Lake.
PISCES_SRC <- list(
  list(sp = "Chinook salmon", files = c(
       "Oncorhynchus_tshawytscha_SOT01_extant_1.shp", "Oncorhynchus_tshawytscha_SOT02_extant_1.shp",
       "Oncorhynchus_tshawytscha_SOT03_extant_1.shp", "Oncorhynchus_tshawytscha_SOT05_extant_1.shp",
       "Oncorhynchus_tshawytscha_SOT07_extant_1.shp", "Oncorhynchus_tshawytscha_SOT08_extant_1.shp")),
  list(sp = "Coastal cutthroat trout",   files = "Oncorhynchus_clarki_clarki_SOC01_extant_1.shp"),
  list(sp = "Western river lamprey",     files = "Lampetra_ayersi_PLA01_extant_1.shp"),
  list(sp = "Green sturgeon",            files = c("Acipenser_medirostris_AAM01_extant_1.shp",
                                                   "Acipenser_medirostris_AAM02_extant_1.shp")),
  list(sp = "White sturgeon",            files = "Acipenser_transmontanus_AAT01_extant_1.shp"),
  list(sp = "Eulachon",                  files = "Thaleichthys_pacificus_OTP01_extant_1.shp"),
  list(sp = "Lost River sucker",         files = "Catostomus_luxatus_CCL01_extant_1.shp"),
  list(sp = "Shortnose sucker",          files = "Chasmistes_brevirostris_CCB01_extant_1.shp"),
  list(sp = "Klamath largescale sucker", files = "Catostomus_snyderi_CCS01_extant_1.shp"),
  list(sp = "Redband trout",             files = c("Oncorhynchus_mykiss_stonei_SOM10_extant_1.shp",
                                                   "Oncorhynchus_mykiss_subspecies_SOM11_extant_1.shp")),
  list(sp = "Mountain whitefish",        files = "Prosopium_williamsoni_SPW01_extant_1.shp"))

# ---- species with no source in a state, by design --------------------------
# DECIDED (Nathan) 2026-09-13: name these, with the reason. Reasons are quoted from
# PROCESS stage 6's phase 2 table, not written here, so the tool cannot invent a
# biogeographic claim the project never made.
#
# The FOUR NAMED WASHINGTON GAPS are first. The rest follow from "strays only" (Nathan,
# 2026-09-11), from a species not being native, or from Californian bull trout being
# extirpated. Any species/state pair missing from BOTH the source lists above AND this
# table falls back to a neutral message rather than to a claim.
NO_SRC <- list(
  c("Western river lamprey",     "WA", "NAMED GAP: data-poor everywhere, no WDFW layer"),
  c("Eulachon",                  "WA", paste("NAMED GAP, decided 2026-09-12: not a proxy built from",
                                             "its own ESA critical habitat, which would make presence",
                                             "a restatement of the designation and collapse rule 17.",
                                             "Eulachon still reaches WA dams through the ESA tier")),
  c("Largescale sucker",         "WA", paste("NAMED GAP: WDFW's layer is modelled occupancy,",
                                             "regional and undocumented, so it fails principle 1")),
  c("Bridgelip sucker",          "WA", paste("NAMED GAP: WDFW's layer is modelled occupancy,",
                                             "regional and undocumented, so it fails principle 1")),
  c("Chum salmon",               "CA", "strays only, no California source"),
  c("Sockeye salmon",            "CA", "strays only, no California source"),
  c("Pink salmon",               "OR", "strays only, no Oregon source"),
  c("Pink salmon",               "CA", "strays only, no California source"),
  c("Bull trout",                "CA", "extirpated in California (McCloud River, not seen since the mid-1970s)"),
  c("Lost River sucker",         "WA", "not native to Washington"),
  c("Shortnose sucker",          "WA", "not native to Washington"),
  c("Klamath largescale sucker", "WA", "not native to Washington"),
  c("Westslope cutthroat trout", "CA", "not native to California"),
  c("Largescale sucker",         "CA", "not native to California"),
  c("Bridgelip sucker",          "CA", "not native to California"))

# ---- the measurement -------------------------------------------------------
rows <- list()
# Only mapped dams are audited. Filtering here rather than later matters because the
# NO_SRC block below works off `need`: without it, an AR_ID that is not a mapped dam
# reaches that block with State = NA, is kept by the anti_join (NA matches nothing), and
# emits a no-source row for a dam that does not exist. NOTE ONE AR_ID CONTAINS A SPACE,
# `OR-087 to OR-088`, so it must be quoted when passed as a shell argument.
need <- targets |> left_join(st_drop_geometry(dams_all)[, c("AR_ID", "State", "River")],
                             by = "AR_ID") |>
  filter(AR_ID %in% dams$AR_ID)
missed <- setdiff(unique(targets$AR_ID), dams$AR_ID)
if (length(missed))
  say("  NOT AUDITED, not a mapped dam: %s", paste(missed, collapse = ", "))
blank <- function(...) data.frame(..., stringsAsFactors = FALSE)

for (s in SRC) {
  # FEDERAL sources serve every state (rule 39); a state source serves only its own.
  tg <- need |> filter(sp == s$sp, identical(s$st, FEDERAL) | State == s$st)
  if (!nrow(tg)) next
  d <- dams[dams$AR_ID %in% tg$AR_ID, ]
  if (!nrow(d)) next
  say("  %-8s %-34s %s", s$st, s$name, s$sp)
  x <- tryCatch(st_zm(s$get()) |> st_transform(CRS), error = function(e) NULL)
  if (is.null(x) || !nrow(x)) { say("      (source unreadable or empty)"); next }
  ok <- s$pass(x); ok[is.na(ok)] <- FALSE
  st_nm <- if (!is.na(s$stream) && s$stream %in% names(x)) as.character(x[[s$stream]])
           else rep(NA_character_, nrow(x))
  at <- kv(st_drop_geometry(x), s$attrs)
  near <- st_is_within_distance(d, x, NEAR_M)
  dtok <- toks(trib_cut(d$River))
  for (i in seq_len(nrow(d))) {
    k <- near[[i]]
    none <- blank(AR_ID = d$AR_ID[i], dam = d$Dam_Name[i], state = d$State[i],
      species = s$sp, source = s$name, nearest_m = NA_real_, nearest_passes = NA,
      nearest_attrs = "", nearest_stream = NA_character_, nearest_passing_m = NA_real_,
      passing_stream = NA_character_, same_stream_m = NA_real_, name_equal = NA,
      rule_base = "no", rule_same_stream = "no", verdict = "nothing within 1 km")
    if (!length(k)) { rows[[length(rows) + 1]] <- none; next }
    dist <- as.numeric(st_distance(d[i, ], x[k, ]))
    # a degenerate geometry can give NA; drop those rather than let them poison the min
    good <- !is.na(dist)
    if (!any(good)) { rows[[length(rows) + 1]] <- none; next }
    k <- k[good]; dist <- dist[good]

    j  <- k[which.min(dist)]; dj <- min(dist)          # nearest feature of any kind
    kp <- k[ok[k]]; dpv <- dist[ok[k]]                 # only the ones that pass
    dp <- if (length(kp)) min(dpv) else NA_real_
    jp <- if (length(kp)) kp[which.min(dpv)] else NA

    # THE TOLERANCE, all three clauses. `same_stream` is rule 40 from rules_shared.R:
    # the normalised names must be EQUAL, so a tributary cannot inherit its main stem.
    eq <- logical(0); ds <- NA_real_
    if (length(kp)) {
      named <- !is.na(st_nm[kp]) & nzchar(st_nm[kp])
      eq <- rep(FALSE, length(kp))
      if (any(named)) eq[named] <- same_stream(dtok[[i]], st_nm[kp][named])
      if (any(eq)) ds <- min(dpv[eq])
    }
    hit_base <- !is.na(dp) && dp <= BASE_M
    hit_same <- !is.na(ds) && ds <= EXT_M
    verdict <- if (hit_base) "MATCH: base 75 m"
      else if (hit_same) sprintf("MATCH: same-stream <=%d m (%.0f m)", EXT_M, ds)
      else if (!is.na(dp)) sprintf("tolerance: nearest passing %.0f m, past %s", dp,
                                   if (any(eq)) "both rules" else "the base rule, and no name-equal stream")
      else if (dj <= BASE_M) "excluded by the filter rule"
      else "nothing passing, nothing near"
    rows[[length(rows) + 1]] <- blank(AR_ID = d$AR_ID[i], dam = d$Dam_Name[i],
      state = d$State[i], species = s$sp, source = s$name,
      nearest_m = round(dj), nearest_passes = ok[j], nearest_attrs = at[j],
      nearest_stream = st_nm[j], nearest_passing_m = round(dp),
      passing_stream = if (is.na(jp)) NA_character_ else st_nm[jp],
      same_stream_m = round(ds), name_equal = length(eq) > 0 && any(eq),
      rule_base = if (hit_base) "YES" else "no",
      rule_same_stream = if (hit_same) "YES" else "no", verdict = verdict)
  }
}

for (s in PISCES_SRC) {
  tg <- need |> filter(sp == s$sp, State == "CA")
  if (!nrow(tg)) next
  d <- dams[dams$AR_ID %in% tg$AR_ID, ]
  if (!nrow(d)) next
  for (f in s$files) {
    if (!file.exists(PISCES(f))) { say("      (missing PISCES file: %s)", f); next }
    x <- st_read(PISCES(f), quiet = TRUE) |> distinct(HUC_12, .keep_all = TRUE) |>
      st_transform(CRS)
    if (!nrow(x)) next
    say("  %-8s %-34s %s", "CA", paste("PISCES", sub("_extant_1.shp", "", f)), s$sp)
    inside <- lengths(st_intersects(d, x)) > 0
    dist <- suppressWarnings(apply(st_distance(d, x), 1, min))
    for (i in seq_len(nrow(d))) {
      dm <- as.numeric(dist[i])
      # Rule 41: containment OR within BASE_M of the edge. Reporting a bare
      # inside/outside here was the third drift found on 2026-09-13, and it would have
      # called Iron Gate (0.238 m outside) a miss when the join matches it.
      verdict <- if (inside[i]) "MATCH: inside HUC12 range"
        else if (dm <= BASE_M) sprintf("MATCH: HUC12 range within %d m (rule 41, %.2f m)", BASE_M, dm)
        else sprintf("outside the range by %.0f m", dm)
      rows[[length(rows) + 1]] <- blank(AR_ID = d$AR_ID[i], dam = d$Dam_Name[i],
        state = "CA", species = s$sp, source = paste("PISCES", sub("_extant_1.shp", "", f)),
        nearest_m = round(dm), nearest_passes = TRUE, nearest_attrs = "HUC12 range",
        nearest_stream = NA_character_, nearest_passing_m = round(dm),
        passing_stream = NA_character_, same_stream_m = NA_real_, name_equal = NA,
        rule_base = if (inside[i] || dm <= BASE_M) "YES" else "no",
        rule_same_stream = "n/a (range)", verdict = verdict)
    }
  }
}

# ---- no source at all, by design -------------------------------------------
covered <- bind_rows(
  bind_rows(lapply(SRC, function(s) if (identical(s$st, FEDERAL))
    blank(sp = s$sp, st = PROJECT_STATES) else blank(sp = s$sp, st = s$st))),
  bind_rows(lapply(PISCES_SRC, function(s) blank(sp = s$sp, st = "CA")))) |> distinct()

uncov <- need |> distinct(AR_ID, sp, State) |>
  anti_join(covered, by = c("sp" = "sp", "State" = "st")) |>
  left_join(st_drop_geometry(dams_all)[, c("AR_ID", "Dam_Name")], by = "AR_ID")
if (nrow(uncov)) {
  say("  %d dam/species pairs have NO SOURCE for that state, by design", nrow(uncov))
  for (i in seq_len(nrow(uncov))) {
    hit <- Filter(function(r) r[1] == uncov$sp[i] && r[2] == uncov$State[i], NO_SRC)
    why <- if (length(hit)) hit[[1]][3]
           else "no source for this state in the build (see PROCESS stage 6)"
    rows[[length(rows) + 1]] <- blank(AR_ID = uncov$AR_ID[i], dam = uncov$Dam_Name[i],
      state = uncov$State[i], species = uncov$sp[i], source = "(none)",
      nearest_m = NA_real_, nearest_passes = NA, nearest_attrs = "",
      nearest_stream = NA_character_, nearest_passing_m = NA_real_,
      passing_stream = NA_character_, same_stream_m = NA_real_, name_equal = NA,
      rule_base = "n/a", rule_same_stream = "n/a",
      verdict = sprintf("NO %s SOURCE, by design: %s", uncov$State[i], why))
  }
}

res <- bind_rows(rows) |> arrange(AR_ID, species, nearest_m)
dir.create(OUT, showWarnings = FALSE, recursive = TRUE)
write.csv(res, file.path(OUT, "join_gap_audit.csv"), row.names = FALSE)

txt <- capture.output({
  cat(sprintf("Join gap audit, %s. All %d species.\n", format(Sys.Date()), length(SPECIES)))
  cat(sprintf("Raw sources, UNFILTERED, within %d m. Join tolerance: base %d m, same-stream <=%d m\n",
              NEAR_M, BASE_M, EXT_M))
  cat("under name equality (rule 40), ranges by containment or within the base (rule 41).\n\n")
  for (id in unique(res$AR_ID)) {
    r <- res[res$AR_ID == id, ]
    dd <- dams[dams$AR_ID == id, ]
    if (!nrow(dd)) next
    # Coordinate printed as lat, lon and READ FROM THE SHEET, never recalled: standing
    # rule 42, so a named dam in this output can be gone and looked at directly.
    ll <- rev(st_coordinates(st_transform(dd, 4326))[1, ])
    cat(sprintf("%s  %s  (%s, %s, river as recorded: %s)\n", id, r$dam[1], r$state[1],
                paste(sprintf("%.5f", ll), collapse = ", "),
                ifelse(is.na(dd$River[1]) || !nzchar(dd$River[1]), "(blank)", dd$River[1])))
    for (k in seq_len(nrow(r))) {
      cat(sprintf("   %-26s %-34s %s\n", r$species[k], r$source[k], r$verdict[k]))
      if (!is.na(r$nearest_m[k])) {
        cat(sprintf("       nearest %s m%s  %s%s\n", r$nearest_m[k],
                    ifelse(isTRUE(r$nearest_passes[k]), " (passes)", " (EXCLUDED)"),
                    ifelse(is.na(r$nearest_stream[k]), "",
                           paste0("on ", r$nearest_stream[k], "  ")), r$nearest_attrs[k]))
        # The tolerance, rule by rule, so a blank can never be blamed on the base rule
        # when the same-stream extension was the clause that actually decided it.
        if (!is.na(r$nearest_passing_m[k]))
          cat(sprintf("       base %d m: %s   |   same-stream <=%d m: %s%s\n", BASE_M,
                      r$rule_base[k], EXT_M, r$rule_same_stream[k],
                      if (identical(r$rule_same_stream[k], "n/a (range)")) ""
                      else if (isTRUE(r$name_equal[k]))
                        sprintf(" (name equal, nearest such %s m)", r$same_stream_m[k])
                      else " (no name-equal stream carrying it)"))
      }
    }
    cat("\n")
  }
})
writeLines(txt, file.path(OUT, "join_gap_audit.txt"))
cat(paste(txt, collapse = "\n"), "\n")
say("wrote %s (%d rows)", file.path("WORKING/JOIN/audit", "join_gap_audit.csv"), nrow(res))
