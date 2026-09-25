-- Smart Detector / SimplePay - complete schema for a NEW database (local XAMPP or Render's external MySQL).
--   mysql -h HOST -u USER -p DBNAME < php_backend/schema.sql
-- Create the database first if needed:  CREATE DATABASE fraud_detection CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- This replaces the old phpMyAdmin dump (transactions.sql), which was stale: it lacked the columns that
-- transaction_api.php now inserts (merchant_category, country, location_*, device_*, clock_skew_seconds ...).

CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    account_number VARCHAR(32) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS transactions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    transaction_id VARCHAR(80) NOT NULL,
    transaction_type VARCHAR(128) NOT NULL,
    description TEXT NULL,
    recipient VARCHAR(256) NULL,
    merchant VARCHAR(256) NULL,
    merchant_category VARCHAR(64) NULL,
    amount DECIMAL(14,2) NOT NULL,

    -- named model inputs
    oldbalanceOrg DOUBLE NULL,
    newbalanceOrig DOUBLE NULL,
    oldbalanceDest DOUBLE NULL,
    newbalanceDest DOUBLE NULL,
    time_hour INT NULL,
    merchant_risk DECIMAL(10,4) NULL,

    -- context captured by the sandbox
    country VARCHAR(8) NULL,
    location_latitude DECIMAL(10,7) NULL,
    location_longitude DECIMAL(10,7) NULL,
    location_accuracy_m DECIMAL(10,2) NULL,
    location_source VARCHAR(32) NULL,
    location_timestamp BIGINT UNSIGNED NULL,
    device_time_ms BIGINT UNSIGNED NULL,
    device_timezone VARCHAR(128) NULL,
    device_timezone_offset_minutes SMALLINT NULL,
    server_received_timestamp BIGINT UNSIGNED NULL,
    clock_skew_seconds DECIMAL(12,3) NULL,

    transaction_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_timestamp BIGINT UNSIGNED NOT NULL,
    `Time` DOUBLE NULL DEFAULT 0,

    -- model output
    risk_score INT NULL,
    is_fraudulent TINYINT(1) NOT NULL DEFAULT 0,
    risk_level VARCHAR(64) NULL,
    model_scores LONGTEXT NULL,
    explanation LONGTEXT NULL,
    feature_snapshot LONGTEXT NULL,
    model_reason TEXT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_transaction_id (transaction_id),
    KEY idx_created (created_at),
    KEY idx_fraud (is_fraudulent, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
