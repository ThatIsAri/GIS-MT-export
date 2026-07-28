UPDATE sys_auth_job
SET
    status = 'CANCELLED',

    last_error_type =
        'LEGACY_CONTROL_AGENT_REMOVED',

    last_error_message =
        'Задание старого control-agent отменено при удалении устаревшего контура.',

    finished_at =
        COALESCE(
            finished_at,
            UTC_TIMESTAMP(6)
        ),

    updated_at =
        UTC_TIMESTAMP(6)

WHERE status IN (
    'PENDING',
    'WAITING_CERTIFICATE',
    'PROCESSING'
)

  AND requested_by NOT LIKE 'pipeline:%';


ALTER TABLE sys_auth_job
    DROP FOREIGN KEY fk_sys_auth_job_agent,
    DROP INDEX ix_sys_auth_job_agent_status,
    DROP COLUMN claimed_by_agent_id,
    DROP COLUMN claimed_at;


DROP TABLE sys_control_agent_certificate;


DROP TABLE sys_control_agent;