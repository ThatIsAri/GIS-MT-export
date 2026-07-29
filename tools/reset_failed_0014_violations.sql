DROP TABLE IF EXISTS violation_import_reject;
DROP TABLE IF EXISTS gis_mt_violation;
DROP TABLE IF EXISTS violation_export_run;
DROP TABLE IF EXISTS gis_mt_product_group_dictionary;


ALTER TABLE legal_entity_product_group
    DROP CHECK ck_legal_entity_group_violations_lookback,

    DROP CHECK ck_legal_entity_group_violations_status,

    DROP INDEX ix_legal_entity_group_violations,

    DROP COLUMN violations_last_error,

    DROP COLUMN violations_last_sync_status,

    DROP COLUMN violations_last_sync_at,

    DROP COLUMN violations_last_success_date,

    DROP COLUMN violations_lookback_days,

    DROP COLUMN violations_enabled;


DELETE FROM sys_schema_migration
WHERE version = '0014';