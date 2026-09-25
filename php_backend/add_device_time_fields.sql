-- Run once against the fraud_detection database.
-- These fields preserve the distinct client, location, and server clocks.

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS location_timestamp BIGINT UNSIGNED NULL,
    ADD COLUMN IF NOT EXISTS device_time_ms BIGINT UNSIGNED NULL,
    ADD COLUMN IF NOT EXISTS device_timezone VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS device_timezone_offset_minutes SMALLINT NULL,
    ADD COLUMN IF NOT EXISTS server_received_timestamp BIGINT UNSIGNED NULL,
    ADD COLUMN IF NOT EXISTS clock_skew_seconds DECIMAL(12,3) NULL;