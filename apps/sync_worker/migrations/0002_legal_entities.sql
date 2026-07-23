CREATE TABLE IF NOT EXISTS legal_entity (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    entity_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    inn VARCHAR(12)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    kpp VARCHAR(9)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    short_name VARCHAR(255) NOT NULL,
    full_name VARCHAR(512) NULL,

    entity_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'SETUP',

    timezone_name VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'Europe/Moscow',

    notes VARCHAR(2000) NULL,

    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_legal_entity_uuid (
        entity_uuid
    ),

    UNIQUE KEY uq_legal_entity_inn (
        inn
    ),

    KEY ix_legal_entity_status_name (
        status,
        short_name
    ),

    CONSTRAINT ck_legal_entity_type
        CHECK (
            entity_type IN (
                'LEGAL_ENTITY',
                'INDIVIDUAL_ENTREPRENEUR'
            )
        ),

    CONSTRAINT ck_legal_entity_status
        CHECK (
            status IN (
                'SETUP',
                'ACTIVE',
                'SUSPENDED',
                'DISABLED'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS legal_entity_certificate (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    legal_entity_id BIGINT UNSIGNED NOT NULL,

    thumbprint CHAR(40)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    subject_name VARCHAR(1000) NULL,
    serial_number VARCHAR(128) NULL,
    issuer_name VARCHAR(1000) NULL,

    valid_from DATETIME(6) NULL,
    valid_to DATETIME(6) NULL,

    store_location VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'CurrentUser',

    store_name VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'My',

    provider_name VARCHAR(255) NULL,

    diskontrol_profile VARCHAR(255) NULL,

    is_active TINYINT(1)
        NOT NULL
        DEFAULT 1,

    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_legal_entity_certificate_thumbprint (
        thumbprint
    ),

    KEY ix_legal_entity_certificate_entity_active (
        legal_entity_id,
        is_active
    ),

    KEY ix_legal_entity_certificate_valid_to (
        valid_to
    ),

    CONSTRAINT fk_legal_entity_certificate_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_legal_entity_certificate_store
        CHECK (
            store_location IN (
                'CurrentUser',
                'LocalMachine'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS legal_entity_product_group (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    legal_entity_id BIGINT UNSIGNED NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    is_enabled TINYINT(1)
        NOT NULL
        DEFAULT 1,

    schedule_enabled TINYINT(1)
        NOT NULL
        DEFAULT 0,

    schedule_cron VARCHAR(255)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    lookback_days SMALLINT UNSIGNED
        NOT NULL
        DEFAULT 3,

    request_limit SMALLINT UNSIGNED
        NOT NULL
        DEFAULT 100,

    max_list_requests INT UNSIGNED
        NOT NULL
        DEFAULT 1000,

    details_delay_ms INT UNSIGNED
        NOT NULL
        DEFAULT 100,

    batch_size SMALLINT UNSIGNED
        NOT NULL
        DEFAULT 50,

    edo_delay_ms INT UNSIGNED
        NOT NULL
        DEFAULT 150,

    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_legal_entity_product_group (
        legal_entity_id,
        product_group
    ),

    KEY ix_legal_entity_product_group_schedule (
        schedule_enabled,
        is_enabled,
        product_group
    ),

    CONSTRAINT fk_legal_entity_product_group_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_legal_entity_product_group_lookback
        CHECK (
            lookback_days BETWEEN 1 AND 365
        ),

    CONSTRAINT ck_legal_entity_product_group_limit
        CHECK (
            request_limit BETWEEN 1 AND 1000
        ),

    CONSTRAINT ck_legal_entity_product_group_max_requests
        CHECK (
            max_list_requests BETWEEN 1 AND 10000
        ),

    CONSTRAINT ck_legal_entity_product_group_batch_size
        CHECK (
            batch_size BETWEEN 1 AND 1000
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;