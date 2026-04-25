-- Rollback for 20260423_activity_log_details.sql
-- Note: dropping these columns removes only the detailed snapshot data.
ALTER TABLE activity_logs DROP COLUMN IF EXISTS metadata;
ALTER TABLE activity_logs DROP COLUMN IF EXISTS actor_name;
ALTER TABLE activity_logs DROP COLUMN IF EXISTS new_values;
ALTER TABLE activity_logs DROP COLUMN IF EXISTS old_values;
ALTER TABLE activity_logs DROP COLUMN IF EXISTS entity_name;
ALTER TABLE activity_logs DROP COLUMN IF EXISTS entity_type;
ALTER TABLE activity_logs DROP COLUMN IF EXISTS action_type;
