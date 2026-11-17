import geopandas as gpd
import matplotlib.pyplot as plt
import os



def check_and_plot(boundary_path, roads_path):
#     # Load shapefiles and reproject
     boundary = gpd.read_file(boundary_path).to_crs(epsg=3857)
     roads = gpd.read_file(roads_path).to_crs(epsg=3857)

     print("Boundary CRS:", boundary.crs)
     print("Roads CRS:", roads.crs)
     print("Boundary bounds:", boundary.total_bounds)
     print("Roads bounds:", roads.total_bounds)

#     # Clip roads to boundary
     roads_in_boundary = gpd.clip(roads, boundary)
     print("Number of road segments inside boundary:", len(roads_in_boundary))

#     # Plot boundary
     ax = boundary.plot(color="lightblue", edgecolor="black", figsize=(8,8))

#     # Plot roads safely
     if not roads_in_boundary.empty:
         roads_in_boundary.plot(ax=ax, color="red", linewidth=1.5, label="Roads in Quezon")
     else:
         print("⚠️ No roads found inside boundary")
         # Plot all roads anyway to check alignment
         roads.plot(ax=ax, color="gray", linewidth=0.5, label="All Roads")

     ax.set_aspect("equal")
     plt.title("Quezon Province with Roads")
     plt.legend()
     plt.show()

     return roads_in_boundary

# # Run the function
roads_in_boundary = check_and_plot(
     "ShapeFiles/QuezonMunicipalities-Barangays.shp",
     "ShapeFiles/QuezonRoads.shp"
 )
