CREATE TABLE core_document_observation (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    core_document_id BIGINT UNSIGNED NOT NULL,

    legal_entity_id BIGINT UNSIGNED NOT NULL,

    product_group VARCHAR(64)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NOT NULL,

    sync_run_id BIGINT UNSIGNED NOT NULL,

    raw_response_id BIGINT UNSIGNED NOT NULL,

    observed_at DATETIME(6) NOT NULL,

    created_at DATETIME(6)
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_core_document_observation_raw_response (
        raw_response_id
    ),

    KEY ix_core_document_observation_run_core (
        sync_run_id,
        core_document_id
    ),

    KEY ix_core_document_observation_entity_group_seen (
        legal_entity_id,
        product_group,
        observed_at
    ),

    KEY ix_core_document_observation_core_seen (
        core_document_id,
        observed_at
    ),

    CONSTRAINT fk_core_document_observation_core
        FOREIGN KEY (core_document_id)
        REFERENCES core_document (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_core_document_observation_entity
        FOREIGN KEY (legal_entity_id)
        REFERENCES legal_entity (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_core_document_observation_group
        FOREIGN KEY (
            legal_entity_id,
            product_group
        )
        REFERENCES legal_entity_product_group (
            legal_entity_id,
            product_group
        )
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_core_document_observation_run
        FOREIGN KEY (sync_run_id)
        REFERENCES sys_sync_run (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT,

    CONSTRAINT fk_core_document_observation_raw
        FOREIGN KEY (raw_response_id)
        REFERENCES raw_api_response (id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci;


INSERT INTO core_document_observation (
    core_document_id,
    legal_entity_id,
    product_group,
    sync_run_id,
    raw_response_id,
    observed_at,
    created_at
)
SELECT
    cd.id,
    run.legal_entity_id,
    run.product_group,
    run.id,
    raw.id,
    raw.received_at,
    UTC_TIMESTAMP(6)

FROM raw_api_response raw

JOIN sys_sync_run run
  ON run.id = raw.sync_run_id

JOIN core_document cd
  ON cd.external_document_id =
     raw.external_entity_id

JOIN legal_entity_product_group pg
  ON pg.legal_entity_id =
     run.legal_entity_id
 AND pg.product_group =
     run.product_group

WHERE run.job_type =
      'SYNC_DOCUMENT_DETAILS'

  AND run.legal_entity_id IS NOT NULL

  AND run.product_group IS NOT NULL

  AND raw.processing_status =
      'PROCESSED'

  AND raw.external_entity_id
      IS NOT NULL

  AND raw.endpoint LIKE
      '%/doc/%/info'

ON DUPLICATE KEY UPDATE
    raw_response_id =
        VALUES(
            raw_response_id
        );