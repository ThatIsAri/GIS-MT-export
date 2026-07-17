CREATE TABLE IF NOT EXISTS core_document (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    external_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    doc_date DATETIME(3) NULL,
    received_at DATETIME(3) NULL,

    document_type VARCHAR(128) NULL,
    document_status VARCHAR(64) NULL,

    sender_inn VARCHAR(16) NULL,
    sender_name VARCHAR(512) NULL,

    receiver_inn VARCHAR(16) NULL,
    receiver_name VARCHAR(512) NULL,

    invoice_number VARCHAR(255) NULL,
    invoice_date DATETIME(3) NULL,

    related_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    turnover_type VARCHAR(64) NULL,

    product_groups JSON NULL,
    product_group_ids JSON NULL,
    errors_json JSON NULL,

    source_item_count INT UNSIGNED NOT NULL DEFAULT 1,

    normalization_status VARCHAR(32)
        NOT NULL
        DEFAULT 'OK',

    normalization_conflicts JSON NULL,

    source_sync_run_id BIGINT UNSIGNED NOT NULL,
    source_raw_response_id BIGINT UNSIGNED NOT NULL,

    first_seen_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3),

    last_seen_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3),

    created_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3),

    updated_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),

    UNIQUE KEY uk_core_document_external_id (
        external_document_id
    ),

    KEY ix_core_document_received_at (
        received_at
    ),

    KEY ix_core_document_doc_date (
        doc_date
    ),

    KEY ix_core_document_invoice (
        invoice_number,
        invoice_date
    ),

    KEY ix_core_document_sender_inn (
        sender_inn
    ),

    KEY ix_core_document_receiver_inn (
        receiver_inn
    ),

    KEY ix_core_document_source_run (
        source_sync_run_id
    ),

    KEY ix_core_document_source_raw (
        source_raw_response_id
    )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;