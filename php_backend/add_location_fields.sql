-- Run once against the fraud_detection database used by transaction_api.php.
-- Existing rows remain valid because all new fields are nullable.

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS location_latitude DECIMAL(10,7) NULL,
    ADD COLUMN IF NOT EXISTS location_longitude DECIMAL(10,7) NULL,
    ADD COLUMN IF NOT EXISTS location_accuracy_m DECIMAL(10,2) NULL,
    ADD COLUMN IF NOT EXISTS location_source VARCHAR(32) NULL;
