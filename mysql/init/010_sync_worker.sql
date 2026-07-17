CREATE TABLE IF NOT EXISTS sys_sync_run (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_uuid CHAR(36) NOT NULL,
    job_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,

    date_from VARCHAR(64) NULL,
    date_to VARCHAR(64) NULL,

    records_received INT UNSIGNED NOT NULL DEFAULT 0,

    error_code VARCHAR(128) NULL,
    error_message VARCHAR(2000) NULL,

    started_at DATETIME(6) NOT NULL,
    finished_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_sys_sync_run_uuid (
        run_uuid
    ),

    KEY ix_sys_sync_run_status_started (
        status,
        started_at
    ),

    KEY ix_sys_sync_run_job_started (
        job_type,
        started_at
    )
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS sys_api_request (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    sync_run_id BIGINT UNSIGNED NOT NULL,

    http_method VARCHAR(10) NOT NULL,
    endpoint VARCHAR(1000) NOT NULL,
    request_params JSON NULL,

    requested_at DATETIME(6) NOT NULL,
    response_received_at DATETIME(6) NULL,

    http_status SMALLINT UNSIGNED NULL,
    response_time_ms INT UNSIGNED NULL,
    attempt_number SMALLINT UNSIGNED NOT NULL DEFAULT 1,

    status VARCHAR(32) NOT NULL,
    error_message VARCHAR(2000) NULL,
    created_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    KEY ix_sys_api_request_run (
        sync_run_id
    ),

    KEY ix_sys_api_request_status_created (
        status,
        created_at
    ),

    CONSTRAINT fk_sys_api_request_run
        FOREIGN KEY (sync_run_id)
        REFERENCES sys_sync_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS raw_api_response (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    sync_run_id BIGINT UNSIGNED NOT NULL,
    api_request_id BIGINT UNSIGNED NOT NULL,

    source_system VARCHAR(64) NOT NULL,
    endpoint VARCHAR(1000) NOT NULL,
    external_entity_id VARCHAR(255) NULL,

    payload_json JSON NOT NULL,
    payload_hash CHAR(64) NOT NULL,

    received_at DATETIME(6) NOT NULL,

    processing_status VARCHAR(32)
        NOT NULL
        DEFAULT 'NEW',

    processing_error VARCHAR(2000) NULL,
    created_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    KEY ix_raw_api_response_run (
        sync_run_id
    ),

    KEY ix_raw_api_response_request (
        api_request_id
    ),

    KEY ix_raw_api_response_entity (
        source_system,
        external_entity_id
    ),

    KEY ix_raw_api_response_hash (
        payload_hash
    ),

    CONSTRAINT fk_raw_api_response_run
        FOREIGN KEY (sync_run_id)
        REFERENCES sys_sync_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_raw_api_response_request
        FOREIGN KEY (api_request_id)
        REFERENCES sys_api_request (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_unicode_ci;