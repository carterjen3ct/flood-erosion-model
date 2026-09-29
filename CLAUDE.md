# Flood & Erosion Modeling Tool — ArcGIS Script Tool

## What this project is
A Python-based ArcGIS Script Tool that models **flood depth** and **erosion risk** for any
user-defined study area. It runs inside ArcGIS Pro with the Spatial Analyst extension.
Built with AI-assisted programming. GitHub: https://github.com/carterjen3ct/flood-erosion-model

**Course context:** GEOG 469 Lab 2 — AI-Assisted Programming for GIS. Due 2026-09-24.

> **Status (2026-09-29):** flood and erosion models rewritten to be physically based
> (fill-depth ponding + corrected RUSLE). Verified against a numpy stand-in for arcpy on
> synthetic terrain; **not yet run in ArcGIS Pro.** See **Known issues** for what's fixed
> and what limits remain.

---

## File structure

```
flood_model/
├── flood_model.py      # Main script tool — all analysis logic
├── lookups.py          # CN by hydro group, C factor, K default, hydro group map
├── FloodModel.pyt      # Python Toolbox — ArcGIS auto-detects this, no setup needed
├── setup_toolbox.py    # Legacy: attempted to generate FloodModel.tbx (deprecated — use .pyt)
├── CLAUDE.md           # This file
└── .gitignore          # __pycache__/, *.pyt.xml (Pro metadata)
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
| 2 | DEM Elevation Units | GPString | "Meters" or "Feet" (vertical units only) |
| 3 | Soil Layer | GPFeatureLayer (Polygon) | SSURGO recommended |
| 4 | Hydrologic Group Field | Field (Text, from #3) | e.g. "hydgrp" → A/B/C/D |
| 5 | K-Factor Field | Field (Double, from #3, optional) | RUSLE soil erodibility |
| 6 | Rainfall Depth | GPDouble | Storm event total |
| 7 | Rainfall Units | GPString | "Inches" or "Millimeters" |
| 8 | Output Workspace | DEWorkspace | Folder or file GDB |
| 9 | Output Flood Depth Raster | DERasterDataset (output) | |
| 10 | Output Soil Loss Raster (t/ha) | DERasterDataset (output) | |

There is **no land use input** (removed 2026-09-24). One land cover is assumed for the
whole study area — pasture/grassland, fair condition — set in `lookups.py`.

`FloodModel.pyt` `execute()` reloads `lookups` and `flood_model` and passes `parameters`
to `flood_model.main(parameters)`, so code edits apply without restarting ArcGIS Pro.

Field parameters (#4, #5) are derived — their dropdowns auto-populate from the
layer selected in the preceding parameter. User never types field names.

---

## Analysis pipeline (flood_model.py)

### 1. Environment setup (`main`)
- `prepare_dem`: a geographic DEM (degrees) is clipped to the study area (+10 cells) and
  projected to the local UTM zone (NAD83 UTM for NAD83 DEMs in zones 1–23 N, else WGS84),
  bilinear resampling. Projected DEMs are used as-is.
- Two nested `arcpy.EnvManager`s (restored when the tool ends): `overwriteOutput`,
  `qualifiedFieldNames=False`; then `extent` = study area (so Fill/flow tools only process
  that area), `mask`, `snapRaster`/`cellSize`/`outputCoordinateSystem` = DEM.
- Horizontal units from `spatialReference.metersPerUnit`; elevations converted to meters
  if "Feet"; Slope gets `z_factor = 1 / metersPerUnit`.

### 2. Terrain surfaces
```
dem_s      = Fill(dem_m, MIN_SINK_DEPTH_M)  # removes DEM-noise sinks only
filled_dem = Fill(dem_s)                    # every depression filled to its spill point
```

### 3. SCS Curve Number runoff (Q, inches)
- Soil layer clipped to the study area (`arcpy.analysis.Clip`, in memory); join prefixes
  stripped from field names.
- Hydro group text → integer (A=1 … D=4); dual groups → D; unknown/blank → D with a warning;
  gaps in soil coverage → D.
- CN from `lookups.CN_BY_HYDRO_GROUP`; Q = (P − 0.2S)² / (P + 0.8S), S = 1000/CN − 10.

### 4. Flood depth — volume-limited fill-depth ponding (`compute_flood_depth`)
1. Depressions = cells where `filled_dem − dem_s > 0`, grouped by `RegionGroup` on the spill
   level (mm) so separate touching depressions stay apart.
2. Runoff volume per cell = Q × cell area; `Watershed(FlowDirection(dem_s), zones)` gives
   each depression's catchment; `ZonalStatistics SUM` → inflow volume per depression.
3. Water level per depression solved exactly in numpy (`solve_pond_depths`, one pass):
   cells sorted by (depression, elevation); with the lowest k cells wet, level =
   (inflow/cell area + Σ their elevations) / k; take the first k whose level doesn't reach
   the next cell up; cap at the spill level (excess leaves the model). Result goes back via
   `NumPyArrayToRaster` → scratch GDB `pond_depth` + `DefineProjection`.
   (Replaced a 20-step zonal-map-algebra bisection on 2026-09-29 — it hung in Pro.)
4. Depth = level − dem_s, kept where ≥ `MIN_FLOOD_DEPTH_M`; **dry cells are NoData**.
5. Output in DEM elevation units. Summary reports flooded area, max depth and a water
   budget (runoff total vs. volume ponded).
No depressions at all → empty flood raster and a message (no crash).

### 5. RUSLE soil loss (A = R·K·LS·C·P, SI units, t/ha per storm)
- **R** = storm EI30 (`event_erosivity`): rainfall spread over 24 h with the SCS Type II
  pattern (`lookups.SCS_TYPE_II`), 15-min steps; E from Brown & Foster (1987)
  e = 0.29(1 − 0.72e^(−0.05i)) MJ/ha/mm; I30 = peak 30-min intensity. 3 in → ~776.
- **K** = field or `K_DEFAULT` (US units) × `K_US_TO_SI` (0.1317).
- **LS** (Moore & Burch 1986): L = (λ/22.13)^0.4 with λ = (flow_acc + 1) × cell size (m)
  on `FlowDirection(filled_dem)`, capped at `MAX_SLOPE_LENGTH_M` (300 m);
  S = (sin β / 0.0896)^1.3 with β from `Slope(dem_s, "DEGREE", z_factor)`.
- **C** = `lookups.C_FACTOR`, **P** = 1.0.
- Cells under ponded water → 0 (deposition, not loss).

### 6. Outputs
- Both rasters saved to the output workspace and added to the active map, styled with a
  stretched ramp (`Blue*` for flood, `Yellow*Red*` percent-clip for soil loss) — falls back
  to Pro's default look if the ramp/colorizer isn't available.
- Tip for the "how it looks" map: put the flood raster over a hillshade of the DEM.

---

## lookups.py contents

- `CN_BY_HYDRO_GROUP` — `{"A": 49, "B": 69, "C": 79, "D": 84}` (TR-55 pasture, fair)
- `C_FACTOR = 0.013` — RUSLE C for the assumed cover (pasture)
- `K_DEFAULT = 0.28` (US units), `K_US_TO_SI = 0.1317`
- `HYDRO_GROUP_MAP` — SSURGO text → int 1–4 (dual groups → 4/D); `UNKNOWN_HYDRO_GROUP = "D"`
- Calibration knobs: `MIN_SINK_DEPTH_M = 0.1` (lower to ~0.03 for 1 m lidar),
  `MIN_FLOOD_DEPTH_M = 0.03`, `MAX_SLOPE_LENGTH_M = 300`
- `SCS_TYPE_II` — 24-h storm distribution (swap for Type I/IA/III outside the US interior)

---

## Recommended data sources

| Input | Source |
|-------|--------|
| DEM | USGS National Map (1/3 arc-second NED) — ships in geographic coordinates; the tool auto-projects it to UTM |
| Soil layer | USDA Web Soil Survey / gSSURGO — see **Soil hydro group field** below |

---

## Soil hydro group field

Use **`hydgrpdcd`** (Hydrologic Group – Dominant Conditions) from SSURGO's `muaggatt`
table. The soil polygons (`soilmu_a_*.shp` / gSSURGO `MUPOLYGON`) don't carry it:
join `muaggatt` on `MUKEY` ↔ `mukey`, then pick `hydgrpdcd` (may appear as
`muaggatt.hydgrpdcd` — the tool strips the prefix, no export needed). `hydgrp` lives in the
`component` table (many rows per map unit) — avoid it. Clip the soil layer to the study area
**before** joining (see P2).

---

## Known issues — model validity

Identified 2026-09-24, fixed 2026-09-29 unless noted. IDs are for reference in commits.

### Fixed 2026-09-29
- **F1–F3, F5–F7 (flood):** replaced `flow_acc × Q` with volume-limited fill-depth ponding
  (pipeline §4). Real depths in real units, flat water surfaces, no cell-count scaling,
  NoData where dry. Summary now reports flooded area / depth / water budget.
- **E1–E3 (erosion):** Moore & Burch LS with λ = specific catchment length, capped at 300 m;
  R = event EI30 from a Type II storm; K converted to SI → A in t/ha per storm. Zero under
  ponded water. Slope from the unfilled surface.
- **U1:** geographic DEMs auto-projected to UTM. **U2:** Slope z-factor. **U3:** K rasterized
  at native cell size.
- **I2:** unknown/blank hydro groups → D with a warning listing the values; dual groups → D.
  **I3:** soil gaps → D instead of NoData.
- **P1:** `env.extent` = study area. **P2:** soil clipped to study area instead of copied.
- Environments are now restored after the run (`EnvManager`), so the extent/mask don't leak
  into the user's next tool.

### Remaining limits (by design, ponytail-marked in code)
- **F4 / spill cascade:** water that overflows a depression leaves the model; it does not
  refill lower depressions, and river overbank (floodplain) flooding is not modeled — it
  needs HAND or HEC-RAS 2D / Pro Flood Simulation. The summary's water budget shows how
  much runoff left as streamflow.
- Merged depressions (sub-basins under one spill level) share one water level.
- **I1:** one assumed cover (pasture, fair) everywhere. **I4:** no stream network input.
  **I5:** no NOAA Atlas 14 lookup — user enters rainfall depth.
- Upstream area outside the study-area polygon contributes no runoff — draw the study area
  around whole catchments.
- Storm pattern is fixed to Type II.

---

## Session handoff (last session: 2026-09-29)

### Done that session (UNCOMMITTED)
- Rewrote flood (§4) and erosion (§5) models, units/CRS handling, input clipping, env
  restore, map styling. `FloodModel.pyt`: labels/description only (11 params unchanged).
- Added `.gitignore` (`__pycache__/`, `*.pyt.xml`); `git rm --cached` staged removal of the
  previously committed `__pycache__/*.pyc` and `*.pyt.xml` (files stay on disk).
- `LICENSE` diff is line endings only (LF↔CRLF), not a text change — left alone.
- Verified with a numpy stand-in for arcpy.sa (Fill, FlowDirection, Watershed, RegionGroup,
  ZonalStatistics…) on a 40×40 synthetic bowl: flat water surface, stored volume =
  min(inflow, capacity), no-depression and blank-hydro-group paths. Test lived in the
  session scratchpad, not the repo. **Needs a real run in ArcGIS Pro.**

### Things to check on the first Pro run
- Tool messages: water budget % and flooded area should be sensible; max depth in m/ft,
  bounded by the deepest depression (not millions).
- Symbology: if the ramp didn't apply, set it manually (Blues for flood, Yellow–Red for soil
  loss).
- Run time: the pond-level solve is ~3 s per 4M cells in numpy; Fill/flow tools dominate.
- The user reported the first Pro run hung at "Solving pond water levels" (bisection);
  replaced with the numpy solver, verified vs brute force on 25 depressions. Re-run needed.
- Then: flood raster drew all black, stretch offered only bivariate ramps. Suspected cause:
  NumPyArrayToRaster wrote 64-bit float (numpy default). Now float32 + CalculateStatistics
  on both outputs. Unconfirmed in Pro — if still black, check Source → NoData/pixel type.

### How the user works
- Wants zero mistakes: trace the code fully, verify, and ask when a request is ambiguous.
- Wants a clear "what do I need to do next" at the end of changes.

---

## Coding conventions

- All analysis functions are standalone and independently testable
- `log()` wraps `arcpy.AddMessage()` — use it instead of `print()` inside the tool
- Temporary rasters go to `"in_memory\\"`; exception: the numpy pond depth is saved to
  `arcpy.env.scratchGDB` so it can get a projection
- Do NOT add `arcpy.CheckOutExtension("Spatial")` — Spatial Analyst is assumed available
- Comments on every code block (user preference)
