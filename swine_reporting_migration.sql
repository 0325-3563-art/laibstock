-- =====================================================================
-- LAIBStock: swine population reporting (inventory + movement)
-- Run once in pgAdmin (Query Tool). Safe to re-run: it checks before creating.
-- BACK UP tblswinepopulation first (right-click > Backup, or:
--   CREATE TABLE tblswinepopulation_backup AS SELECT * FROM tblswinepopulation;)
-- =====================================================================

BEGIN;

-- 1) One row per farmer per reporting period -------------------------
CREATE TABLE IF NOT EXISTS tblswinereport (
  id               serial PRIMARY KEY,
  farmer_id        integer NOT NULL REFERENCES tblfarmerregistry(id),
  period_type      varchar(10) NOT NULL CHECK (period_type IN ('monthly','quarterly')),
  period_start     date NOT NULL,
  period_end       date NOT NULL,
  status           varchar(15) NOT NULL DEFAULT 'submitted'
                   CHECK (status IN ('submitted','returned','verified')),
  reported_by_role varchar(10) NOT NULL DEFAULT 'staff'
                   CHECK (reported_by_role IN ('farmer','staff')),
  reported_by_user varchar(100),
  verified_by      varchar(100),
  verified_at      timestamp,
  review_note      text,
  remarks          text,
  created_at       timestamp NOT NULL DEFAULT now(),
  CHECK (period_end >= period_start),
  UNIQUE (farmer_id, period_end)
);

-- 2) Movement totals during the period -------------------------------
CREATE TABLE IF NOT EXISTS tblswinemovement (
  id            serial PRIMARY KEY,
  report_id     integer NOT NULL REFERENCES tblswinereport(id) ON DELETE CASCADE,
  movement_type varchar(20) NOT NULL CHECK (movement_type IN
    ('birth','purchase','transfer_in','sale','slaughter','death','transfer_out','depopulated')),
  category      varchar(20) NOT NULL CHECK (category IN
    ('boar','sow','gilts','piglets','grower_fattener')),
  quantity      integer NOT NULL CHECK (quantity > 0),
  remarks       text
);
CREATE INDEX IF NOT EXISTS ix_swinemovement_report ON tblswinemovement(report_id);

-- 3) tblswinepopulation = the closing inventory of a report ----------
ALTER TABLE tblswinepopulation ADD COLUMN IF NOT EXISTS report_id integer;

-- 4) Turn existing rows into verified first reports ------------------
--    (if a farmer has several rows on the same date, the latest one is kept
--     as the report; the others stay in the table, untouched, with report_id NULL)
WITH src AS (
  SELECT DISTINCT ON (farmer_id, dateadded::date)
         id AS pop_id, farmer_id, dateadded::date AS d
  FROM tblswinepopulation
  WHERE report_id IS NULL
    AND farmer_id IN (SELECT id FROM tblfarmerregistry)
  ORDER BY farmer_id, dateadded::date, dateadded DESC, id DESC
), ins AS (
  INSERT INTO tblswinereport
    (farmer_id, period_type, period_start, period_end, status,
     reported_by_role, reported_by_user, verified_by, verified_at, remarks)
  SELECT farmer_id, 'monthly', date_trunc('month', d)::date, d, 'verified',
         'staff', 'migration', 'migration', now(), 'Imported from existing records'
  FROM src
  ON CONFLICT (farmer_id, period_end) DO NOTHING
  RETURNING id, farmer_id, period_end
)
UPDATE tblswinepopulation p
SET report_id = ins.id
FROM src JOIN ins ON ins.farmer_id = src.farmer_id AND ins.period_end = src.d
WHERE p.id = src.pop_id;

-- one closing-inventory row per report
CREATE UNIQUE INDEX IF NOT EXISTS ux_swinepop_report
  ON tblswinepopulation(report_id) WHERE report_id IS NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_swinepop_report') THEN
    ALTER TABLE tblswinepopulation
      ADD CONSTRAINT fk_swinepop_report
      FOREIGN KEY (report_id) REFERENCES tblswinereport(id) ON DELETE CASCADE;
  END IF;
END $$;

-- 5) Views ------------------------------------------------------------
DROP VIEW IF EXISTS vw_swine_reconciliation;
DROP VIEW IF EXISTS vw_swine_latest;

-- Latest VERIFIED inventory per farmer (what the dashboard should count)
CREATE VIEW vw_swine_latest AS
SELECT DISTINCT ON (r.farmer_id)
       r.id AS report_id,
       r.farmer_id,
       r.period_end,
       p.swine_population,
       COALESCE(p.boar, 0)            AS boar,
       COALESCE(p.sow, 0)             AS sow,
       COALESCE(p.gilts, 0)           AS gilts,
       COALESCE(p.piglets, 0)         AS piglets,
       COALESCE(p.grower_fattener, 0) AS grower_fattener,
       GREATEST(0, p.swine_population
         - (COALESCE(p.boar,0) + COALESCE(p.sow,0) + COALESCE(p.gilts,0)
          + COALESCE(p.piglets,0) + COALESCE(p.grower_fattener,0))) AS unclassified
FROM tblswinereport r
JOIN tblswinepopulation p ON p.report_id = r.id
WHERE r.status = 'verified'
ORDER BY r.farmer_id, r.period_end DESC;

-- Opening (= last verified closing before this period) + movements = expected closing
CREATE VIEW vw_swine_reconciliation AS
SELECT r.id AS report_id,
       r.farmer_id,
       r.period_end,
       r.status,
       prev.closing                          AS opening,
       p.swine_population                    AS closing,
       COALESCE(m.total_in, 0)               AS total_in,
       COALESCE(m.total_out, 0)              AS total_out,
       prev.closing + COALESCE(m.total_in,0) - COALESCE(m.total_out,0) AS expected_closing,
       p.swine_population
         - (prev.closing + COALESCE(m.total_in,0) - COALESCE(m.total_out,0)) AS variance
FROM tblswinereport r
JOIN tblswinepopulation p ON p.report_id = r.id
LEFT JOIN LATERAL (
  SELECT p2.swine_population AS closing
  FROM tblswinereport r2
  JOIN tblswinepopulation p2 ON p2.report_id = r2.id
  WHERE r2.farmer_id = r.farmer_id
    AND r2.status = 'verified'
    AND r2.period_end < r.period_end
  ORDER BY r2.period_end DESC
  LIMIT 1
) prev ON true
LEFT JOIN LATERAL (
  SELECT SUM(quantity) FILTER (WHERE movement_type IN ('birth','purchase','transfer_in')) AS total_in,
         SUM(quantity) FILTER (WHERE movement_type IN
           ('sale','slaughter','death','transfer_out','depopulated'))                      AS total_out
  FROM tblswinemovement WHERE report_id = r.id
) m ON true;
-- A farmer's first report has no opening, so opening and variance are NULL (baseline).

COMMIT;

-- Quick checks (run after):
-- SELECT status, count(*) FROM tblswinereport GROUP BY status;
-- SELECT count(*) FROM tblswinepopulation WHERE report_id IS NULL;   -- rows not linked
-- SELECT * FROM vw_swine_latest LIMIT 10;
