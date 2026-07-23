ALTER TABLE sys_sync_run
    ADD COLUMN legal_entity_id BIGINT UNSIGNED NULL
        AFTER id,

    ADD COLUMN product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER job_type,

    ADD KEY ix_sys_sync_run_entity_job_started (
        legal_entity_id,
        job_type,
        started_at
    ),

    ADD KEY ix_sys_sync_run_entity_group_started (
        legal_entity_id,
        product_group,
        started_at
    ),

    ADD CONSTRAINT fk_sys_sync_run_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    ADD CONSTRAINT fk_sys_sync_run_entity_product_group
        FOREIGN KEY (
            legal_entity_id,
            product_group
        )
        REFERENCES legal_entity_product_group (
            legal_entity_id,
            product_group
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    ADD CONSTRAINT ck_sys_sync_run_product_group_scope
        CHECK (
            product_group IS NULL
            OR legal_entity_id IS NOT NULL
        );


CREATE TABLE legal_entity_document (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    legal_entity_id BIGINT UNSIGNED NOT NULL,
    core_document_id BIGINT UNSIGNED NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    first_seen_sync_run_id BIGINT UNSIGNED NOT NULL,
    last_seen_sync_run_id BIGINT UNSIGNED NOT NULL,

    first_seen_raw_response_id BIGINT UNSIGNED NOT NULL,
    last_seen_raw_response_id BIGINT UNSIGNED NOT NULL,

    first_seen_at DATETIME(6) NOT NULL,
    last_seen_at DATETIME(6) NOT NULL,

    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uq_legal_entity_document_scope (
        legal_entity_id,
        core_document_id,
        product_group
    ),

    KEY ix_legal_entity_document_entity_group (
        legal_entity_id,
        product_group,
        last_seen_at
    ),

    KEY ix_legal_entity_document_core (
        core_document_id,
        legal_entity_id
    ),

    KEY ix_legal_entity_document_first_run (
        first_seen_sync_run_id
    ),

    KEY ix_legal_entity_document_last_run (
        last_seen_sync_run_id
    ),

    KEY ix_legal_entity_document_first_raw (
        first_seen_raw_response_id
    ),

    KEY ix_legal_entity_document_last_raw (
        last_seen_raw_response_id
    ),

    CONSTRAINT fk_legal_entity_document_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_legal_entity_document_core
        FOREIGN KEY (core_document_id)
        REFERENCES core_document (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_legal_entity_document_product_group
        FOREIGN KEY (
            legal_entity_id,
            product_group
        )
        REFERENCES legal_entity_product_group (
            legal_entity_id,
            product_group
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_legal_entity_document_first_run
        FOREIGN KEY (first_seen_sync_run_id)
        REFERENCES sys_sync_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_legal_entity_document_last_run
        FOREIGN KEY (last_seen_sync_run_id)
        REFERENCES sys_sync_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_legal_entity_document_first_raw
        FOREIGN KEY (first_seen_raw_response_id)
        REFERENCES raw_api_response (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_legal_entity_document_last_raw
        FOREIGN KEY (last_seen_raw_response_id)
        REFERENCES raw_api_response (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_legal_entity_document_seen_at
        CHECK (
            first_seen_at <= last_seen_at
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;