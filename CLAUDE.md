# Flood & Erosion Modeling Tool — ArcGIS Script Tool

## What this project is
A Python-based ArcGIS Script Tool that models **flood depth** and **erosion risk** for any
user-defined study area. It runs inside ArcGIS Pro with the Spatial Analyst extension.
Built with AI-assisted programming. GitHub: https://github.com/carterjen3ct/flood-erosion-model

**Course context:** GEOG 469 Lab 2 — AI-Assisted Programming for GIS. Due 2026-09-24.

> **Status (2026-09-24): outputs are NOT physically valid.** The tool runs, but the
> "flood depth" raster is an accumulated-runoff index, not a depth (a test run gave a max
> of 1,260,356 on a raster that should read in m/ft). The erosion raster has formula and
> unit errors too. See **Known issues — model validity** below before trusting or
> reporting any output, and before extending the model.

---

## File structure

```
flood_model/
├── flood_model.py      # Main script tool — all analysis logic
├── lookups.py          # CN by hydro group, C factor, K default, hydro group map
├── FloodModel.pyt      # Python Toolbox — ArcGIS auto-detects this, no setup needed
├── setup_toolbox.py    # Legacy: attempted to generate FloodModel.tbx (deprecated — use .pyt)
├── CLAUDE.md           # This file
└── .gitignore          # Excludes __pycache__, etc.
```

`FloodModel.pyt` is the active toolbox. `setup_toolbox.py` is kept for reference but
`arcpy.management.CreateToolbox` does not exist in all ArcGIS Pro versions — use the .pyt.

---

## Requirements

- ArcGIS Pro (any recent version)
- Spatial Analyst extension (assumed available — do NOT add license check/checkout code)
- Python environment that ships with ArcGIS Pro (includes arcpy)

---

## How to set up the toolbox

No setup script needed. Just:
1. Open ArcGIS Pro
2. Catalog pane → Folders → right-click → **Add Folder Connection** → `C:\Users\carte\Documents\flood_model`
3. Expand the folder → expand `FloodModel.pyt` → double-click **Flood & Erosion Model**

---

## Tool inputs (11 parameters in order)

| # | Name | Type | Notes |
|---|------|------|-------|
| 0 | Study Area | GPFeatureLayer (Polygon) | Mask for all analysis |
| 1 | DEM | GPRasterLayer | Elevation raster |
| 2 | DEM Units | GPString | "Meters" or "Feet" |
| 3 | Soil Layer | GPFeatureLayer (Polygon) | SSURGO recommended |
| 4 | Hydrologic Group Field | Field (Text, from #3) | e.g. "hydgrp" → A/B/C/D |
| 5 | K-Factor Field | Field (Double, from #3, optional) | RUSLE soil erodibility |
| 6 | Rainfall Depth | GPDouble | Storm event total |
| 7 | Rainfall Units | GPString | "Inches" or "Millimeters" |
| 8 | Output Workspace | DEWorkspace | Folder or file GDB |
| 9 | Output Flood Depth Raster | DERasterDataset (output) | |
| 10 | Output Erosion Risk Raster | DERasterDataset (output) | |

There is **no land use input** (removed 2026-09-24). One land cover is assumed for the
whole study area — pasture/grassland, fair condition — set in `lookups.py`.

`FloodModel.pyt` `execute()` reloads `lookups` and `flood_model` and passes `parameters`
to `flood_model.main(parameters)`, so code edits apply without restarting ArcGIS Pro.

Field parameters (#4, #5) are derived — their dropdowns auto-populate from the
layer selected in the preceding parameter. User never types field names.

---

## Analysis pipeline (flood_model.py)

### 1. Environment setup
- `arcpy.env.mask = study_area`, `snapRaster = DEM`, `overwriteOutput = True`
- DEM converted to meters internally if user supplied feet
- Cell size detected from DEM; projected unit auto-detected for m² calculations

### 2. Terrain derivatives
```
Fill(dem)                    → filled_dem (sink removal)
FlowDirection(filled_dem)    → flow_dir (D8)
FlowAccumulation(flow_dir)   → flow_acc (upstream cell count)
Slope(filled_dem, "DEGREE")  → slope_deg (used in RUSLE LS)
```

### 3. SCS Curve Number runoff (Q, inches)
- Soil layer rasterized: hydro group text → integer (A=1, B=2, C=3, D=4)
- CN per cell from `lookups.CN_BY_HYDRO_GROUP[letter]` via a Con chain (uniform assumed cover)
- Q = (P − 0.2S)² / (P − 0.2S + S), where S = 1000/CN − 10; Q=0 where P ≤ 0.2S

### 4. Flood depth raster
```
flood_depth_m = flow_acc * (Q_inches * 0.0254)
flood_depth_m = Con(flow_acc >= 100, flood_depth_m, 0)   # suppress hilltop noise
```
Converted back to DEM units for output.
**This is not a depth.** `flow_acc` is a count of upstream cells, so the result is the whole
storm's runoff from every upstream cell stacked onto one pixel. See issue F1 below.

### 5. RUSLE erosion risk (A = R·K·LS·C·P)
- **R** = 0.04 × rainfall_mm × 1.15 (simplified Wischmeier single-event)
- **K** = rasterized from soil K-factor field, or constant 0.28 if field not supplied
- **L** = (flow_acc × cell_m² / 22.13)^0.4
- **S** = (sin(slope_rad) / 0.0896)^1.3   (McCool et al. 1987)
- **C** = constant `lookups.C_FACTOR` (uniform assumed cover)
- **P** = 1.0 (no support practice assumed)
- Output units: tons/acre/event (relative risk index)

### 6. Outputs
- Both rasters saved to output workspace
- Both auto-added to the active ArcGIS Pro map via `arcpy.mp`
- Summary stats (max flood depth, mean erosion) printed to tool messages

---

## lookups.py contents

- `CN_BY_HYDRO_GROUP` — `{"A": 49, "B": 69, "C": 79, "D": 84}` (TR-55 pasture, fair)
- `C_FACTOR = 0.013` — RUSLE C for the assumed cover (pasture)
- `K_DEFAULT = 0.28` — used when no K-factor field provided
- `HYDRO_GROUP_MAP` — maps SSURGO text values ("A", "A/D", "B", etc.) → int 1–4

---

## Recommended data sources

| Input | Source |
|-------|--------|
| DEM | USGS National Map (1/3 arc-second NED) — **project to UTM (meters) first**, it ships in geographic coordinates (issue U1) |
| Soil layer | USDA Web Soil Survey / gSSURGO — see **Soil hydro group field** below |

---

## Soil hydro group field

Use **`hydgrpdcd`** (Hydrologic Group – Dominant Conditions) from SSURGO's `muaggatt`
table. The soil polygons (`soilmu_a_*.shp` / gSSURGO `MUPOLYGON`) don't carry it:
join `muaggatt` on `MUKEY` ↔ `mukey`, then pick `hydgrpdcd` (may appear as
`muaggatt.hydgrpdcd`; export the joined layer to drop the prefix). `hydgrp` lives in the
`component` table (many rows per map unit) — avoid it. Clip the soil layer to the study area
**before** joining (see P2).

---

## Known issues — model validity

Identified 2026-09-24 after a test run. IDs are for reference in commits/discussion.
Line numbers are `flood_model.py` as of that date.

### Flood depth (the core problem)
- **F1 — Output is accumulated runoff, not depth.** `flow_acc * Q` (lines ~171–177) sums the
  runoff of every upstream cell onto each pixel. Values grow with drainage area without limit
  (millions at outlets), are ~0 almost everywhere else, and carry no real unit.
- **F2 — No ponding / lateral spreading.** Real water fills low areas up to a level water
  surface and spreads sideways across the floodplain. The model routes everything into
  single-pixel D8 flow lines and never builds a water surface, so it produces extreme spikes
  on thin channel lines instead of a flood extent.
- **F3 — `Fill()` erases the depressions that should flood.** Sinks are filled for routing
  (line ~285), and the filled surface is then treated as "dry" — the fill depth
  (`filled_dem − dem`), which is exactly where water would pool, is thrown away.
- **F4 — No time, outflow, or conveyance.** The whole storm volume is treated as present at
  once; nothing drains out of the study area, and there's no channel capacity, velocity,
  roughness (Manning's n) or hydrograph. Runoff doesn't re-infiltrate as it flows downhill.
- **F5 — Resolution-dependent.** `flow_acc` counts cells, so the same area gives ~100× larger
  values at 1 m than at 10 m. The `min_acc = 100` hilltop filter is also cell-count based, so
  it means very different areas at different resolutions.
- **F6 — Unit conversion is cosmetic.** Multiplying by 3.28084 for "Feet" output (line ~181)
  converts a number that has no length unit to begin with.
- **F7 — Summary message is misleading.** "Max flood depth" (line ~340) reports F1's index as
  a depth.

**Fix direction:** replace section 4 with a method that produces a water surface, e.g.
- *Fill-depth ponding:* `filled_dem − dem` gives where/how deep depressions pond (quick win).
- *HAND (Height Above Nearest Drainage):* define streams from flow accumulation, compute each
  cell's height above its stream, derive a stage from runoff volume, flood cells with
  HAND < stage. Gives real depths and extents; still simplified.
- *Real hydraulics:* HEC-RAS 2D or ArcGIS Pro Flood Simulation for defensible results.

### Units / coordinate systems
- **U1 — Geographic DEMs break the math.** `cell_size_m` (lines ~271–274) only handles
  meters/feet; a DEM in degrees (e.g. USGS 3DEP 1/3 arc-second is NAD83 geographic) is used
  as if the cell size were ~0.0001 m. Slope (planar) is also wrong in degrees. **Project the
  DEM to a meter-based projected CRS (e.g. UTM) before running.**
- **U2 — "DEM Units = Feet" corrupts slope for feet-based projections.** Elevations are
  converted to meters (line ~279) but horizontal units stay in feet, so slope is understated
  by ~3.28× in e.g. State Plane (feet) DEMs.
- **U3 — K-factor raster uses the wrong cell size in feet projections.** It is rasterized
  with `cellsize=cell_size_m` (line ~211) instead of the DEM's native cell size.

### Erosion (RUSLE)
- **E1 — L factor uses area instead of specific catchment area.** Line ~222 uses
  `flow_acc × cell²`; the standard (Moore & Burch / Desmet & Govers) form is
  `flow_acc × cell_size` (area per unit contour width). Overstates L, and grows unbounded
  along channels — slope length is usually capped (~100–300 m) or channels are masked out,
  since RUSLE models sheet/rill erosion, not channel erosion.
- **E2 — R factor is not a recognized formula.** `0.04 × rainfall_mm × 1.15` (line ~203) is not
  EI30; event erosivity needs storm intensity, not just depth.
- **E3 — Mixed units.** R (from mm) and K (US customary) are combined and labeled
  "tons/acre/event" — only valid as a relative index, and only once E1/E2 are fixed.

### Inputs / assumptions
- **I1 — No land use** (removed 2026-09-24): one assumed cover (pasture, fair) everywhere,
  so runoff/erosion don't vary by urban/forest/crop.
- **I2 — Unknown hydro groups silently become B** (line ~91); dual groups (A/D etc.) use the
  drained class. Blank `hydgrpdcd` (water, urban land) skews runoff without warning.
- **I3 — Soil outside polygon coverage → NoData** CN, which propagates to NoData outputs.
- **I4 — No stream network input**; routing is purely DEM-derived.
- **I5 — No NOAA Atlas 14 integration**; user enters raw rainfall depth.

### Performance
- **P1 — Mask ≠ processing extent.** `arcpy.env.mask` only blanks output cells; Fill / flow
  tools still process the full DEM extent. Clip the DEM to the study area first.
- **P2 — Whole soil layer is copied to memory** (`CopyFeatures`, line ~84) and looped row by
  row. A national soil layer will exhaust RAM — clip/select to the study area first.

### What the current outputs ARE usable for
- Flood raster: a relative map of where runoff **concentrates** (symbolize with a log or
  percent-clip stretch). Not depth, not extent.
- Erosion raster: a rough relative pattern driven mostly by slope and flow concentration.
  Not a soil-loss estimate.

---

## Session handoff (last session: 2026-09-24)

### Done that session (all UNCOMMITTED — nothing committed or pushed)
- Removed land use inputs (layer, class field, NLCD/Custom classification): 14 → 11 params.
  User chose "remove all land use" over converting the input to an NLCD raster.
- Fixed pre-existing crash bugs: `from arcpy.sa import PolygonToRaster, PolylineToRaster`
  (don't exist → ImportError on load); `mgmt.PolygonToRaster` → `arcpy.conversion` (`conv.`).
- `.pyt execute()` now reloads modules and passes `parameters` into `flood_model.main()`.
- Verified only with a stubbed `arcpy` (flow + parameter list); **not yet re-run in ArcGIS Pro**
  after these edits. The 1,260,356 max came from the user's own run in Pro.
- Added the Known issues section and this handoff.

### Git state
Modified: `CLAUDE.md`, `FloodModel.pyt`, `flood_model.py`, `lookups.py`, `setup_toolbox.py`.
`LICENSE` was already modified before that session (not by Claude) — ask before committing it.
Untracked `__pycache__/` and `*.pyt.xml` (Pro metadata) — there is no `.gitignore` despite the
file tree above; suggest adding one. Commit/push only when the user asks.

### Offered to the user, not yet done (their call)
1. **Fix the flood model (F1–F3)** — fill-depth ponding (`filled_dem − dem`) as a quick win,
   or a HAND approach for real depths/extents. Top priority: current output is invalid.
2. **Auto-clip inputs (P1, P2)** — clip the soil layer to the study area inside the tool
   (`arcpy.analysis.Clip` instead of `CopyFeatures`) and set `arcpy.env.extent` to the study
   area. ~3 lines.
3. Then U1–U3 (units/CRS) and E1–E3 (RUSLE formula) fixes.

### Things told to the user
- Run time is driven by DEM cell count: ~1M cells ≈ 1–3 min, ~10M ≈ 5–15 min, 100M+ ≈
  30 min–hours or out-of-memory. Fill/FlowDirection/FlowAccumulation dominate. Clip the DEM
  first (mask ≠ extent). Tool runs in the foreground.
- A nationwide soil layer will likely exhaust RAM — clip or Select by Location first.
- Current outputs are relative indices only; symbolize flood raster with log/percent-clip stretch.

### How the user works
- Wants zero mistakes: trace the code fully, verify, and ask when a request is ambiguous
  (e.g. "remove the land use parameter" had 3 readings — asking was the right call).
- Wants a clear "what do I need to do next" at the end of changes.

---

## Coding conventions

- All analysis functions are standalone and independently testable
- `log()` wraps `arcpy.AddMessage()` — use it instead of `print()` inside the tool
- Temporary rasters go to `"in_memory\\"` — no scratch GDB needed
- Do NOT add `arcpy.CheckOutExtension("Spatial")` — Spatial Analyst is assumed available
- Comments on every code block (user preference)
