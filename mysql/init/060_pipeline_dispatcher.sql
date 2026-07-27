ALTER TABLE sys_pipeline_config
    ADD COLUMN autorun_running TINYINT(1)
        NOT NULL DEFAULT 0
        AFTER autorun_enabled,

    ADD COLUMN last_autorun_slot_utc DATETIME(6) NULL
        AFTER starts_at_utc,

    ADD COLUMN last_autorun_status VARCHAR(32)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL DEFAULT 'IDLE'
        AFTER last_autorun_slot_utc,

    ADD COLUMN last_autorun_started_at DATETIME(6) NULL
        AFTER last_autorun_status,

    ADD COLUMN last_autorun_finished_at DATETIME(6) NULL
        AFTER last_autorun_started_at,

    ADD COLUMN last_autorun_message VARCHAR(1000)
        NOT NULL DEFAULT ''
        AFTER last_autorun_finished_at,

    ADD COLUMN current_run_uuid CHAR(36)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER last_autorun_message,

    ADD COLUMN current_run_mode VARCHAR(16)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER current_run_uuid,

    ADD COLUMN current_run_started_at DATETIME(6) NULL
        AFTER current_run_mode,

    ADD COLUMN current_run_heartbeat_at DATETIME(6) NULL
        AFTER current_run_started_at,

    ADD CONSTRAINT ck_sys_pipeline_config_autorun_running
        CHECK (
            autorun_running IN (0, 1)
        ),

    ADD CONSTRAINT ck_sys_pipeline_config_current_run_mode
        CHECK (
            current_run_mode IS NULL
            OR current_run_mode IN (
                'TEST',
                'AUTORUN'
            )
        );


UPDATE legal_entity_certificate certificate

INNER JOIN legal_entity entity
    ON entity.id = certificate.legal_entity_id

SET
    certificate.diskontrol_profile =
        CASE entity.inn
            WHEN '366225317371'
                THEN 'ИП Горбунов'

            WHEN '366205551616'
                THEN 'ИП Крицина'

            WHEN '366607308851'
                THEN 'ИП Горбунова'

            WHEN '366608065023'
                THEN 'ИП Лебедева'
        END,

    certificate.updated_at =
        UTC_TIMESTAMP(6)

WHERE certificate.is_active = 1
  AND entity.inn IN (
      '366225317371',
      '366205551616',
      '366607308851',
      '366608065023'
  );