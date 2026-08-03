-- Полная очистка операционных данных проекта GIS МТ.
--
-- Сохраняются:
--   legal_entity;
--   legal_entity_certificate;
--   legal_entity_integration_config;
--   legal_entity_product_group;
--   gis_mt_product_group_dictionary;
--   sys_pipeline_config;
--   sys_pipeline_task_entity;
--   sys_schema_migration.
--
-- Удаляются:
--   каталог документов;
--   RAW/CORE УПД и УКД;
--   хранилище DataMatrix;
--   отклонения;
--   журналы API;
--   история заданий.
--
-- ВНИМАНИЕ:
-- операция необратима без резервной копии.

SET NAMES utf8mb4;
SET SESSION sql_safe_updates = 0;

SELECT
    UTC_TIMESTAMP(6) AS reset_started_at,
    DATABASE() AS database_name;


-- Останавливаем активное состояние конвейера,
-- но сохраняем пользовательскую конфигурацию заданий.
UPDATE sys_pipeline_config
SET
    pipeline_enabled = 0,
    autorun_running = 0,

    current_run_uuid = NULL,
    current_run_mode = NULL,
    current_run_started_at = NULL,
    current_run_heartbeat_at = NULL,

    test_running = 0,

    last_autorun_status = 'IDLE',
    last_autorun_started_at = NULL,
    last_autorun_finished_at = NULL,
    last_autorun_message = '',

    last_test_status = 'IDLE',
    last_test_requested_at = NULL,
    last_test_message = '',

    updated_by = 'operational-reset',
    updated_at = UTC_TIMESTAMP(6)

WHERE id = 1;


SET FOREIGN_KEY_CHECKS = 0;


-- ============================================================
-- Хранилище DataMatrix
-- ============================================================

TRUNCATE TABLE datamatrix_unit;


-- ============================================================
-- Отклонения
-- ============================================================

TRUNCATE TABLE violation_import_reject;
TRUNCATE TABLE gis_mt_violation;
TRUNCATE TABLE violation_export_run;


-- ============================================================
-- Скачанные и обработанные XML УПД/УКД
-- ============================================================

TRUNCATE TABLE upd_download_file;

TRUNCATE TABLE core_document_code;
TRUNCATE TABLE core_document_line;
TRUNCATE TABLE raw_edo_document;

TRUNCATE TABLE legal_entity_document;
TRUNCATE TABLE core_document_observation;
TRUNCATE TABLE core_document_legacy_source;
TRUNCATE TABLE core_document;


-- ============================================================
-- История RabbitMQ-заданий и авторизаций
-- ============================================================

TRUNCATE TABLE sys_sync_job;
TRUNCATE TABLE sys_auth_job;


-- ============================================================
-- RAW-ответы True API и история запусков
-- ============================================================

TRUNCATE TABLE raw_api_response;
TRUNCATE TABLE sys_api_request;
TRUNCATE TABLE sys_sync_run;


SET FOREIGN_KEY_CHECKS = 1;


-- ============================================================
-- Контрольные проверки
-- ============================================================

SELECT
    'datamatrix_unit' AS table_name,
    COUNT(*) AS row_count
FROM datamatrix_unit

UNION ALL

SELECT
    'gis_mt_violation',
    COUNT(*)
FROM gis_mt_violation

UNION ALL

SELECT
    'violation_import_reject',
    COUNT(*)
FROM violation_import_reject

UNION ALL

SELECT
    'violation_export_run',
    COUNT(*)
FROM violation_export_run

UNION ALL

SELECT
    'upd_download_file',
    COUNT(*)
FROM upd_download_file

UNION ALL

SELECT
    'core_document_code',
    COUNT(*)
FROM core_document_code

UNION ALL

SELECT
    'core_document_line',
    COUNT(*)
FROM core_document_line

UNION ALL

SELECT
    'raw_edo_document',
    COUNT(*)
FROM raw_edo_document

UNION ALL

SELECT
    'legal_entity_document',
    COUNT(*)
FROM legal_entity_document

UNION ALL

SELECT
    'core_document_observation',
    COUNT(*)
FROM core_document_observation

UNION ALL

SELECT
    'core_document_legacy_source',
    COUNT(*)
FROM core_document_legacy_source

UNION ALL

SELECT
    'core_document',
    COUNT(*)
FROM core_document

UNION ALL

SELECT
    'sys_sync_job',
    COUNT(*)
FROM sys_sync_job

UNION ALL

SELECT
    'sys_auth_job',
    COUNT(*)
FROM sys_auth_job

UNION ALL

SELECT
    'raw_api_response',
    COUNT(*)
FROM raw_api_response

UNION ALL

SELECT
    'sys_api_request',
    COUNT(*)
FROM sys_api_request

UNION ALL

SELECT
    'sys_sync_run',
    COUNT(*)
FROM sys_sync_run

ORDER BY table_name;


-- Проверяем, что справочники и настройки не удалены.
SELECT
    'legal_entity' AS preserved_table,
    COUNT(*) AS row_count
FROM legal_entity

UNION ALL

SELECT
    'legal_entity_certificate',
    COUNT(*)
FROM legal_entity_certificate

UNION ALL

SELECT
    'legal_entity_product_group',
    COUNT(*)
FROM legal_entity_product_group

UNION ALL

SELECT
    'sys_pipeline_task_entity',
    COUNT(*)
FROM sys_pipeline_task_entity

UNION ALL

SELECT
    'sys_schema_migration',
    COUNT(*)
FROM sys_schema_migration

ORDER BY preserved_table;


SELECT
    pipeline_enabled,
    autorun_enabled,
    autorun_running,
    current_run_uuid,
    test_running,
    updated_by,
    updated_at
FROM sys_pipeline_config
WHERE id = 1;


SELECT
    UTC_TIMESTAMP(6) AS reset_finished_at;