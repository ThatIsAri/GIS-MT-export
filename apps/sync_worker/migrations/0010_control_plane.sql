ALTER TABLE legal_entity
    ADD COLUMN storage_slug VARCHAR(160)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER timezone_name;

UPDATE legal_entity
SET storage_slug = CONCAT(
    'entity_',
    id,
    '_',
    inn
)
WHERE storage_slug IS NULL;

ALTER TABLE legal_entity
    MODIFY COLUMN storage_slug VARCHAR(160)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    ADD UNIQUE KEY uq_legal_entity_storage_slug (
        storage_slug
    );


CREATE TABLE sys_control_agent (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    agent_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    host_name VARCHAR(255) NOT NULL,

    agent_version VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    status VARCHAR(16)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'ONLINE',

    current_certificate_thumbprint CHAR(40)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    current_certificate_inn VARCHAR(12)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    capabilities_json JSON NULL,

    last_seen_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_sys_control_agent_uuid (
        agent_uuid
    ),

    KEY ix_sys_control_agent_last_seen (
        last_seen_at,
        status
    ),

    CONSTRAINT ck_sys_control_agent_status
        CHECK (
            status IN (
                'ONLINE',
                'OFFLINE',
                'DISABLED'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE sys_control_agent_certificate (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    agent_id BIGINT UNSIGNED NOT NULL,
    legal_entity_id BIGINT UNSIGNED NOT NULL,
    certificate_id BIGINT UNSIGNED NOT NULL,

    thumbprint CHAR(40)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    certificate_inn VARCHAR(12)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    store_location VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    store_name VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    is_present TINYINT(1)
        NOT NULL DEFAULT 1,

    first_seen_at DATETIME(6) NOT NULL,
    last_seen_at DATETIME(6) NOT NULL,
    last_missing_at DATETIME(6) NULL,

    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_sys_control_agent_certificate (
        agent_id,
        thumbprint
    ),

    KEY ix_sys_control_agent_certificate_presence (
        agent_id,
        is_present,
        last_seen_at
    ),

    KEY ix_sys_control_agent_certificate_entity (
        legal_entity_id,
        is_present
    ),

    CONSTRAINT fk_sys_control_agent_certificate_agent
        FOREIGN KEY (agent_id)
        REFERENCES sys_control_agent (id)
        ON DELETE CASCADE
        ON UPDATE RESTRICT,

    CONSTRAINT fk_sys_control_agent_certificate_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_sys_control_agent_certificate_certificate
        FOREIGN KEY (certificate_id)
        REFERENCES legal_entity_certificate (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_sys_control_agent_certificate_store
        CHECK (
            store_location IN (
                'CurrentUser',
                'LocalMachine'
            )
        ),

    CONSTRAINT ck_sys_control_agent_certificate_present
        CHECK (
            is_present IN (
                0,
                1
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE sys_auth_job (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    job_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    legal_entity_id BIGINT UNSIGNED NOT NULL,

    requested_by VARCHAR(128) NOT NULL,
    requested_at DATETIME(6) NOT NULL,

    status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'PENDING',

    claimed_by_agent_id BIGINT UNSIGNED NULL,

    certificate_thumbprint CHAR(40)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    claimed_at DATETIME(6) NULL,
    started_at DATETIME(6) NULL,
    finished_at DATETIME(6) NULL,

    sync_job_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    last_error_type VARCHAR(128)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    last_error_message VARCHAR(2000) NULL,

    result_json JSON NULL,

    active_legal_entity_id BIGINT UNSIGNED
        GENERATED ALWAYS AS (
            CASE
                WHEN status IN (
                    'PENDING',
                    'WAITING_CERTIFICATE',
                    'PROCESSING'
                )
                THEN legal_entity_id

                ELSE NULL
            END
        )
        STORED,

    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_sys_auth_job_uuid (
        job_uuid
    ),

    UNIQUE KEY uq_sys_auth_job_active_entity (
        active_legal_entity_id
    ),

    KEY ix_sys_auth_job_status_requested (
        status,
        requested_at
    ),

    KEY ix_sys_auth_job_agent_status (
        claimed_by_agent_id,
        status
    ),

    KEY ix_sys_auth_job_sync_job (
        sync_job_uuid
    ),

    CONSTRAINT fk_sys_auth_job_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_sys_auth_job_agent
        FOREIGN KEY (claimed_by_agent_id)
        REFERENCES sys_control_agent (id)
        ON DELETE SET NULL
        ON UPDATE RESTRICT,

    CONSTRAINT ck_sys_auth_job_status
        CHECK (
            status IN (
                'PENDING',
                'WAITING_CERTIFICATE',
                'PROCESSING',
                'SUCCESS',
                'ERROR',
                'CANCELLED'
            )
        ),

    CONSTRAINT ck_sys_auth_job_terminal_finished
        CHECK (
            status NOT IN (
                'SUCCESS',
                'ERROR',
                'CANCELLED'
            )
            OR finished_at IS NOT NULL
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;