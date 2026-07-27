CREATE TABLE sys_sync_job (
    id BIGINT UNSIGNED
        NOT NULL
        AUTO_INCREMENT,

    job_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    schema_version SMALLINT UNSIGNED
        NOT NULL
        DEFAULT 1,

    job_type VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    legal_entity_id BIGINT UNSIGNED
        NOT NULL,

    requested_by VARCHAR(128)
        NOT NULL,

    requested_at DATETIME(6)
        NOT NULL,

    date_from DATETIME(6)
        NULL,

    date_to DATETIME(6)
        NULL,

    skip_edo TINYINT(1)
        NOT NULL
        DEFAULT 0,

    force_edo TINYINT(1)
        NOT NULL
        DEFAULT 0,

    edo_fail_fast TINYINT(1)
        NOT NULL
        DEFAULT 0,

    continue_on_error TINYINT(1)
        NOT NULL
        DEFAULT 0,

    payload_json JSON
        NOT NULL,

    status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    retry_count INT UNSIGNED
        NOT NULL
        DEFAULT 0,

    max_retries INT UNSIGNED
        NOT NULL,

    attempt_count INT UNSIGNED
        NOT NULL
        DEFAULT 0,

    queue_name VARCHAR(255)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    routing_key VARCHAR(255)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    last_message_id VARCHAR(255)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    correlation_id VARCHAR(255)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    worker_id VARCHAR(128)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    first_started_at DATETIME(6)
        NULL,

    last_started_at DATETIME(6)
        NULL,

    last_heartbeat_at DATETIME(6)
        NULL,

    lease_expires_at DATETIME(6)
        NULL,

    retry_available_at DATETIME(6)
        NULL,

    published_at DATETIME(6)
        NULL,

    finished_at DATETIME(6)
        NULL,

    last_error_type VARCHAR(128)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    last_error_message VARCHAR(2000)
        NULL,

    result_json JSON
        NULL,

    lock_version BIGINT UNSIGNED
        NOT NULL
        DEFAULT 0,

    active_legal_entity_id BIGINT UNSIGNED
        GENERATED ALWAYS AS (
            CASE
                WHEN status IN (
                    'CREATED',
                    'PUBLISHED',
                    'PROCESSING',
                    'RETRY_WAIT'
                )
                THEN legal_entity_id

                ELSE NULL
            END
        )
        STORED,

    created_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        id
    ),

    UNIQUE KEY uq_sys_sync_job_uuid (
        job_uuid
    ),

    UNIQUE KEY uq_sys_sync_job_active_entity (
        active_legal_entity_id
    ),

    KEY ix_sys_sync_job_entity_requested (
        legal_entity_id,
        requested_at
    ),

    KEY ix_sys_sync_job_status_requested (
        status,
        requested_at
    ),

    KEY ix_sys_sync_job_retry_available (
        status,
        retry_available_at
    ),

    KEY ix_sys_sync_job_lease (
        status,
        lease_expires_at
    ),

    CONSTRAINT fk_sys_sync_job_legal_entity
        FOREIGN KEY (
            legal_entity_id
        )
        REFERENCES legal_entity (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_sys_sync_job_type
        CHECK (
            job_type = 'SYNC_LEGAL_ENTITY'
        ),

    CONSTRAINT ck_sys_sync_job_status
        CHECK (
            status IN (
                'CREATED',
                'PUBLISHED',
                'PROCESSING',
                'RETRY_WAIT',
                'SUCCESS',
                'DEAD',
                'CANCELLED'
            )
        ),

    CONSTRAINT ck_sys_sync_job_date_range
        CHECK (
            date_from IS NULL
            OR date_to IS NULL
            OR date_from < date_to
        ),

    CONSTRAINT ck_sys_sync_job_skip_edo
        CHECK (
            skip_edo IN (
                0,
                1
            )
        ),

    CONSTRAINT ck_sys_sync_job_force_edo
        CHECK (
            force_edo IN (
                0,
                1
            )
        ),

    CONSTRAINT ck_sys_sync_job_edo_fail_fast
        CHECK (
            edo_fail_fast IN (
                0,
                1
            )
        ),

    CONSTRAINT ck_sys_sync_job_continue_on_error
        CHECK (
            continue_on_error IN (
                0,
                1
            )
        ),

    CONSTRAINT ck_sys_sync_job_retry_count
        CHECK (
            retry_count <= max_retries
        ),

    CONSTRAINT ck_sys_sync_job_terminal_finished
        CHECK (
            status NOT IN (
                'SUCCESS',
                'DEAD',
                'CANCELLED'
            )
            OR finished_at IS NOT NULL
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;