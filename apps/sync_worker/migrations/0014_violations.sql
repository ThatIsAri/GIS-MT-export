CREATE TABLE IF NOT EXISTS gis_mt_product_group_dictionary (
    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    product_group_code SMALLINT UNSIGNED
        NOT NULL,

    display_name VARCHAR(512)
        NOT NULL,

    is_active TINYINT(1)
        NOT NULL DEFAULT 1,

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (product_group),

    UNIQUE KEY uq_gis_mt_product_group_code (
        product_group_code
    ),

    KEY ix_gis_mt_product_group_active (
        is_active,
        display_name
    )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


INSERT INTO gis_mt_product_group_dictionary (
    product_group,
    product_group_code,
    display_name,
    is_active
)
VALUES
    ('lp', 1, 'Предметы одежды, бельё постельное, столовое, туалетное и кухонное', 1),
    ('shoes', 2, 'Обувные товары', 1),
    ('tobacco', 3, 'Табачная продукция', 1),
    ('perfumery', 4, 'Духи и туалетная вода', 1),
    ('tires', 5, 'Шины и покрышки пневматические резиновые новые', 1),
    ('electronics', 6, 'Фотокамеры, фотовспышки и лампы-вспышки', 1),
    ('milk', 8, 'Молочная продукция', 1),
    ('bicycle', 9, 'Велосипеды и велосипедные рамы', 1),
    ('wheelchairs', 10, 'Медицинские изделия', 1),
    ('alcohol', 11, 'Алкоголь', 1),
    ('otp', 12, 'Альтернативная табачная продукция', 1),
    ('water', 13, 'Упакованная вода', 1),
    ('furs', 14, 'Товары из натурального меха', 1),
    ('beer', 15, 'Пиво и слабоалкогольные напитки', 1),
    ('ncp', 16, 'Никотиносодержащая продукция', 1),
    ('bio', 17, 'Специализированная пищевая продукция и БАД к пище', 1),
    ('antiseptic', 19, 'Антисептики и дезинфицирующие средства', 1),
    ('petfood', 20, 'Корма для животных', 1),
    ('seafood', 21, 'Морепродукты', 1),
    ('nabeer', 22, 'Безалкогольное пиво', 1),
    ('softdrinks', 23, 'Соковая продукция и безалкогольные напитки', 1),
    ('meat', 25, 'Мясные изделия', 1),
    ('vetpharma', 26, 'Ветеринарные препараты', 1),
    ('toys', 27, 'Игры и игрушки для детей', 1),
    ('radio', 28, 'Радиоэлектронная продукция', 1),
    ('titan', 31, 'Титановая металлопродукция', 1),
    ('conserve', 32, 'Консервированная продукция', 1),
    ('vegetableoil', 33, 'Растительные масла', 1),
    ('chemistry', 35, 'Косметика, бытовая химия и товары личной гигиены', 1),
    ('grocery', 37, 'Бакалейная продукция', 1),
    ('autofluids', 43, 'Моторные масла', 1),
    ('polymer', 44, 'Полимерные трубы', 1),
    ('carparts', 48, 'Автозапчасти и комплектующие транспортных средств', 1),
    ('furslp', 49, 'Натуральный мех', 1),
    ('nicotindev', 50, 'Радиоэлектронная продукция. Электронные системы доставки никотина', 1),
    ('gadgets', 51, 'Радиоэлектронная продукция. Ноутбуки и смартфоны', 1),
    ('fertilizers', 53, 'Удобрения в потребительской упаковке', 1),
    ('homeware', 54, 'Товары для дома и интерьера', 1)
ON DUPLICATE KEY UPDATE
    product_group_code = VALUES(product_group_code),
    display_name = VALUES(display_name),
    is_active = VALUES(is_active),
    updated_at = UTC_TIMESTAMP(6);


ALTER TABLE legal_entity_product_group
    ADD COLUMN violations_enabled TINYINT(1)
        NOT NULL DEFAULT 1
        AFTER gis_mt_unavailable_at,

    ADD COLUMN violations_lookback_days SMALLINT UNSIGNED
        NOT NULL DEFAULT 7
        AFTER violations_enabled,

    ADD COLUMN violations_last_success_date DATE NULL
        AFTER violations_lookback_days,

    ADD COLUMN violations_last_sync_at DATETIME(6) NULL
        AFTER violations_last_success_date,

    ADD COLUMN violations_last_sync_status VARCHAR(16)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'NEVER'
        AFTER violations_last_sync_at,

    ADD COLUMN violations_last_error VARCHAR(2000) NULL
        AFTER violations_last_sync_status,

    ADD KEY ix_legal_entity_group_violations (
        legal_entity_id,
        violations_enabled,
        product_group
    ),

    ADD CONSTRAINT ck_legal_entity_group_violations_lookback
        CHECK (
            violations_lookback_days BETWEEN 1 AND 91
        ),

    ADD CONSTRAINT ck_legal_entity_group_violations_status
        CHECK (
            violations_last_sync_status IN (
                'NEVER',
                'SUCCESS',
                'ERROR'
            )
        );


CREATE TABLE IF NOT EXISTS violation_export_run (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    run_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    legal_entity_id BIGINT UNSIGNED
        NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    product_group_code SMALLINT UNSIGNED
        NOT NULL,

    period_from DATE
        NOT NULL,

    period_to DATE
        NOT NULL,

    task_id CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    result_id CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'NEW',

    task_status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    download_status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    request_json JSON NULL,
    task_response_json JSON NULL,
    result_response_json JSON NULL,

    archive_path VARCHAR(1000) NULL,

    archive_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    archive_size BIGINT UNSIGNED NULL,

    csv_file_count INT UNSIGNED
        NOT NULL DEFAULT 0,

    row_count BIGINT UNSIGNED
        NOT NULL DEFAULT 0,

    inserted_count BIGINT UNSIGNED
        NOT NULL DEFAULT 0,

    updated_count BIGINT UNSIGNED
        NOT NULL DEFAULT 0,

    rejected_count BIGINT UNSIGNED
        NOT NULL DEFAULT 0,

    started_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    finished_at DATETIME(6) NULL,

    error_message VARCHAR(4000) NULL,

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_violation_export_run_uuid (
        run_uuid
    ),

    UNIQUE KEY uq_violation_export_task_id (
        task_id
    ),

    KEY ix_violation_export_entity_period (
        legal_entity_id,
        product_group,
        period_from,
        period_to
    ),

    KEY ix_violation_export_status (
        status,
        started_at
    ),

    CONSTRAINT fk_violation_export_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_violation_export_period
        CHECK (
            period_from <= period_to
        ),

    CONSTRAINT ck_violation_export_status
        CHECK (
            status IN (
                'NEW',
                'TASK_CREATED',
                'WAITING_RESULT',
                'DOWNLOADED',
                'COMPLETED',
                'EMPTY',
                'FAILED'
            )
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS gis_mt_violation (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    violation_key_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    legal_entity_id BIGINT UNSIGNED
        NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    product_group_code SMALLINT UNSIGNED
        NOT NULL,

    first_seen_run_id BIGINT UNSIGNED
        NOT NULL,

    last_seen_run_id BIGINT UNSIGNED
        NOT NULL,

    datamatrix_unit_id BIGINT UNSIGNED NULL,

    violation_kind VARCHAR(1000) NULL,
    violation_result VARCHAR(1000) NULL,
    registered_at DATETIME(6) NULL,

    product_group_name VARCHAR(512) NULL,
    subject_name VARCHAR(512) NULL,
    location_address VARCHAR(2000) NULL,
    document_number VARCHAR(512) NULL,

    code_text VARCHAR(2048)
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_bin
        NULL,

    code_sha256 CHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    vsd_id VARCHAR(255) NULL,
    kkt_registration_number VARCHAR(128) NULL,
    operation_at DATETIME(6) NULL,

    participant_inn VARCHAR(12)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    violation_number VARCHAR(255) NULL,

    is_nivellated TINYINT(1) NULL,

    vsd_volume DECIMAL(30, 6) NULL,
    vsd_unit VARCHAR(64) NULL,

    gis_mt_volume DECIMAL(30, 6) NULL,
    gis_mt_unit VARCHAR(64) NULL,

    volume_difference DECIMAL(30, 6) NULL,
    volume_difference_unit VARCHAR(64) NULL,

    excess_percent DECIMAL(18, 6) NULL,

    gtin CHAR(14)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    fias_id CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    municipal_district VARCHAR(1000) NULL,
    fiscal_drive_number VARCHAR(128) NULL,
    permission_mode_result VARCHAR(512) NULL,

    withdrawal_volume DECIMAL(30, 6) NULL,
    expansion_stage VARCHAR(255) NULL,

    raw_row_json JSON NOT NULL,

    first_seen_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    last_seen_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_gis_mt_violation_key (
        violation_key_sha256
    ),

    KEY ix_gis_mt_violation_entity_operation (
        legal_entity_id,
        operation_at
    ),

    KEY ix_gis_mt_violation_number (
        violation_number
    ),

    KEY ix_gis_mt_violation_code (
        code_sha256
    ),

    KEY ix_gis_mt_violation_gtin (
        gtin
    ),

    KEY ix_gis_mt_violation_kkt (
        kkt_registration_number,
        operation_at
    ),

    KEY ix_gis_mt_violation_nivellated (
        is_nivellated,
        registered_at
    ),

    KEY ix_gis_mt_violation_datamatrix (
        datamatrix_unit_id
    ),

    CONSTRAINT fk_gis_mt_violation_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_gis_mt_violation_first_run
        FOREIGN KEY (first_seen_run_id)
        REFERENCES violation_export_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_gis_mt_violation_last_run
        FOREIGN KEY (last_seen_run_id)
        REFERENCES violation_export_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_gis_mt_violation_datamatrix
        FOREIGN KEY (datamatrix_unit_id)
        REFERENCES datamatrix_unit (id)
        ON DELETE SET NULL
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS violation_import_reject (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    export_run_id BIGINT UNSIGNED
        NOT NULL,

    csv_file_name VARCHAR(512) NULL,
    source_row_number BIGINT UNSIGNED NULL,
    error_message VARCHAR(4000) NOT NULL,
    raw_row_json JSON NULL,

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    KEY ix_violation_reject_run (
        export_run_id,
        source_row_number
    ),

    CONSTRAINT fk_violation_reject_run
        FOREIGN KEY (export_run_id)
        REFERENCES violation_export_run (id)
        ON DELETE CASCADE
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;