ALTER TABLE gis_mt_violation
    DROP FOREIGN KEY fk_gis_mt_violation_datamatrix;


DROP TABLE IF EXISTS datamatrix_unit;


CREATE TABLE datamatrix_product (
    gtin CHAR(14)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    product_name VARCHAR(1024) NULL,
    brand VARCHAR(512) NULL,
    package_type VARCHAR(128) NULL,
    product_group VARCHAR(128) NULL,

    raw_payload_json JSON NULL,
    fetched_at DATETIME(6) NOT NULL,

    created_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (gtin),

    KEY ix_datamatrix_product_name (
        product_name(191)
    ),

    CONSTRAINT ck_datamatrix_product_gtin
        CHECK (
            gtin REGEXP '^[0-9]{14}$'
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE datamatrix_source_code (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    code_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    code_text VARCHAR(2048)
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_bin
        NOT NULL,

    code_value VARBINARY(8192) NOT NULL,

    legal_entity_id BIGINT UNSIGNED NOT NULL,
    core_document_id BIGINT UNSIGNED NOT NULL,
    raw_edo_document_id BIGINT UNSIGNED NOT NULL,
    document_line_id BIGINT UNSIGNED NOT NULL,
    source_document_code_id BIGINT UNSIGNED NOT NULL,

    external_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    document_product_name VARCHAR(1024) NULL,
    product_code VARCHAR(512) NULL,

    source_gtin CHAR(14)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    source_line_quantity DECIMAL(30, 6) NULL,

    source_line_code_count INT UNSIGNED NOT NULL,

    expected_unit_count DECIMAL(30, 6) NULL,

    actual_unit_count INT UNSIGNED
        NOT NULL
        DEFAULT 0,

    code_kind VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    expansion_status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    quantity_match_status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    expansion_error VARCHAR(2000) NULL,

    receiver_warehouse_address VARCHAR(2000) NULL,

    source_document_date DATE NULL,

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

    UNIQUE KEY uq_datamatrix_source_code_hash (
        code_sha256
    ),

    KEY ix_datamatrix_source_code_entity (
        legal_entity_id,
        source_document_date
    ),

    KEY ix_datamatrix_source_code_document (
        core_document_id,
        raw_edo_document_id
    ),

    KEY ix_datamatrix_source_code_line (
        document_line_id
    ),

    KEY ix_datamatrix_source_code_source (
        source_document_code_id
    ),

    KEY ix_datamatrix_source_code_gtin (
        source_gtin
    ),

    KEY ix_datamatrix_source_code_status (
        expansion_status,
        quantity_match_status
    ),

    CONSTRAINT fk_datamatrix_source_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_source_core_document
        FOREIGN KEY (core_document_id)
        REFERENCES core_document (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_source_raw_document
        FOREIGN KEY (raw_edo_document_id)
        REFERENCES raw_edo_document (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_source_line
        FOREIGN KEY (document_line_id)
        REFERENCES core_document_line (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_source_document_code
        FOREIGN KEY (source_document_code_id)
        REFERENCES core_document_code (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_datamatrix_source_line_code_count
        CHECK (
            source_line_code_count > 0
        ),

    CONSTRAINT ck_datamatrix_source_actual_count
        CHECK (
            actual_unit_count >= 0
        ),

    CONSTRAINT ck_datamatrix_source_kind
        CHECK (
            code_kind IN (
                'UNIT',
                'AGGREGATE'
            )
        ),

    CONSTRAINT ck_datamatrix_source_expansion_status
        CHECK (
            expansion_status IN (
                'UNIT',
                'EXPANDED',
                'ERROR'
            )
        ),

    CONSTRAINT ck_datamatrix_source_quantity_status
        CHECK (
            quantity_match_status IN (
                'MATCHED',
                'MISMATCH',
                'NOT_CHECKED'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


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

    code_value VARBINARY(8192) NOT NULL,

    source_code_id BIGINT UNSIGNED NOT NULL,

    legal_entity_id BIGINT UNSIGNED NOT NULL,
    core_document_id BIGINT UNSIGNED NOT NULL,
    raw_edo_document_id BIGINT UNSIGNED NOT NULL,
    document_line_id BIGINT UNSIGNED NOT NULL,
    source_document_code_id BIGINT UNSIGNED NOT NULL,

    external_document_id VARCHAR(512)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    gtin CHAR(14)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    product_name VARCHAR(1024) NULL,

    product_name_source VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    document_product_name VARCHAR(1024) NULL,

    product_code VARCHAR(512) NULL,

    quantity DECIMAL(30, 6)
        NOT NULL
        DEFAULT 1.000000,

    source_line_quantity DECIMAL(30, 6) NULL,

    receiver_warehouse_address VARCHAR(2000) NULL,

    source_document_date DATE NULL,

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

    KEY ix_datamatrix_unit_source_code (
        source_code_id
    ),

    KEY ix_datamatrix_unit_entity (
        legal_entity_id,
        source_document_date
    ),

    KEY ix_datamatrix_unit_document (
        core_document_id,
        raw_edo_document_id
    ),

    KEY ix_datamatrix_unit_line (
        document_line_id
    ),

    KEY ix_datamatrix_unit_source_document_code (
        source_document_code_id
    ),

    KEY ix_datamatrix_unit_gtin_date (
        gtin,
        source_document_date,
        id
    ),

    KEY ix_datamatrix_unit_product_name (
        product_name(191)
    ),

    KEY ix_datamatrix_unit_address (
        receiver_warehouse_address(191)
    ),

    CONSTRAINT fk_datamatrix_unit_source
        FOREIGN KEY (source_code_id)
        REFERENCES datamatrix_source_code (id)
        ON DELETE CASCADE
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_core_document
        FOREIGN KEY (core_document_id)
        REFERENCES core_document (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_raw_document
        FOREIGN KEY (raw_edo_document_id)
        REFERENCES raw_edo_document (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_line
        FOREIGN KEY (document_line_id)
        REFERENCES core_document_line (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_datamatrix_unit_source_document_code
        FOREIGN KEY (source_document_code_id)
        REFERENCES core_document_code (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_datamatrix_unit_quantity
        CHECK (
            quantity = 1.000000
        ),

    CONSTRAINT ck_datamatrix_unit_name_source
        CHECK (
            product_name_source IN (
                'GIS_MT_PRODUCT',
                'EDO_DOCUMENT',
                'UNKNOWN'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE datamatrix_aggregation_edge (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    source_code_id BIGINT UNSIGNED NOT NULL,

    parent_code_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    parent_code_text VARCHAR(2048)
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_bin
        NOT NULL,

    child_code_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    child_code_text VARCHAR(2048)
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_bin
        NOT NULL,

    child_gtin CHAR(14)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    depth INT UNSIGNED NOT NULL,

    is_terminal TINYINT(1) NOT NULL,

    created_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_datamatrix_edge (
        source_code_id,
        parent_code_sha256,
        child_code_sha256
    ),

    KEY ix_datamatrix_edge_parent (
        parent_code_sha256
    ),

    KEY ix_datamatrix_edge_child (
        child_code_sha256
    ),

    KEY ix_datamatrix_edge_terminal (
        source_code_id,
        is_terminal,
        depth
    ),

    CONSTRAINT fk_datamatrix_edge_source
        FOREIGN KEY (source_code_id)
        REFERENCES datamatrix_source_code (id)
        ON DELETE CASCADE
        ON UPDATE RESTRICT,

    CONSTRAINT ck_datamatrix_edge_depth
        CHECK (
            depth > 0
        ),

    CONSTRAINT ck_datamatrix_edge_terminal
        CHECK (
            is_terminal IN (
                0,
                1
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


ALTER TABLE gis_mt_violation
    ADD CONSTRAINT fk_gis_mt_violation_datamatrix
        FOREIGN KEY (datamatrix_unit_id)
        REFERENCES datamatrix_unit (id)
        ON DELETE SET NULL
        ON UPDATE RESTRICT;