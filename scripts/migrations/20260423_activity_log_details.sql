-- Safe, non-destructive migration for detailed activity log snapshots.
-- All newly added columns are nullable by design.
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS action_type VARCHAR;
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS entity_type VARCHAR;
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS entity_name VARCHAR;
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS old_values JSON;
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS new_values JSON;
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS actor_name VARCHAR;
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS metadata JSON;
