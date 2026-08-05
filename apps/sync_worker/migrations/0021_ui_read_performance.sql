SET @schema_name = DATABASE();


SELECT COUNT(*)
INTO @event_at_exists
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = @schema_name
  AND TABLE_NAME = 'gis_mt_violation'
  AND COLUMN_NAME = 'event_at';

SET @migration_sql = IF(
    @event_at_exists = 0,
    'ALTER TABLE gis_mt_violation ADD COLUMN event_at DATETIME(6) GENERATED ALWAYS AS (COALESCE(operation_at, registered_at)) STORED AFTER operation_at',
    'DO 0'
);

PREPARE migration_statement FROM @migration_sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;


SELECT COUNT(*)
INTO @violation_event_index_exists
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = @schema_name
  AND TABLE_NAME = 'gis_mt_violation'
  AND INDEX_NAME = 'ix_gis_mt_violation_event';

SET @migration_sql = IF(
    @violation_event_index_exists = 0,
    'ALTER TABLE gis_mt_violation ADD KEY ix_gis_mt_violation_event (event_at, id)',
    'DO 0'
);

PREPARE migration_statement FROM @migration_sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;


SELECT COUNT(*)
INTO @violation_entity_event_index_exists
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = @schema_name
  AND TABLE_NAME = 'gis_mt_violation'
  AND INDEX_NAME = 'ix_gis_mt_violation_entity_event';

SET @migration_sql = IF(
    @violation_entity_event_index_exists = 0,
    'ALTER TABLE gis_mt_violation ADD KEY ix_gis_mt_violation_entity_event (legal_entity_id, event_at, id)',
    'DO 0'
);

PREPARE migration_statement FROM @migration_sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;


SELECT COUNT(*)
INTO @violation_nivellated_event_index_exists
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = @schema_name
  AND TABLE_NAME = 'gis_mt_violation'
  AND INDEX_NAME = 'ix_gis_mt_violation_nivellated_event';

SET @migration_sql = IF(
    @violation_nivellated_event_index_exists = 0,
    'ALTER TABLE gis_mt_violation ADD KEY ix_gis_mt_violation_nivellated_event (is_nivellated, event_at, id)',
    'DO 0'
);

PREPARE migration_statement FROM @migration_sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;


SELECT COUNT(*)
INTO @violation_kind_event_index_exists
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = @schema_name
  AND TABLE_NAME = 'gis_mt_violation'
  AND INDEX_NAME = 'ix_gis_mt_violation_kind_event';

SET @migration_sql = IF(
    @violation_kind_event_index_exists = 0,
    'ALTER TABLE gis_mt_violation ADD KEY ix_gis_mt_violation_kind_event (violation_kind(191), event_at, id)',
    'DO 0'
);

PREPARE migration_statement FROM @migration_sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;


SELECT COALESCE(
    GROUP_CONCAT(
        COLUMN_NAME
        ORDER BY SEQ_IN_INDEX
        SEPARATOR ','
    ),
    ''
)
INTO @datamatrix_entity_gtin_date_columns
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = @schema_name
  AND TABLE_NAME = 'datamatrix_unit'
  AND INDEX_NAME = 'ix_datamatrix_unit_entity_gtin_date';

SET @migration_sql = CASE
    WHEN @datamatrix_entity_gtin_date_columns =
         'legal_entity_id,gtin,source_document_date,id'
        THEN 'DO 0'

    WHEN @datamatrix_entity_gtin_date_columns = ''
        THEN 'ALTER TABLE datamatrix_unit ADD KEY ix_datamatrix_unit_entity_gtin_date (legal_entity_id, gtin, source_document_date, id)'

    ELSE 'ALTER TABLE datamatrix_unit DROP INDEX ix_datamatrix_unit_entity_gtin_date, ADD KEY ix_datamatrix_unit_entity_gtin_date (legal_entity_id, gtin, source_document_date, id)'
END;

PREPARE migration_statement FROM @migration_sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;