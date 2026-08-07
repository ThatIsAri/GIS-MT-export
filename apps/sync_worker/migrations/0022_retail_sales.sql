-- Хранилище корректных розничных продаж ГИС МТ.
--
-- Источник: отчёт «Количество и объём выведенных из оборота товаров»,
-- отфильтрованный по причине «Розничная продажа» и основанию «Чек».
-- Данные сохраняются посуточно, потому что CSV отчёта не содержит дату
-- операции, а дашборду требуется произвольное суммирование по периоду.

ALTER TABLE legal_entity_product_group
    ADD COLUMN sales_enabled TINYINT(1)
        NOT NULL DEFAULT 1
        AFTER violations_last_error,

    ADD COLUMN sales_lookback_days SMALLINT UNSIGNED
        NOT NULL DEFAULT 90
        AFTER sales_enabled,

    ADD COLUMN sales_last_success_date DATE NULL
        AFTER sales_lookback_days,

    ADD COLUMN sales_last_sync_at DATETIME(6) NULL
        AFTER sales_last_success_date,

    ADD COLUMN sales_last_sync_status VARCHAR(16)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'NEVER'
        AFTER sales_last_sync_at,

    ADD COLUMN sales_last_error VARCHAR(2000) NULL
        AFTER sales_last_sync_status,

    ADD KEY ix_legal_entity_group_sales (
        legal_entity_id,
        sales_enabled,
        product_group
    ),

    ADD CONSTRAINT ck_legal_entity_group_sales_lookback
        CHECK (
            sales_lookback_days BETWEEN 1 AND 366
        ),

    ADD CONSTRAINT ck_legal_entity_group_sales_status
        CHECK (
            sales_last_sync_status IN (
                'NEVER',
                'SUCCESS',
                'ERROR'
            )
        );


CREATE TABLE IF NOT EXISTS sales_export_run (
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

    report_id VARCHAR(128)
        CHARACTER SET ascii
        COLLATE ascii_bin
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

    rejected_count BIGINT UNSIGNED
        NOT NULL DEFAULT 0,

    total_quantity DECIMAL(30, 6)
        NOT NULL DEFAULT 0,

    total_amount DECIMAL(30, 2)
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

    UNIQUE KEY uq_sales_export_run_uuid (
        run_uuid
    ),

    UNIQUE KEY uq_sales_export_task_id (
        task_id
    ),

    KEY ix_sales_export_entity_period (
        legal_entity_id,
        product_group,
        period_from,
        period_to
    ),

    KEY ix_sales_export_status (
        status,
        started_at
    ),

    CONSTRAINT fk_sales_export_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_sales_export_period
        CHECK (
            period_from <= period_to
        ),

    CONSTRAINT ck_sales_export_status
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


CREATE TABLE IF NOT EXISTS gis_mt_retail_sale_daily (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    sale_key_sha256 CHAR(64)
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

    sale_date DATE
        NOT NULL,

    source_run_id BIGINT UNSIGNED
        NOT NULL,

    participant_inn VARCHAR(12)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    participant_name VARCHAR(512) NULL,

    gtin VARCHAR(14)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    tnved VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    okpd2 VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL,

    package_type VARCHAR(128) NULL,
    product_type VARCHAR(512) NULL,
    manufacturer VARCHAR(1000) NULL,

    package_quantity DECIMAL(30, 6) NULL,
    package_unit VARCHAR(128) NULL,

    product_name VARCHAR(1000) NULL,

    withdrawal_reason VARCHAR(512) NULL,
    turnover_reason VARCHAR(512) NULL,

    region_name VARCHAR(512) NULL,
    sales_point_address VARCHAR(2000) NULL,

    sold_quantity DECIMAL(30, 6)
        NOT NULL DEFAULT 0,

    sold_amount DECIMAL(30, 2) NULL,

    raw_row_json JSON NULL,

    created_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_gis_mt_retail_sale_key (
        sale_key_sha256
    ),

    KEY ix_gis_mt_retail_sale_period (
        sale_date,
        legal_entity_id,
        product_group
    ),

    KEY ix_gis_mt_retail_sale_gtin (
        gtin,
        sale_date
    ),

    KEY ix_gis_mt_retail_sale_address (
        legal_entity_id,
        sales_point_address(255),
        sale_date
    ),

    KEY ix_gis_mt_retail_sale_run (
        source_run_id
    ),

    CONSTRAINT fk_gis_mt_retail_sale_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_gis_mt_retail_sale_run
        FOREIGN KEY (source_run_id)
        REFERENCES sales_export_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT ck_gis_mt_retail_sale_quantity
        CHECK (
            sold_quantity >= 0
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


CREATE TABLE IF NOT EXISTS sales_import_reject (
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

    KEY ix_sales_reject_run (
        export_run_id,
        source_row_number
    ),

    CONSTRAINT fk_sales_reject_run
        FOREIGN KEY (export_run_id)
        REFERENCES sales_export_run (id)
        ON DELETE CASCADE
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;
