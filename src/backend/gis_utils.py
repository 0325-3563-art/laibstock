import geopandas as gpd
from shapely.geometry import Point

QUEZON_SHP = "ShapeFiles/QuezonProvince.shp"
ROADS_SHP  = "ShapeFiles/QuezonRoads.shp"

def load_roads():
    """Load and return the Quezon roads shapefile in EPSG:3857."""
    return gpd.read_file(ROADS_SHP).to_crs(epsg=3857)

def load_quezon():
    """Load and return the Quezon province shapefile in EPSG:3857."""
    return gpd.read_file(QUEZON_SHP).to_crs(epsg=3857)

def compute_access_road_flag(latitude, longitude, threshold=2000):
    """Check if a farm point is within threshold meters of a road."""
    if latitude is None or longitude is None:
        return False

    pt = Point(longitude, latitude)
    pt_gdf = gpd.GeoDataFrame(geometry=[pt], crs="EPSG:4326").to_crs(epsg=3857)

    quezon = load_quezon()
    roads = load_roads()
    roads_quezon = gpd.clip(roads, quezon)

    if roads_quezon.empty:
        return False

    # Ensure LineString geometries
    roads_quezon["geometry"] = roads_quezon["geometry"].apply(
        lambda g: g if g.geom_type == "LineString" else g[0]
    )

    dist = roads_quezon.distance(pt_gdf.geometry.iloc[0]).min()
    return dist <= threshold if dist is not None else False
