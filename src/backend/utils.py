from sqlalchemy import text

def recompute_outbreak_metrics(conn):
    conn.execute(text("""
        WITH ground_zeros AS (
            SELECT latitude, longitude
            FROM tbldiseasereports
            WHERE is_ground_zero = TRUE AND status = 'Positive'
        ),
        distances AS (
            SELECT f.id AS farm_id,
                   MIN(
                       ST_Distance(
                           ST_SetSRID(ST_MakePoint(f.longitude, f.latitude), 4326)::geography,
                           ST_SetSRID(ST_MakePoint(gz.longitude, gz.latitude), 4326)::geography
                       ) / 1000
                   ) AS nearest_km
            FROM tblFarmerRegistry f
            CROSS JOIN ground_zeros gz
            WHERE f.latitude IS NOT NULL AND f.longitude IS NOT NULL
            GROUP BY f.id
        )
        UPDATE tblFarmerRegistry fr
        SET nearest_ground_zero_km = d.nearest_km,
            risk_level = CASE
                WHEN d.nearest_km IS NULL THEN 'Safe'
                WHEN d.nearest_km < 1 AND fr.total_farm_population > 50 THEN 'High'
                WHEN d.nearest_km < 3 THEN 'Medium'
                WHEN d.nearest_km < 5 THEN 'Low'
                ELSE 'Safe'
            END
        FROM distances d
        WHERE fr.id = d.farm_id;
    """))
