# setup_toolbox.py
# Run this script ONCE in an ArcGIS Pro Python environment to create FloodModel.tbx.
# After running, open ArcGIS Pro → Catalog pane → connect to this folder → FloodModel.tbx.
#
# Usage (ArcGIS Pro Python prompt or standalone):
#   cd C:\path\to\flood_model
#   python setup_toolbox.py

import os
import arcpy

# ---------------------------------------------------------------------------
# Paths — adjust TOOL_FOLDER if needed
# ---------------------------------------------------------------------------
TOOL_FOLDER = os.path.dirname(os.path.abspath(__file__))
TOOLBOX_PATH = os.path.join(TOOL_FOLDER, "FloodModel.tbx")
SCRIPT_PATH  = os.path.join(TOOL_FOLDER, "flood_model.py")

# ---------------------------------------------------------------------------
# Parameter definitions
# Each dict maps to an arcpy.Parameter object.
# ---------------------------------------------------------------------------
def build_parameters():
    """Returns the ordered list of arcpy.Parameter objects for the Script Tool."""

    # 0: Study Area
    p0 = arcpy.Parameter(
        displayName="Study Area",
        name="study_area",
        datatype="GPFeatureLayer",
        parameterType="Required",
        direction="Input"
    )
    p0.filter.list = ["Polygon"]

    # 1: DEM
    p1 = arcpy.Parameter(
        displayName="DEM",
        name="dem",
        datatype="GPRasterLayer",
        parameterType="Required",
        direction="Input"
    )

    # 2: DEM Units
    p2 = arcpy.Parameter(
        displayName="DEM Units",
        name="dem_units",
        datatype="GPString",
        parameterType="Required",
        direction="Input"
    )
    p2.filter.type = "ValueList"
    p2.filter.list = ["Meters", "Feet"]
    p2.value = "Meters"

    # 3: Soil Layer
    p3 = arcpy.Parameter(
        displayName="Soil Layer",
        name="soil_layer",
        datatype="GPFeatureLayer",
        parameterType="Required",
        direction="Input"
    )
    p3.filter.list = ["Polygon"]

    # 4: Soil Hydrologic Group Field (derived from soil layer — auto-populates)
    p4 = arcpy.Parameter(
        displayName="Hydrologic Group Field",
        name="hydro_group_field",
        datatype="Field",
        parameterType="Required",
        direction="Input"
    )
    p4.parameterDependencies = [p3.name]
    p4.filter.list = ["Text"]

    # 5: Soil K-Factor Field (optional)
    p5 = arcpy.Parameter(
        displayName="K-Factor Field (optional)",
        name="k_factor_field",
        datatype="Field",
        parameterType="Optional",
        direction="Input"
    )
    p5.parameterDependencies = [p3.name]
    p5.filter.list = ["Double", "Single", "Float"]

    # 6: Rainfall Depth
    p6 = arcpy.Parameter(
        displayName="Rainfall Depth",
        name="rainfall_depth",
        datatype="GPDouble",
        parameterType="Required",
        direction="Input"
    )

    # 7: Rainfall Units
    p7 = arcpy.Parameter(
        displayName="Rainfall Units",
        name="rainfall_units",
        datatype="GPString",
        parameterType="Required",
        direction="Input"
    )
    p7.filter.type = "ValueList"
    p7.filter.list = ["Inches", "Millimeters"]
    p7.value = "Inches"

    # 8: Output Workspace
    p8 = arcpy.Parameter(
        displayName="Output Workspace",
        name="output_workspace",
        datatype="DEWorkspace",
        parameterType="Required",
        direction="Input"
    )

    # 9: Output Flood Depth Raster
    p9 = arcpy.Parameter(
        displayName="Output Flood Depth Raster",
        name="out_flood_raster",
        datatype="DERasterDataset",
        parameterType="Required",
        direction="Output"
    )

    # 10: Output Erosion Risk Raster
    p10 = arcpy.Parameter(
        displayName="Output Erosion Risk Raster",
        name="out_erosion_raster",
        datatype="DERasterDataset",
        parameterType="Required",
        direction="Output"
    )

    return [p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10]


# ---------------------------------------------------------------------------
# Create the toolbox and add the script tool
# ---------------------------------------------------------------------------
def create_toolbox():
    # Remove existing toolbox so we can recreate cleanly
    if os.path.exists(TOOLBOX_PATH):
        os.remove(TOOLBOX_PATH)
        print(f"Removed existing toolbox: {TOOLBOX_PATH}")

    # Create the .tbx file
    arcpy.management.CreateToolbox(TOOLBOX_PATH)
    print(f"Created toolbox: {TOOLBOX_PATH}")

    # Build parameter XML expected by AddScriptTool
    params = build_parameters()

    # Add the script tool to the toolbox
    arcpy.management.AddScriptTool(
        toolbox=TOOLBOX_PATH,
        tool_name="FloodModel",
        script=SCRIPT_PATH,
        parameters=params,
        description=(
            "Models flood depth and erosion risk for a defined study area. "
            "Inputs: DEM and soil layer (with hydrologic group). "
            "Outputs: flood depth raster (SCS-CN routed) and RUSLE erosion risk raster."
        ),
        display_name="Flood & Erosion Model"
    )
    print("Script tool 'Flood & Erosion Model' added successfully.")
    print(f"\nTo use:")
    print(f"  1. Open ArcGIS Pro")
    print(f"  2. Catalog pane → Folders → connect to: {TOOL_FOLDER}")
    print(f"  3. Double-click FloodModel.tbx → double-click 'Flood & Erosion Model'")


if __name__ == "__main__":
    create_toolbox()
