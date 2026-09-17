# Flood & Erosion Modeling Tool — ArcGIS Script Tool

## What this project is
A Python-based ArcGIS Script Tool that models **flood depth** and **erosion risk** for any
user-defined study area. It runs inside ArcGIS Pro with the Spatial Analyst extension.
Built with AI-assisted programming. GitHub: https://github.com/carterjen3ct/flood-erosion-model

---

## File structure

```
flood_model/
├── flood_model.py      # Main script tool — all analysis logic
├── lookups.py          # CN table, C-factor table, K default, hydro group maps
├── setup_toolbox.py    # Run once to generate FloodModel.tbx via arcpy
├── CLAUDE.md           # This file
└── .gitignore          # Excludes FloodModel.tbx, __pycache__, etc.
```

`FloodModel.tbx` is not committed — it is generated locally by running `setup_toolbox.py`.

---

## Requirements

- ArcGIS Pro (any recent version)
- Spatial Analyst extension (assumed available — do NOT add license check/checkout code)
- Python environment that ships with ArcGIS Pro (includes arcpy)

---

## How to set up the toolbox

```powershell
cd C:\Users\carte\Documents\flood_model
python setup_toolbox.py
```

Then in ArcGIS Pro: Catalog pane → Folders → connect to this folder → open FloodModel.tbx.

---

## Tool inputs (14 parameters in order)

| # | Name | Type | Notes |
|---|------|------|-------|
| 0 | Study Area | GPFeatureLayer (Polygon) | Mask for all analysis |
| 1 | DEM | GPRasterLayer | Elevation raster |
| 2 | DEM Units | GPString | "Meters" or "Feet" |
| 3 | Soil Layer | GPFeatureLayer (Polygon) | SSURGO recommended |
| 4 | Hydrologic Group Field | Field (Text, from #3) | e.g. "hydgrp" → A/B/C/D |
| 5 | K-Factor Field | Field (Double, from #3, optional) | RUSLE soil erodibility |
| 6 | Land Use Layer | GPFeatureLayer (Polygon) | NLCD or custom |
| 7 | Land Use Class Field | Field (from #6) | e.g. NLCD "Value" field |
| 8 | Land Use Classification | GPString | "NLCD" or "Custom" |
| 9 | Rainfall Depth | GPDouble | Storm event total |
| 10 | Rainfall Units | GPString | "Inches" or "Millimeters" |
| 11 | Output Workspace | DEWorkspace | Folder or file GDB |
| 12 | Output Flood Depth Raster | DERasterDataset (output) | |
| 13 | Output Erosion Risk Raster | DERasterDataset (output) | |

Field parameters (#4, #5, #7) are derived — their dropdowns auto-populate from the
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
- Land use rasterized → NLCD code raster
- CN looked up per cell from `lookups.CN_TABLE[(nlcd_code, hydro_letter)]` via Con chains
- Q = (P − 0.2S)² / (P − 0.2S + S), where S = 1000/CN − 10; Q=0 where P ≤ 0.2S

### 4. Flood depth raster
```
flood_depth_m = flow_acc * (Q_inches * 0.0254)
flood_depth_m = Con(flow_acc >= 100, flood_depth_m, 0)   # suppress hilltop noise
```
Converted back to DEM units for output.
**Known ceiling:** steady-state proxy, not hydrodynamic. No Manning's n, no channel
geometry. For regulatory use, replace with HEC-RAS 2D.

### 5. RUSLE erosion risk (A = R·K·LS·C·P)
- **R** = 0.04 × rainfall_mm × 1.15 (simplified Wischmeier single-event)
- **K** = rasterized from soil K-factor field, or constant 0.28 if field not supplied
- **L** = (flow_acc × cell_m² / 22.13)^0.4
- **S** = (sin(slope_rad) / 0.0896)^1.3   (McCool et al. 1987)
- **C** = from `lookups.C_FACTOR_TABLE[nlcd_code]` via Con chain
- **P** = 1.0 (no support practice assumed)
- Output units: tons/acre/event (relative risk index)

### 6. Outputs
- Both rasters saved to output workspace
- Both auto-added to the active ArcGIS Pro map via `arcpy.mp`
- Summary stats (max flood depth, mean erosion) printed to tool messages

---

## lookups.py contents

- `CN_TABLE` — dict keyed `(nlcd_code, "A"|"B"|"C"|"D")` → CN int. Covers NLCD codes:
  11, 21–24, 31, 41–43, 52, 71, 81–82, 90, 95. Fallback: `CN_DEFAULT = 75`
- `C_FACTOR_TABLE` — dict keyed by NLCD code → C float (0.001–0.45). Fallback: `C_FACTOR_DEFAULT = 0.10`
- `K_DEFAULT = 0.28` — used when no K-factor field provided
- `HYDRO_GROUP_MAP` — maps SSURGO text values ("A", "A/D", "B", etc.) → int 1–4
- `HYDRO_INT_TO_LETTER` — reverse map for CN lookup

---

## Recommended data sources

| Input | Source |
|-------|--------|
| DEM | USGS National Map (1/3 arc-second NED) |
| Soil layer | USDA Web Soil Survey (SSURGO) — `hydgrp` field for hydro group |
| Land use | MRLC NLCD — use the `Value` field, pick "NLCD" classification |

---

## Known limitations / deferred work

- Flood model is a **steady-state accumulation proxy** — not suitable for FEMA/regulatory use
- RUSLE is **event-based**, not annualized — good for relative risk comparison only
- No stream network input — flow routing is purely DEM-derived
- No NOAA Atlas 14 integration — user enters raw rainfall depth
- `min_acc = 100` threshold (hilltop filter) is hardcoded — could be exposed as a parameter
  if users with very high-res DEMs need finer control

---

## Coding conventions

- All analysis functions are standalone and independently testable
- `log()` wraps `arcpy.AddMessage()` — use it instead of `print()` inside the tool
- Temporary rasters go to `"in_memory\\"` — no scratch GDB needed
- Do NOT add `arcpy.CheckOutExtension("Spatial")` — Spatial Analyst is assumed available
- Comments on every code block (user preference)
