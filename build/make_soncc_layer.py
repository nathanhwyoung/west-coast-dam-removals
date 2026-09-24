"""RETIRED 2026-09-11. The SONCC build is now build/make_soncc_layer.R.

This script built the Oregon half only, treated Table 6's boundary dams as
advisory, had no county or ESU-extent clause, and its comment pointed joins at a
statewide unclipped file. The rebuild fixes all four; see PROCESS.md stage 5.
The full old script is kept at build/_old/make_soncc_layer_pre_rebuild_2026-09-11.py.
"""
import sys
sys.exit("make_soncc_layer.py is retired: run  Rscript build/make_soncc_layer.R")
