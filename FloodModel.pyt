# FloodModel.pyt
# ArcGIS Pro Python Toolbox — replaces setup_toolbox.py + FloodModel.tbx
# No setup script needed. ArcGIS Pro auto-detects .pyt files when you
# connect this folder in the Catalog pane.
#
# To use:
#   Catalog pane → Folders → Add Folder Connection → this folder
#   Expand FloodModel.pyt → double-click "Flood & Erosion Model"

import arcpy
import os
import sys

# Add this folder to sys.path so flood_model.py and lookups.py can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class Toolbox:
    """ArcGIS Python Toolbox container."""
    def __init__(self):
        self.label = "Flood Model"
        self.alias = "floodmodel"
        self.tools = [FloodErosionModel]


class FloodErosionModel:
    """Flood depth and erosion risk modeling tool."""

    def __init__(self):
        self.label = "Flood & Erosion Model"
        self.description = (
            "Models flood depth and erosion risk for a defined study area. "
            "Inputs: DEM and soil layer (with hydrologic group). "
            "Outputs: flood depth raster (SCS-CN routed) and RUSLE erosion risk raster."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define the tool's parameters — mirrors setup_toolbox.py parameter list."""

        # 0: Study Area polygon mask
        p0 = arcpy.Parameter(
            displayName="Study Area",
            name="study_area",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )
        p0.filter.list = ["Polygon"]

        # 1: DEM raster
        p1 = arcpy.Parameter(
            displayName="DEM",
            name="dem",
            datatype="GPRasterLayer",
            parameterType="Required",
            direction="Input"
        )

        # 2: DEM units dropdown
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

        # 3: Soil polygon layer (SSURGO recommended)
        p3 = arcpy.Parameter(
            displayName="Soil Layer",
            name="soil_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )
        p3.filter.list = ["Polygon"]

        # 4: Hydrologic group field — auto-populates from soil layer (text fields only)
        p4 = arcpy.Parameter(
            displayName="Hydrologic Group Field",
            name="hydro_group_field",
            datatype="Field",
            parameterType="Required",
            direction="Input"
        )
        p4.parameterDependencies = [p3.name]
        p4.filter.list = ["Text"]

        # 5: K-factor field — optional, auto-populates from soil layer (numeric fields)
        p5 = arcpy.Parameter(
            displayName="K-Factor Field (optional)",
            name="k_factor_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input"
        )
        p5.parameterDependencies = [p3.name]
        p5.filter.list = ["Double", "Single", "Float"]

        # 6: Rainfall depth (numeric)
        p6 = arcpy.Parameter(
            displayName="Rainfall Depth",
            name="rainfall_depth",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input"
        )

        # 7: Rainfall units dropdown
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

        # 8: Output workspace (folder or file GDB)
        p8 = arcpy.Parameter(
            displayName="Output Workspace",
            name="output_workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"
        )

        # 9: Output flood depth raster path
        p9 = arcpy.Parameter(
            displayName="Output Flood Depth Raster",
            name="out_flood_raster",
            datatype="DERasterDataset",
            parameterType="Required",
            direction="Output"
        )

        # 10: Output erosion risk raster path
        p10 = arcpy.Parameter(
            displayName="Output Erosion Risk Raster",
            name="out_erosion_raster",
            datatype="DERasterDataset",
            parameterType="Required",
            direction="Output"
        )

        return [p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10]

    def isLicensed(self):
        """Tool requires Spatial Analyst — assumed available per project conventions."""
        return True

    def updateParameters(self, parameters):
        """No dynamic parameter updates needed."""
        pass

    def updateMessages(self, parameters):
        """No custom validation messages needed."""
        pass

    def execute(self, parameters, messages):
        """Run the flood and erosion model with the values entered in the dialog."""
        import importlib
        import lookups
        import flood_model
        # Reload so edits to lookups.py / flood_model.py take effect without
        # restarting ArcGIS Pro (Pro caches imported modules between runs)
        importlib.reload(lookups)
        importlib.reload(flood_model)
        flood_model.main(parameters)

    def postExecute(self, parameters):
        """Nothing to clean up after execution."""
        pass
