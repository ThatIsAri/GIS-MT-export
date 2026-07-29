CREATE TABLE datamatrix_unit (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    code_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    code_text VARCHAR(2048)
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_bin
        NOT NULL,

    code_value VARBINARY(8192)
        NOT NULL,

    legal_entity_id BIGINT UNSIGNED
        NOT NULL,

    core_document_id BIGINT UNSIGNED
        NOT NULL,

    raw_edo_document_id BIGINT UNSIGNED
        NOT NULL,

    document_line_id BIGINT UNSIGNED
        NOT NULL,

    source_document_code_id BIGINT UNSIGNED
        NOT NULL,

    external_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    product_name VARCHAR(1024)
        NULL,

    product_code VARCHAR(512)
        NULL,

    quantity DECIMAL(30, 6)
        NOT NULL
        DEFAULT 1.000000,

    source_line_quantity DECIMAL(30, 6)
        NULL,

    receiver_warehouse_address VARCHAR(2000)
        NULL,

    source_document_date DATE
        NULL,

    first_seen_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    last_seen_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    created_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_datamatrix_unit_code (
        code_sha256
    ),

    UNIQUE KEY uq_datamatrix_unit_source_code (
        source_document_code_id
    ),

    KEY ix_datamatrix_unit_entity (
        legal_entity_id,
        product_name(191)
    ),

    KEY ix_datamatrix_unit_document (
        core_document_id,
        source_document_date
    ),

    KEY ix_datamatrix_unit_raw_document (
        raw_edo_document_id
    ),

    KEY ix_datamatrix_unit_product_code (
        product_code
    ),

    KEY ix_datamatrix_unit_address (
        receiver_warehouse_address(191)
    ),

    CONSTRAINT fk_datamatrix_unit_entity
        FOREIGN KEY (
            legal_entity_id
        )
        REFERENCES legal_entity (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_core_document
        FOREIGN KEY (
            core_document_id
        )
        REFERENCES core_document (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_raw_document
        FOREIGN KEY (
            raw_edo_document_id
        )
        REFERENCES raw_edo_document (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_line
        FOREIGN KEY (
            document_line_id
        )
        REFERENCES core_document_line (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_source_code
        FOREIGN KEY (
            source_document_code_id
        )
        REFERENCES core_document_code (
            id
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_datamatrix_unit_quantity
        CHECK (
            quantity > 0
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;