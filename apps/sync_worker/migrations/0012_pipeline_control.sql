CREATE TABLE IF NOT EXISTS sys_pipeline_config (
    id TINYINT UNSIGNED NOT NULL,

    pipeline_enabled TINYINT(1)
        NOT NULL DEFAULT 0,

    autorun_enabled TINYINT(1)
        NOT NULL DEFAULT 0,

    autorun_running TINYINT(1)
        NOT NULL DEFAULT 0,

    schedule_code VARCHAR(16)
        NOT NULL DEFAULT 'DAILY',

    starts_at_utc DATETIME(6) NULL,

    last_autorun_slot_utc DATETIME(6) NULL,

    last_autorun_status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'IDLE',

    last_autorun_started_at DATETIME(6) NULL,

    last_autorun_finished_at DATETIME(6) NULL,

    last_autorun_message VARCHAR(1000)
        NOT NULL DEFAULT '',

    current_run_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    current_run_mode VARCHAR(16)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    current_run_started_at DATETIME(6) NULL,

    current_run_heartbeat_at DATETIME(6) NULL,

    authorization_enabled TINYINT(1)
        NOT NULL DEFAULT 1,

    export_upd_enabled TINYINT(1)
        NOT NULL DEFAULT 0,

    export_period_from DATE NULL,

    export_period_to DATE NULL,

    process_upd_enabled TINYINT(1)
        NOT NULL DEFAULT 0,

    test_running TINYINT(1)
        NOT NULL DEFAULT 0,

    last_test_status VARCHAR(32)
        NOT NULL DEFAULT 'IDLE',

    last_test_requested_at DATETIME(6) NULL,

    last_test_message VARCHAR(1000)
        NOT NULL DEFAULT '',

    updated_by VARCHAR(128)
        NOT NULL DEFAULT 'system',

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT ck_sys_pipeline_config_autorun_running
        CHECK (
            autorun_running IN (
                0,
                1
            )
        ),

    CONSTRAINT ck_sys_pipeline_config_current_run_mode
        CHECK (
            current_run_mode IS NULL
            OR current_run_mode IN (
                'TEST',
                'AUTORUN'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS sys_pipeline_task_entity (
    task_code VARCHAR(32) NOT NULL,

    legal_entity_id BIGINT UNSIGNED NOT NULL,

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        task_code,
        legal_entity_id
    ),

    KEY ix_pipeline_task_entity_entity (
        legal_entity_id
    )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


INSERT IGNORE INTO sys_pipeline_config (
    id
)
VALUES (
    1
);