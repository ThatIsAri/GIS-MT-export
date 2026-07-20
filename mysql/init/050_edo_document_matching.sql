ALTER TABLE raw_edo_document
    ADD COLUMN edo_document_number VARCHAR(255) NULL
        AFTER external_document_id,

    ADD COLUMN edo_document_date DATE NULL
        AFTER edo_document_number,

    ADD COLUMN seller_inn VARCHAR(16) NULL
        AFTER edo_document_date,

    ADD COLUMN buyer_inn VARCHAR(16) NULL
        AFTER seller_inn,

    ADD COLUMN total_amount DECIMAL(30, 2) NULL
        AFTER buyer_inn,

    ADD COLUMN match_status VARCHAR(32)
        NOT NULL
        DEFAULT 'NOT_PROCESSED'
        AFTER core_document_id,

    ADD COLUMN match_method VARCHAR(64) NULL
        AFTER match_status,

    ADD COLUMN match_score TINYINT UNSIGNED NULL
        AFTER match_method,

    ADD COLUMN match_candidate_count INT UNSIGNED
        NOT NULL
        DEFAULT 0
        AFTER match_score,

    ADD COLUMN match_candidates_json JSON NULL
        AFTER match_candidate_count,

    ADD COLUMN matched_at DATETIME(3) NULL
        AFTER match_candidates_json,

    ADD KEY ix_raw_edo_document_invoice (
        edo_document_number,
        edo_document_date
    ),

    ADD KEY ix_raw_edo_document_parties (
        seller_inn,
        buyer_inn
    ),

    ADD KEY ix_raw_edo_document_match_status (
        match_status
    );