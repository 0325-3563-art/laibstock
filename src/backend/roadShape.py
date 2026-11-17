import osmnx as ox
roads = ox.graph_from_place("Quezon, Philippines", network_type="drive")
gdf_roads = ox.graph_to_gdfs(roads, nodes=False)
gdf_roads.to_file("ShapeFiles/QuezonRoads.shp")
