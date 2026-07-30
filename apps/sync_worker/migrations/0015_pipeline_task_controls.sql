ALTER TABLE sys_pipeline_config
    ADD COLUMN track_violations_enabled TINYINT(1)
        NOT NULL DEFAULT 0
        AFTER process_upd_enabled;


UPDATE legal_entity_product_group
   SET violations_enabled = 0,
       violations_last_sync_status =
           CASE
               WHEN violations_last_sync_status = 'ERROR'
               THEN violations_last_sync_status
               ELSE 'NEVER'
           END,
       updated_at = UTC_TIMESTAMP(6);
