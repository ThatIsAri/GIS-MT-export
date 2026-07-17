CREATE TABLE IF NOT EXISTS raw_edo_document (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    source_system VARCHAR(64)
        NOT NULL
        DEFAULT 'EDO_MANUAL',

    source_message_id VARCHAR(512) NULL,

    original_file_name VARCHAR(512) NOT NULL,
    relative_path VARCHAR(1024) NOT NULL,

    mime_type VARCHAR(128)
        NOT NULL
        DEFAULT 'application/xml',

    file_size_bytes BIGINT UNSIGNED NOT NULL,

    content_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    detected_encoding VARCHAR(64) NULL,

    xml_content LONGBLOB NOT NULL,

    xml_well_formed TINYINT(1)
        NOT NULL
        DEFAULT 0,

    parse_status VARCHAR(32)
        NOT NULL
        DEFAULT 'RAW',

    parse_error TEXT NULL,

    external_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    core_document_id BIGINT UNSIGNED NULL,

    duplicate_count INT UNSIGNED
        NOT NULL
        DEFAULT 0,

    first_imported_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3),

    last_seen_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3),

    parsed_at DATETIME(3) NULL,

    PRIMARY KEY (id),

    UNIQUE KEY uk_raw_edo_document_sha256 (
        content_sha256
    ),

    KEY ix_raw_edo_document_external_id (
        external_document_id
    ),

    KEY ix_raw_edo_document_core_id (
        core_document_id
    ),

    KEY ix_raw_edo_document_parse_status (
        parse_status
    ),

    KEY ix_raw_edo_document_first_imported (
        first_imported_at
    )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;