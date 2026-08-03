CREATE TABLE fine_matrix_rule (
    id BIGINT UNSIGNED
        NOT NULL
        AUTO_INCREMENT,

    rule_code VARCHAR(128)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    violation_name VARCHAR(1000)
        NOT NULL,

    product_scope VARCHAR(1000)
        NULL,

    calculation_mode VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    aggregation_scope VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    quantity_from INT UNSIGNED
        NULL,

    quantity_to INT UNSIGNED
        NULL,

    individual_entrepreneur_amount DECIMAL(15, 2)
        NOT NULL,

    legal_entity_amount DECIMAL(15, 2)
        NOT NULL,

    statutory_default_individual_amount DECIMAL(15, 2)
        NOT NULL,

    statutory_default_legal_amount DECIMAL(15, 2)
        NOT NULL,

    effective_from DATE
        NOT NULL,

    legal_basis VARCHAR(500)
        NOT NULL,

    calculation_note VARCHAR(1000)
        NULL,

    sort_order INT UNSIGNED
        NOT NULL,

    is_active TINYINT(1)
        NOT NULL
        DEFAULT 1,

    created_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_fine_matrix_rule_code (
        rule_code
    ),

    KEY ix_fine_matrix_rule_active_order (
        is_active,
        sort_order,
        id
    ),

    KEY ix_fine_matrix_rule_effective (
        effective_from,
        is_active
    ),

    CONSTRAINT ck_fine_matrix_rule_ip_amount
        CHECK (
            individual_entrepreneur_amount >= 0
        ),

    CONSTRAINT ck_fine_matrix_rule_legal_amount
        CHECK (
            legal_entity_amount >= 0
        ),

    CONSTRAINT ck_fine_matrix_rule_default_ip_amount
        CHECK (
            statutory_default_individual_amount >= 0
        ),

    CONSTRAINT ck_fine_matrix_rule_default_legal_amount
        CHECK (
            statutory_default_legal_amount >= 0
        ),

    CONSTRAINT ck_fine_matrix_rule_quantity
        CHECK (
            quantity_from IS NULL
            OR quantity_to IS NULL
            OR quantity_from <= quantity_to
        )
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


INSERT INTO fine_matrix_rule (
    rule_code,
    violation_name,
    product_scope,
    calculation_mode,
    aggregation_scope,
    quantity_from,
    quantity_to,
    individual_entrepreneur_amount,
    legal_entity_amount,
    statutory_default_individual_amount,
    statutory_default_legal_amount,
    effective_from,
    legal_basis,
    calculation_note,
    sort_order
)
VALUES
(
    'EXPIRED_MARKED_PRODUCT_PER_UNIT',

    'Продажа маркированного товара с истекшим сроком годности после получения запрета продажи из ГИС МТ',

    'Все товары, подлежащие обязательной маркировке, для которых ГИС МТ передала информацию о запрете продажи из-за истекшего срока годности',

    'PER_UNIT',
    'SOLD_UNIT',

    1,
    NULL,

    10000.00,
    20000.00,

    10000.00,
    20000.00,

    '2026-09-01',

    'КоАП РФ, часть 4 статьи 14.43; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Штраф умножается на количество проданных единиц просроченного товара.',

    10
),
(
    'TOBACCO_PRICE_BELOW_LIMIT_001_100',

    'Продажа табачной продукции ниже МРЦ или никотинсодержащей продукции ниже минимальной цены: не более 100 единиц',

    'Табачная и никотинсодержащая продукция',

    'FIXED_TIER',
    'RETAIL_OBJECT_DAY',

    1,
    100,

    5000.00,
    5000.00,

    5000.00,
    5000.00,

    '2026-09-01',

    'КоАП РФ, часть 6 статьи 14.3.1; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Количество определяется в одном объекте розничной торговли за один календарный день.',

    20
),
(
    'TOBACCO_PRICE_BELOW_LIMIT_101_1000',

    'Продажа табачной продукции ниже МРЦ или никотинсодержащей продукции ниже минимальной цены: от 101 до 1000 единиц',

    'Табачная и никотинсодержащая продукция',

    'FIXED_TIER',
    'RETAIL_OBJECT_DAY',

    101,
    1000,

    50000.00,
    50000.00,

    50000.00,
    50000.00,

    '2026-09-01',

    'КоАП РФ, часть 7 статьи 14.3.1; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Количество определяется в одном объекте розничной торговли за один календарный день.',

    30
),
(
    'TOBACCO_PRICE_BELOW_LIMIT_OVER_1000',

    'Продажа табачной продукции ниже МРЦ или никотинсодержащей продукции ниже минимальной цены: более 1000 единиц',

    'Табачная и никотинсодержащая продукция',

    'FIXED_TIER',
    'RETAIL_OBJECT_DAY',

    1001,
    NULL,

    500000.00,
    500000.00,

    500000.00,
    500000.00,

    '2026-09-01',

    'КоАП РФ, часть 8 статьи 14.3.1; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Количество определяется в одном объекте розничной торговли за один календарный день.',

    40
),
(
    'TOBACCO_PRICE_ABOVE_MRP_001_100',

    'Продажа табачной продукции выше максимальной розничной цены: не более 100 единиц',

    'Табачная продукция',

    'FIXED_TIER',
    'RETAIL_OBJECT_DAY',

    1,
    100,

    5000.00,
    5000.00,

    5000.00,
    5000.00,

    '2026-09-01',

    'КоАП РФ, часть 4 статьи 14.6; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Количество определяется в одном объекте розничной торговли за один календарный день.',

    50
),
(
    'TOBACCO_PRICE_ABOVE_MRP_101_1000',

    'Продажа табачной продукции выше максимальной розничной цены: от 101 до 1000 единиц',

    'Табачная продукция',

    'FIXED_TIER',
    'RETAIL_OBJECT_DAY',

    101,
    1000,

    50000.00,
    50000.00,

    50000.00,
    50000.00,

    '2026-09-01',

    'КоАП РФ, часть 5 статьи 14.6; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Количество определяется в одном объекте розничной торговли за один календарный день.',

    60
),
(
    'TOBACCO_PRICE_ABOVE_MRP_OVER_1000',

    'Продажа табачной продукции выше максимальной розничной цены: более 1000 единиц',

    'Табачная продукция',

    'FIXED_TIER',
    'RETAIL_OBJECT_DAY',

    1001,
    NULL,

    500000.00,
    500000.00,

    500000.00,
    500000.00,

    '2026-09-01',

    'КоАП РФ, часть 6 статьи 14.6; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Количество определяется в одном объекте розничной торговли за один календарный день.',

    70
),
(
    'TOBACCO_SALE_WITHOUT_GIS_MT_REGISTRATION',

    'Продажа без регистрации продавца в ГИС МТ: более 10 единиц за календарный месяц через одну ККТ',

    'Табачная продукция, никотинсодержащая продукция и устройства для потребления никотинсодержащей продукции',

    'FIXED_TIER',
    'KKT_MONTH',

    11,
    NULL,

    50000.00,
    50000.00,

    50000.00,
    50000.00,

    '2026-09-01',

    'КоАП РФ, статья 15.12.2; Федеральный закон от 02.05.2026 № 120-ФЗ',

    'Количество определяется за один календарный месяц отдельно по каждой единице ККТ.',

    80
);