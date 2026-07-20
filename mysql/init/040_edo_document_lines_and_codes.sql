CREATE TABLE IF NOT EXISTS core_document_line (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    raw_edo_document_id BIGINT UNSIGNED NOT NULL,
    core_document_id BIGINT UNSIGNED NULL,

    external_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    line_number INT UNSIGNED NOT NULL,
    source_line_number VARCHAR(64) NOT NULL,

    product_name VARCHAR(1024) NULL,
    product_code VARCHAR(512) NULL,

    unit_code VARCHAR(32) NULL,
    unit_name VARCHAR(128) NULL,

    quantity DECIMAL(30, 6) NULL,
    unit_price DECIMAL(30, 6) NULL,

    amount_without_vat DECIMAL(30, 2) NULL,
    vat_rate VARCHAR(32) NULL,
    vat_amount DECIMAL(30, 2) NULL,
    amount_with_vat DECIMAL(30, 2) NULL,

    source_payload_hash CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    created_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3),

    updated_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),

    UNIQUE KEY uk_core_document_line_raw_line (
        raw_edo_document_id,
        line_number
    ),

    KEY ix_core_document_line_core (
        core_document_id
    ),

    KEY ix_core_document_line_external (
        external_document_id
    ),

    KEY ix_core_document_line_product_code (
        product_code
    )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS core_document_code (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    raw_edo_document_id BIGINT UNSIGNED NOT NULL,
    core_document_id BIGINT UNSIGNED NULL,
    document_line_id BIGINT UNSIGNED NOT NULL,

    external_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    line_number INT UNSIGNED NOT NULL,
    sequence_number INT UNSIGNED NOT NULL,

    source_element_name VARCHAR(128) NOT NULL,
    source_code_type VARCHAR(64) NOT NULL,

    transport_package_identifier VARCHAR(512) NULL,

    code_text VARCHAR(2048)
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_bin
        NOT NULL,

    code_value VARBINARY(8192) NOT NULL,

    code_char_length INT UNSIGNED NOT NULL,
    code_byte_length INT UNSIGNED NOT NULL,

    code_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    created_at DATETIME(3)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),

    UNIQUE KEY uk_core_document_code_source (
        raw_edo_document_id,
        document_line_id,
        sequence_number,
        code_sha256
    ),

    KEY ix_core_document_code_core (
        core_document_id
    ),

    KEY ix_core_document_code_line (
        document_line_id
    ),

    KEY ix_core_document_code_external (
        external_document_id
    ),

    KEY ix_core_document_code_hash (
        code_sha256
    ),

    KEY ix_core_document_code_source_type (
        source_code_type
    )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;