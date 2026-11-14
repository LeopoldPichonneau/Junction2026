-- One row per article = what Wikipedia shows today; every past revision is a history row,
-- written with its real Wikipedia date (see server/load_versions.py).
-- The `article` table follows the official MariaDB example
-- https://github.com/MariaDB/mariadb-system-versioning-wikipedia (MIT licence).
CREATE TABLE IF NOT EXISTS article (
  page_id    INT UNSIGNED NOT NULL,
  title      VARCHAR(255) NOT NULL,
  rev_id     INT UNSIGNED NOT NULL,
  parent_id  INT UNSIGNED,
  user       VARCHAR(255),             -- stays in the database; never returned by the public API
  anonymous  BOOL NOT NULL DEFAULT 0,
  comment    TEXT,
  minor      BOOL NOT NULL DEFAULT 0,
  sha1       CHAR(31),
  len        INT UNSIGNED,
  text       MEDIUMTEXT COMPRESSED NOT NULL,
  row_start  TIMESTAMP(6) GENERATED ALWAYS AS ROW START INVISIBLE,
  row_end    TIMESTAMP(6) GENERATED ALWAYS AS ROW END INVISIBLE,
  PERIOD FOR SYSTEM_TIME (row_start, row_end),
  PRIMARY KEY (page_id),
  KEY (sha1), KEY (rev_id), KEY (user),
  KEY start_key (page_id, row_start)   -- keeps old "as of" dates fast
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING;

-- Imported from data/exchange/*.jsonl by server/import_jsonl.py
CREATE TABLE IF NOT EXISTS candidate (
  rev_id INT UNSIGNED PRIMARY KEY, page_id INT UNSIGNED NOT NULL, title VARCHAR(255),
  kind ENUM('framing','image','sources','coordination') NOT NULL,
  edited_at DATETIME(6) NOT NULL, account_hash CHAR(16), synthetic BOOL NOT NULL DEFAULT 0,
  data JSON NOT NULL,                  -- the full JSONL line
  KEY (page_id), KEY (kind)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS analysis (
  rev_id INT UNSIGNED PRIMARY KEY, model VARCHAR(120) NOT NULL,
  suspicious BOOL, data JSON NOT NULL
) CHARACTER SET utf8mb4;

-- Versioned: we can prove when a case was published or withdrawn.
CREATE TABLE IF NOT EXISTS decision (
  rev_id INT UNSIGNED PRIMARY KEY,
  decision ENUM('flag','dismiss','human_review') NOT NULL,
  publish BOOL NOT NULL DEFAULT 0, confidence FLOAT,
  days_live FLOAT, readers_est INT UNSIGNED, still_online BOOL,
  data JSON NOT NULL
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING;

CREATE TABLE IF NOT EXISTS account_profile (
  account_hash CHAR(16) PRIMARY KEY,
  kind ENUM('declared_bot','bot_like','throwaway','single_purpose','normal') NOT NULL,
  score FLOAT, data JSON NOT NULL
) CHARACTER SET utf8mb4;

-- Precomputed while loading, so /api/articles and /api/articles/{id}/timeline never
-- run a GROUP BY over 862,000 rows.
CREATE TABLE IF NOT EXISTS article_stats (
  page_id INT UNSIGNED PRIMARY KEY, title VARCHAR(255) NOT NULL,
  versions INT UNSIGNED NOT NULL, first_edit DATE NOT NULL, last_edit DATE NOT NULL,
  -- For /api/articles?q=. This file only runs on an empty base; on an existing one, run:
  -- CREATE INDEX IF NOT EXISTS title_key ON article_stats (title);
  KEY title_key (title)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS article_timeline (
  page_id INT UNSIGNED NOT NULL, month CHAR(7) NOT NULL,   -- 'YYYY-MM'
  edits INT UNSIGNED NOT NULL, reverts INT UNSIGNED NOT NULL,
  PRIMARY KEY (page_id, month)
) CHARACTER SET utf8mb4;
