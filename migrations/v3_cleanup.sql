-- v3 Cleanup Migration
-- Removes all push-based delivery and SRS legacy tables/columns.

-- 1. Drop the delivery_queue table (push-based scheduled delivery)
DROP TABLE IF EXISTS delivery_queue;

-- 2. Drop push-only columns from users table
ALTER TABLE users DROP COLUMN preferred_delivery_minute;
ALTER TABLE users DROP COLUMN active_window_start_minute;
ALTER TABLE users DROP COLUMN active_window_end_minute;
ALTER TABLE users DROP COLUMN daily_reminder_cap;
ALTER TABLE users DROP COLUMN reminder_cap_updated_at;
