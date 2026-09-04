-- library explorer: track storage origin
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS storage_source VARCHAR(20) DEFAULT 'internal';
