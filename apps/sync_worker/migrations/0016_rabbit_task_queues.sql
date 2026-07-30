ALTER TABLE sys_sync_job
    DROP INDEX uq_sys_sync_job_active_entity,
    DROP CHECK ck_sys_sync_job_type,
    DROP COLUMN active_legal_entity_id,

    ADD COLUMN parent_job_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER job_type,

    ADD COLUMN active_job_key VARCHAR(128)
        CHARACTER SET ascii
        COLLATE ascii_bin
        GENERATED ALWAYS AS (
            CASE
                WHEN status IN (
                    'CREATED',
                    'PUBLISHED',
                    'PROCESSING',
                    'RETRY_WAIT'
                )
                THEN CONCAT(
                    job_type,
                    ':',
                    legal_entity_id
                )
                ELSE NULL
            END
        )
        STORED
        AFTER lock_version,

    ADD UNIQUE KEY uq_sys_sync_job_active_task (
        active_job_key
    ),

    ADD KEY ix_sys_sync_job_parent (
        parent_job_uuid
    ),

    ADD CONSTRAINT fk_sys_sync_job_parent
        FOREIGN KEY (
            parent_job_uuid
        )
        REFERENCES sys_sync_job (
            job_uuid
        )
        ON DELETE SET NULL
        ON UPDATE RESTRICT,

    ADD CONSTRAINT ck_sys_sync_job_type
        CHECK (
            job_type IN (
                'SYNC_LEGAL_ENTITY',
                'EXPORT_UPD',
                'PROCESS_UPD',
                'TRACK_VIOLATIONS'
            )
        );


CREATE TABLE upd_download_file (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    legal_entity_id BIGINT UNSIGNED NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    details_run_id BIGINT UNSIGNED NOT NULL,
    core_document_id BIGINT UNSIGNED NOT NULL,

    document_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    relative_path VARCHAR(1000) NOT NULL,

    content_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    file_size_bytes BIGINT UNSIGNED NOT NULL,

    status VARCHAR(24)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'DOWNLOADED',

    raw_document_id BIGINT UNSIGNED NULL,

    processing_job_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    downloaded_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    processed_at DATETIME(6) NULL,

    last_error_type VARCHAR(128)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    last_error_message VARCHAR(2000) NULL,

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_upd_download_file (
        details_run_id,
        core_document_id,
        content_sha256
    ),

    KEY ix_upd_download_file_entity_status (
        legal_entity_id,
        status,
        downloaded_at
    ),

    KEY ix_upd_download_file_run_status (
        details_run_id,
        status
    ),

    KEY ix_upd_download_file_processing_job (
        processing_job_uuid
    ),

    CONSTRAINT fk_upd_download_file_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_upd_download_file_run
        FOREIGN KEY (details_run_id)
        REFERENCES sys_sync_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_upd_download_file_core
        FOREIGN KEY (core_document_id)
        REFERENCES core_document (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_upd_download_file_raw
        FOREIGN KEY (raw_document_id)
        REFERENCES raw_edo_document (id)
        ON DELETE SET NULL
        ON UPDATE RESTRICT,

    CONSTRAINT fk_upd_download_file_processing_job
        FOREIGN KEY (processing_job_uuid)
        REFERENCES sys_sync_job (job_uuid)
        ON DELETE SET NULL
        ON UPDATE RESTRICT,

    CONSTRAINT ck_upd_download_file_status
        CHECK (
            status IN (
                'DOWNLOADED',
                'PROCESSING',
                'PROCESSED',
                'ERROR'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;
