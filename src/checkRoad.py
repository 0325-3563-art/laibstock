import geopandas as gpd
import matplotlib.pyplot as plt

# Load road file
roads_gdf = gpd.read_file(r"C:\MIT\CAPSTONE\SampleSystem\LAIBStock-project\src\backend\hotosm_phl_roads_lines_geojson.geojson")
# Load barangay shapefile
quezon = gpd.read_file(r"C:\MIT\CAPSTONE\SampleSystem\LAIBStock-project\src\backend\ShapeFiles\QuezonMunicipalities-Barangays.shp")

# Convert CRS to match roads
quezon = quezon.to_crs(roads_gdf.crs)

roads_quezon = gpd.overlay(roads_gdf, quezon, how="intersection")

print("Roads in Quezon:", len(roads_quezon))
#roads_quezon.plot(figsize=(10,10))

major_roads = roads_quezon[roads_quezon["highway"].isin(["primary","secondary","tertiary"])]
print("Major roads in Quezon:", len(major_roads))


# Inspect CRS and geometry
# print("CRS:", roads_gdf.crs)
# print("Geometry types:", roads_gdf.geom_type.value_counts())
# print("Columns:", roads_gdf.columns)

# # Plot roads
# roads_gdf.plot(figsize=(10,10))
# plt.show()

# # Optional: filter major roads only
# major_roads = roads_gdf[roads_gdf["highway"].isin(["primary","secondary","tertiary"])]
# print("Major roads count:", len(major_roads))

