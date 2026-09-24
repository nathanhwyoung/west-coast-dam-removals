#!/usr/bin/env Rscript
# Shared rule definitions: the values and helpers that MORE THAN ONE script needs.
#
# Created 2026-09-13. Sourced by `make_presence_layers.R`, `join_dams_to_habitat.R`
# and `audit_join_gaps.R`.
#
# WHY THIS FILE EXISTS. Standing rules 38, 39 and 41 were each decided once, on
# 2026-09-12, and each was implemented in the build but not in the audit tool, which
# held its own copy. All three drifted, and the drift was invisible because both
# copies ran without error and returned plausible answers:
#
#   - rule 38: the audit still listed four SWIFD evidence strings while the build
#     accepted six, so 485 `Artificial -` features read as excluded when they pass
#   - rule 39: the audit clipped both USFWS lamprey layers to one state each while
#     the build used them federally, so Oregon lamprey was invisible to the audit
#   - rule 41: the audit tested containment strictly while the join carries the
#     75 m tolerance into ranges, so it called Iron Gate outside a range the join
#     matches
#
# That is the same failure mode rule 38 itself describes: a decision made by
# omission, leaving no trace. A rule that lives in two files has two chances to be
# wrong and no way to notice. DECIDED (Nathan) 2026-09-13: fix the cause, not the
# three instances.
#
# WHAT BELONGS HERE: a value or helper that is literally the same thing in more than
# one script, and that a standing rule governs.
#
# WHAT DOES NOT: the per-source filter predicates. The build pushes them into SQL
# (`fhdUseTy <> 'Historical'`) for speed on 40,000-reach layers, while the audit needs
# them as R predicates over already-loaded features, because its whole job is to read
# the sources UNFILTERED and then say what would have passed. Those are two genuinely
# different forms of the same rule, so they stay duplicated, and the warning at the top
# of `audit_join_gaps.R` stands: copy them, never reinvent them.

# ---- rule 38: an evidence GRADE plus an optional QUALIFIER ------------------
# SWIFD's DISTTYPE_DESC is TWO facts in one string, and enumerating whole strings
# conflated them (found in the 2026-09-12 audit, PHASE1_AUDIT.md section 2).
#   grades:     Documented / Presumed carry evidence (principle 1).
#               Potential / Modeled / Gradient Accessible are models, so they are out.
#   qualifiers: Transported, fish trucked past a barrier, IS presence (principle 3).
#               Artificial, habitat the species did not historically occupy, opened by
#               a fish ladder or a ditch, IS presence: WDFW's own definition of code 13
#               says it "meets the basic criteria for Documented". DECIDED by Nathan
#               2026-09-12.
#               Historic is out, which is fixed rather than a choice.
# Note `Artificial - Potential` is therefore still excluded: the grade is what decides.
#
# Built by combination rather than typed out, which is the point of rule 38: a new
# qualifier is one entry here and lands everywhere on purpose.
GRADES     <- c("Documented", "Presumed")
QUALIFIERS <- c("", "Transported - ", "Artificial - ")

# Two forms of the same list, deliberately named apart so neither can be mistaken for
# the other. EVIDENCE_VALUES is the character vector, for `%in%` over loaded features;
# EVIDENCE_SQL is the parenthesised fragment, for `... DISTTYPE_DESC IN %s ...`.
# (An earlier single `EVIDENCE` meant the SQL string in one script and would have had
# to mean the vector in another: same name, two meanings, which is the trap rule 38 is
# about.)
EVIDENCE_VALUES <- paste0(rep(QUALIFIERS, each = length(GRADES)), GRADES)
EVIDENCE_SQL    <- sprintf("(%s)", paste(sprintf("'%s'", EVIDENCE_VALUES), collapse = ","))

# ---- rule 39: the state seam binds state agency sources, not federal ones ---
# Stage 6 says a source's records outside its own state are not used, which is right
# for ODFW, WDFW and CDFW, each authoritative inside one state and not beyond it. It is
# meaningless for a federal layer, which has no own state: applied literally it clipped
# the USFWS Pacific lamprey layer to Washington and discarded its 1,897 Oregon features,
# 72% of the file. DECIDED by Nathan 2026-09-12.
#
# A source's scope is therefore either one of PROJECT_STATES or the marker FEDERAL,
# which means the whole three-state project extent.
FEDERAL        <- "US"
PROJECT_STATES <- c("CA", "OR", "WA")

# ---- the join tolerance, and rule 41 ---------------------------------------
# DECIDED by Nathan 2026-09-11 (PROCESS.md stage 6), three clauses:
#   1. base BASE_M;
#   2. same-stream extension to EXT_M, only where the source carries a stream name and
#      that name matches the dam's river (see `same_stream` below);
#   3. PISCES HUC12 ranges match by containment OR within BASE_M of the polygon edge.
#      AMENDED 2026-09-12 (rule 41): the original clause exempted ranges from the
#      tolerance, on the reasoning that the 75 m budget is built for point-to-line
#      error. Two of its three components are line-specific, but the third, COORDINATE
#      ERROR (40 m at the 75th percentile, 116 m at the 90th), applies to the dam point
#      whatever it is tested against. It is structural, not bad luck: HUC12 boundaries
#      are drainage divides, a subwatershed's outlet is a point on the mainstem, and
#      that is exactly where dams get built. Iron Gate sat 0.238 m outside the Upper
#      Klamath-Trinity Chinook range and read as no Chinook.
BASE_M <- 75
EXT_M  <- 500

# ---- rule 40: a name-agreement rule needs equality, not an overlap ---------
# LOWERCASE FIRST: stripping non-lowercase characters before lowercasing deletes every
# capital and makes every creek match every creek (standing rule 37, learned the hard
# way on 2026-09-11).
#
# TIGHTENED 2026-09-12, DECIDED by Nathan (PHASE1_AUDIT.md section 3). The old rule kept
# a candidate if it shared ONE non-generic token, and the generic list held `little`,
# `big`, `east`, `west`, `fork` and `branch`: exactly the words that separate sibling
# streams. So "East Fork Anderson Creek" and "Anderson Creek" reduced to the same token
# and a dam on a tributary inherited the main stem's species from a few hundred metres
# away. Four such matches were found (WA-046, CA-155, CA-075, OR-066).
#
# Now the two names must be EQUAL after normalisation. Only words carrying no identity
# of their own are dropped; the qualifiers stay, and are what makes two sibling names
# differ. A parenthetical is cut the way "tributary to X" already was, because it names
# the basin rather than the stream ("Glenbrook Gulch (Albion River)" was matching the
# Albion River). Measured against the 2026-09-11 run this keeps 16 of 20 dam/stream
# pairs and drops exactly those four; Iron Gate (95 m) and Little Shasta (140 m), the
# cases the extension exists for, are untouched.
# `stream` added 2026-09-13. It is exactly as generic as `creek`, `river`, `brook` and
# `run`, and its absence was an oversight with a consequence: SWIFD encodes an unnamed
# watercourse as the literal text "Unnamed stream [1206706475584]", which normalised to
# the token {stream} and so read as a real name carrying an identity. That is a "no value"
# stored as a string rather than as a null, the same family as rule 38, and it made two
# placeholder features look like named channels under rule 45.
NOISE <- c("creek", "river", "the", "of", "dam", "unnamed", "mainstem", "main", "stem",
           "stream", "reservoir", "lake", "pond", "and", "gulch", "slough", "canal",
           "ditch", "brook", "run")

# Does this stream name carry an identity of its own, or is it a placeholder? A name is
# only a name if something survives normalisation: "Unnamed stream [1206706475584]" and
# "(unnamed)" both reduce to nothing and must not be treated as a different channel.
# Used by rule 45, which blocks the same-stream extension only for a genuinely NAMED
# channel, because an unnamed feature is usually the same watercourse with a missing name
# attribute rather than a different stream.
is_named <- function(x) {
  x <- ifelse(is.na(x), "", x)
  lengths(toks(trib_cut(x))) > 0
}
trib_cut <- function(x) {
  x <- sub("(?i)\\b(tributary|trib)\\b.*$", "", ifelse(is.na(x), "", x), perl = TRUE)
  gsub("\\([^)]*\\)", "", x)
}
toks <- function(x) {
  x <- gsub("[^a-z ]", " ", tolower(ifelse(is.na(x), "", x)))
  lapply(strsplit(x, " +"), function(v) sort(unique(setdiff(v[nchar(v) > 2], NOISE))))
}
same_stream <- function(a_tok, b) {
  if (!length(a_tok)) return(rep(FALSE, length(b)))
  vapply(toks(trib_cut(b)), function(v) length(v) > 0 && identical(v, a_tok), logical(1))
}

# ---- claim grades ----------------------------------------------------------
# Added 2026-09-12 (Nathan: mark inferred and proxy claims visibly). One list, because
# it was previously `CLAIM_GRADES` in make_presence_layers.R and `GRADE_ORDER` in
# join_dams_to_habitat.R, with a comment in each saying it must match the other: the
# same two-copies-of-one-rule shape as 38, 39 and 41, caught before it bit.
#
#   observed   a record of the fish
#   presumed   an expert presumption at reach level, not a record
#   range      a whole-watershed expert range, not a reach
#   proxy      a different layer standing in for this species' distribution
#   inferred   this project derived the species or its presence; the source does not
#              say it
#
# Ranked best to worst in exactly that order. The order is a stated judgement, not a
# measurement, and is Nathan's to change.
#
# NOT to be confused with `GRADES` above, which is SWIFD's own Documented/Presumed
# vocabulary. Two different things, hence two names.
CLAIM_GRADES <- c("observed", "presumed", "range", "proxy", "inferred")
