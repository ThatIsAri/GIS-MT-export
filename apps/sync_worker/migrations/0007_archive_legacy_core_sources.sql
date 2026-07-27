CREATE TABLE core_document_legacy_source (
    core_document_id BIGINT UNSIGNED NOT NULL,

    source_sync_run_id BIGINT UNSIGNED NULL,

    source_raw_response_id BIGINT UNSIGNED NULL,

    archived_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        core_document_id
    ),

    KEY ix_core_document_legacy_source_run (
        source_sync_run_id
    ),

    KEY ix_core_document_legacy_source_raw (
        source_raw_response_id
    ),

    CONSTRAINT fk_core_document_legacy_source_document
        FOREIGN KEY (
            core_document_id
        )
        REFERENCES core_document (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_core_document_legacy_source_run
        FOREIGN KEY (
            source_sync_run_id
        )
        REFERENCES sys_sync_run (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_core_document_legacy_source_raw
        FOREIGN KEY (
            source_raw_response_id
        )
        REFERENCES raw_api_response (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


INSERT INTO core_document_legacy_source (
    core_document_id,
    source_sync_run_id,
    source_raw_response_id,
    archived_at
)
SELECT
    document.id,
    document.source_sync_run_id,
    document.source_raw_response_id,
    UTC_TIMESTAMP(6)

FROM core_document AS document

WHERE document.source_sync_run_id
          IS NOT NULL

   OR document.source_raw_response_id
          IS NOT NULL

ON DUPLICATE KEY UPDATE
    core_document_id =
        VALUES(
            core_document_id
        );