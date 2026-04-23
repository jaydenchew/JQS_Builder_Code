-- WA Unified Database Schema
-- Merged from Builder (system_new) + JQS (JQS_Code)
-- 14 tables: arms, stations, phones, bank_apps, transactions, transaction_logs,
--            flow_templates, flow_steps, ui_elements, keymaps, swipe_actions,
--            keyboard_configs, bank_name_mappings, calibrations

CREATE DATABASE IF NOT EXISTS wa_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE wa_db;

-- arms (multi-machine: camera_id + active flag)
CREATE TABLE IF NOT EXISTS arms (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(50) NOT NULL,
    com_port VARCHAR(10) NOT NULL,
    service_url VARCHAR(255) NOT NULL,
    z_down INT NOT NULL DEFAULT 10,
    camera_id INT NOT NULL DEFAULT 0 COMMENT 'OpenCV camera device index',
    max_x FLOAT NOT NULL DEFAULT 90 COMMENT 'Hard X movement limit (mm). Builder refuses to move beyond this.',
    max_y FLOAT NOT NULL DEFAULT 120 COMMENT 'Hard Y movement limit (mm). Builder refuses to move beyond this.',
    active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'false = paused/debug, worker skips this arm',
    status ENUM('idle', 'busy', 'offline') NOT NULL DEFAULT 'idle',
    stall_reason VARCHAR(50) NULL COMMENT 'Classified stall reason: ocr_mismatch/screen_mismatch/camera_fail/arm_hw_error/flow_not_found/step_failed/unknown',
    stall_details TEXT NULL COMMENT 'Stall step name + error message',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- stations
CREATE TABLE IF NOT EXISTS stations (
    id INT PRIMARY KEY AUTO_INCREMENT,
    arm_id INT NOT NULL,
    name VARCHAR(10) NOT NULL,
    x_offset FLOAT NOT NULL DEFAULT 0 COMMENT 'Reference only, not applied at runtime',
    stall_photo_x FLOAT NULL COMMENT 'Arm X position for stall screenshot (full phone view)',
    stall_photo_y FLOAT NULL COMMENT 'Arm Y position for stall screenshot (full phone view)',
    status ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    FOREIGN KEY (arm_id) REFERENCES arms(id)
) ENGINE=InnoDB;

-- phones
CREATE TABLE IF NOT EXISTS phones (
    id INT PRIMARY KEY AUTO_INCREMENT,
    station_id INT NOT NULL,
    name VARCHAR(50) NOT NULL,
    model VARCHAR(100),
    status ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    FOREIGN KEY (station_id) REFERENCES stations(id)
) ENGINE=InnoDB;

-- bank_apps
CREATE TABLE IF NOT EXISTS bank_apps (
    id INT PRIMARY KEY AUTO_INCREMENT,
    phone_id INT NOT NULL,
    station_id INT NOT NULL,
    bank_code VARCHAR(20) NOT NULL,
    bank_name VARCHAR(100) NOT NULL,
    account_no VARCHAR(50) NOT NULL,
    password VARCHAR(100) NOT NULL,
    pin VARCHAR(100) NULL COMMENT 'APP PIN for random keypad banks',
    status ENUM('active', 'suspended') NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phone_id) REFERENCES phones(id),
    FOREIGN KEY (station_id) REFERENCES stations(id),
    UNIQUE KEY uk_bank_account (station_id, bank_code, account_no)
) ENGINE=InnoDB;

-- transactions
CREATE TABLE IF NOT EXISTS transactions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    process_id INT NOT NULL UNIQUE,
    currency_code VARCHAR(10) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    pay_from_bank_code VARCHAR(20) NOT NULL,
    pay_from_account_no VARCHAR(50) NOT NULL,
    pay_to_bank_code VARCHAR(20) NOT NULL,
    pay_to_account_no VARCHAR(50) NOT NULL,
    pay_to_account_name VARCHAR(100) NOT NULL,
    bank_app_id INT NULL,
    station_id INT NULL,
    status ENUM('pending', 'queued', 'running', 'success', 'failed', 'review', 'stall') NOT NULL DEFAULT 'pending',
    receipt_base64 LONGTEXT NULL,
    error_message VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    callback_sent_at DATETIME NULL,
    INDEX idx_status (status),
    INDEX idx_process_id (process_id),
    INDEX idx_station_id (station_id),
    INDEX idx_bank_app_id (bank_app_id)
) ENGINE=InnoDB;

-- transaction_logs
CREATE TABLE IF NOT EXISTS transaction_logs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    transaction_id INT NOT NULL,
    step_number INT NOT NULL,
    step_name VARCHAR(100) NOT NULL,
    action_type VARCHAR(20) NOT NULL,
    result ENUM('ok', 'fail') NOT NULL,
    duration_ms INT NULL,
    screenshot_base64 LONGTEXT NULL,
    ocr_text TEXT NULL,
    expected_value VARCHAR(255) NULL,
    message TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id),
    INDEX idx_transaction (transaction_id)
) ENGINE=InnoDB;

-- flow_templates (with arm_id binding + transfer_type + amount_format)
CREATE TABLE IF NOT EXISTS flow_templates (
    id INT PRIMARY KEY AUTO_INCREMENT,
    bank_code VARCHAR(20) NOT NULL,
    arm_id INT NULL COMMENT 'NULL=legacy/universal, specific=per-arm flow',
    name VARCHAR(100) NOT NULL,
    total_steps INT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    status ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    transfer_type VARCHAR(10) NULL DEFAULT NULL COMMENT 'NULL=default, SAME=same bank, INTER=interbank',
    amount_format VARCHAR(20) NULL DEFAULT NULL COMMENT 'NULL/decimal=12.34, no_dot=1234, always_decimal=12.00',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_bank_arm_version_type (bank_code, arm_id, version, transfer_type)
) ENGINE=InnoDB;

-- flow_steps
CREATE TABLE IF NOT EXISTS flow_steps (
    id INT PRIMARY KEY AUTO_INCREMENT,
    flow_template_id INT NOT NULL,
    step_number INT NOT NULL,
    step_name VARCHAR(100) NOT NULL,
    action_type ENUM('CLICK', 'TYPE', 'SWIPE', 'PHOTO', 'ARM_MOVE', 'OCR_VERIFY', 'CHECK_SCREEN') NOT NULL,
    ui_element_key VARCHAR(50) NULL,
    keymap_type VARCHAR(50) NULL,
    swipe_key VARCHAR(50) NULL,
    input_source VARCHAR(50) NULL,
    tap_count INT NOT NULL DEFAULT 1,
    pre_delay_ms INT NOT NULL DEFAULT 0,
    post_delay_ms INT NOT NULL DEFAULT 0,
    description TEXT NULL,
    FOREIGN KEY (flow_template_id) REFERENCES flow_templates(id),
    INDEX idx_flow_step (flow_template_id, step_number)
) ENGINE=InnoDB;

-- ui_elements
CREATE TABLE IF NOT EXISTS ui_elements (
    id INT PRIMARY KEY AUTO_INCREMENT,
    bank_code VARCHAR(20) NULL COMMENT 'NULL = station-level shared element',
    station_id INT NOT NULL,
    element_key VARCHAR(50) NOT NULL,
    x FLOAT NOT NULL,
    y FLOAT NOT NULL,
    FOREIGN KEY (station_id) REFERENCES stations(id),
    INDEX idx_lookup (bank_code, station_id, element_key)
) ENGINE=InnoDB;

-- keymaps
CREATE TABLE IF NOT EXISTS keymaps (
    id INT PRIMARY KEY AUTO_INCREMENT,
    bank_code VARCHAR(20) NOT NULL,
    station_id INT NOT NULL,
    keyboard_type VARCHAR(50) NOT NULL,
    key_char VARCHAR(5) NOT NULL,
    x FLOAT NOT NULL,
    y FLOAT NOT NULL,
    FOREIGN KEY (station_id) REFERENCES stations(id),
    INDEX idx_lookup (bank_code, station_id, keyboard_type, key_char)
) ENGINE=InnoDB;

-- swipe_actions
CREATE TABLE IF NOT EXISTS swipe_actions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    bank_code VARCHAR(20) NULL COMMENT 'NULL = station-level (close_app)',
    station_id INT NOT NULL,
    swipe_key VARCHAR(50) NOT NULL,
    start_x FLOAT NOT NULL,
    start_y FLOAT NOT NULL,
    end_x FLOAT NOT NULL,
    end_y FLOAT NOT NULL,
    FOREIGN KEY (station_id) REFERENCES stations(id),
    INDEX idx_lookup (bank_code, station_id, swipe_key)
) ENGINE=InnoDB;

-- keyboard_configs — multi-page keyboard definitions for intelligent typing
CREATE TABLE IF NOT EXISTS keyboard_configs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    bank_code VARCHAR(20) NOT NULL,
    station_id INT NOT NULL,
    keyboard_type VARCHAR(50) NOT NULL,
    config JSON NOT NULL COMMENT 'Full keyboard config: pages, keys, switch rules, properties',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (station_id) REFERENCES stations(id),
    UNIQUE KEY uk_keyboard (bank_code, station_id, keyboard_type)
) ENGINE=InnoDB;

-- bank_name_mappings — cross-bank transfer: PAS short code -> APP search text
CREATE TABLE IF NOT EXISTS bank_name_mappings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    from_bank_code VARCHAR(20) NOT NULL COMMENT 'The bank APP performing the transfer',
    to_bank_code VARCHAR(20) NOT NULL COMMENT 'PAS short code for destination bank',
    search_text VARCHAR(100) NOT NULL COMMENT 'Text to type in search box',
    display_name VARCHAR(200) NULL COMMENT 'Full display name in search results',
    UNIQUE KEY uk_from_to (from_bank_code, to_bank_code)
) ENGINE=InnoDB;

-- calibrations — per-station pixel-to-arm transform data
CREATE TABLE IF NOT EXISTS calibrations (
    id INT PRIMARY KEY AUTO_INCREMENT,
    station_id INT NOT NULL UNIQUE,
    transform_matrix JSON NOT NULL COMMENT '2x3 affine matrix [[a,b,c],[d,e,f]]',
    camera_park_x FLOAT NOT NULL DEFAULT 91.0,
    camera_park_y FLOAT NOT NULL DEFAULT 58.0,
    scale_mm_per_pixel FLOAT NOT NULL DEFAULT 0.204,
    rotation_degrees FLOAT NOT NULL DEFAULT 90.0,
    raw_height INT NOT NULL DEFAULT 480,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (station_id) REFERENCES stations(id)
) ENGINE=InnoDB;

-- Seed data is in seed.sql (exported from builder-mysql)
