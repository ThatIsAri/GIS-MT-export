ALTER TABLE core_document
    DROP INDEX ix_core_document_source_run,

    DROP INDEX ix_core_document_source_raw,

    MODIFY COLUMN source_sync_run_id
        BIGINT UNSIGNED NULL
        COMMENT
        'DEPRECATED: provenance is stored in core_document_observation',

    MODIFY COLUMN source_raw_response_id
        BIGINT UNSIGNED NULL
        COMMENT
        'DEPRECATED: provenance is stored in core_document_observation';