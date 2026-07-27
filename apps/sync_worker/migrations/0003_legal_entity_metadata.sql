ALTER TABLE legal_entity
    ADD COLUMN gis_mt_name VARCHAR(512) NULL
        AFTER notes,

    ADD COLUMN gis_mt_status_code VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER gis_mt_name,

    ADD COLUMN gis_mt_status_name VARCHAR(255) NULL
        AFTER gis_mt_status_code,

    ADD COLUMN gis_mt_is_registered TINYINT(1) NULL
        AFTER gis_mt_status_name,

    ADD COLUMN gis_mt_participant_json JSON NULL
        AFTER gis_mt_is_registered,

    ADD COLUMN gis_mt_last_sync_at DATETIME(6) NULL
        AFTER gis_mt_participant_json,

    ADD COLUMN gis_mt_last_sync_status VARCHAR(16)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'NEVER'
        AFTER gis_mt_last_sync_at,

    ADD COLUMN gis_mt_last_error VARCHAR(2000) NULL
        AFTER gis_mt_last_sync_status,

    ADD KEY ix_legal_entity_gis_mt_sync (
        gis_mt_last_sync_status,
        gis_mt_last_sync_at
    ),

    ADD CONSTRAINT ck_legal_entity_gis_mt_sync_status
        CHECK (
            gis_mt_last_sync_status IN (
                'NEVER',
                'SUCCESS',
                'ERROR'
            )
        );


ALTER TABLE legal_entity_certificate
    ADD COLUMN certificate_inn VARCHAR(12)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER thumbprint,

    ADD COLUMN has_private_key TINYINT(1)
        NOT NULL DEFAULT 0
        AFTER diskontrol_profile,

    ADD COLUMN last_discovered_at DATETIME(6) NULL
        AFTER is_active,

    ADD KEY ix_legal_entity_certificate_inn (
        certificate_inn,
        is_active
    );


CREATE TABLE legal_entity_integration_config (
    legal_entity_id BIGINT UNSIGNED NOT NULL,

    true_api_enabled TINYINT(1)
        NOT NULL DEFAULT 1,

    auto_discover_certificate TINYINT(1)
        NOT NULL DEFAULT 1,

    auto_discover_product_groups TINYINT(1)
        NOT NULL DEFAULT 1,

    new_group_default_enabled TINYINT(1)
        NOT NULL DEFAULT 1,

    default_lookback_days SMALLINT UNSIGNED
        NOT NULL DEFAULT 3,

    default_request_limit SMALLINT UNSIGNED
        NOT NULL DEFAULT 100,

    default_max_list_requests INT UNSIGNED
        NOT NULL DEFAULT 1000,

    default_details_delay_ms INT UNSIGNED
        NOT NULL DEFAULT 100,

    default_batch_size SMALLINT UNSIGNED
        NOT NULL DEFAULT 50,

    default_edo_delay_ms INT UNSIGNED
        NOT NULL DEFAULT 150,

    last_metadata_sync_at DATETIME(6) NULL,

    last_metadata_sync_status VARCHAR(16)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'NEVER',

    last_metadata_sync_error VARCHAR(2000) NULL,

    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (legal_entity_id),

    CONSTRAINT fk_legal_entity_integration_config_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE CASCADE
        ON UPDATE RESTRICT,

    CONSTRAINT ck_legal_entity_integration_config_sync_status
        CHECK (
            last_metadata_sync_status IN (
                'NEVER',
                'SUCCESS',
                'ERROR'
            )
        ),

    CONSTRAINT ck_legal_entity_integration_config_lookback
        CHECK (
            default_lookback_days BETWEEN 1 AND 365
        ),

    CONSTRAINT ck_legal_entity_integration_config_request_limit
        CHECK (
            default_request_limit BETWEEN 1 AND 1000
        ),

    CONSTRAINT ck_legal_entity_integration_config_max_requests
        CHECK (
            default_max_list_requests BETWEEN 1 AND 10000
        ),

    CONSTRAINT ck_legal_entity_integration_config_batch_size
        CHECK (
            default_batch_size BETWEEN 1 AND 1000
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


INSERT IGNORE INTO legal_entity_integration_config (
    legal_entity_id,
    created_at,
    updated_at
)
SELECT
    id,
    UTC_TIMESTAMP(6),
    UTC_TIMESTAMP(6)
FROM legal_entity;


ALTER TABLE legal_entity_product_group
    ADD COLUMN gis_mt_available TINYINT(1)
        NOT NULL DEFAULT 0
        AFTER edo_delay_ms,

    ADD COLUMN gis_mt_first_seen_at DATETIME(6) NULL
        AFTER gis_mt_available,

    ADD COLUMN gis_mt_last_seen_at DATETIME(6) NULL
        AFTER gis_mt_first_seen_at,

    ADD COLUMN gis_mt_unavailable_at DATETIME(6) NULL
        AFTER gis_mt_last_seen_at,

    ADD KEY ix_legal_entity_product_group_available (
        legal_entity_id,
        gis_mt_available,
        is_enabled
    );