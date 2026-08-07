-- Отдельное пятое задание конвейера: скачивание корректных продаж.

ALTER TABLE sys_pipeline_config
    ADD COLUMN download_sales_enabled TINYINT(1)
        NOT NULL DEFAULT 0
        AFTER track_violations_enabled,

    ADD COLUMN sales_period_from DATE NULL
        AFTER download_sales_enabled,

    ADD COLUMN sales_period_to DATE NULL
        AFTER sales_period_from;


ALTER TABLE sys_sync_job
    DROP CHECK ck_sys_sync_job_type,

    ADD CONSTRAINT ck_sys_sync_job_type
        CHECK (
            job_type IN (
                'SYNC_LEGAL_ENTITY',
                'EXPORT_UPD',
                'PROCESS_UPD',
                'TRACK_VIOLATIONS',
                'DOWNLOAD_SALES'
            )
        );
