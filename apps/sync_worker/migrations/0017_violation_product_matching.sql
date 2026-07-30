ALTER TABLE datamatrix_unit
    ADD COLUMN gtin CHAR(14)
        CHARACTER SET ascii
        COLLATE ascii_bin
        NULL
        AFTER product_code,

    ADD KEY ix_datamatrix_unit_entity_gtin_date (
        legal_entity_id,
        gtin,
        source_document_date
    );


UPDATE datamatrix_unit
   SET gtin =
       CASE
           WHEN LOWER(LEFT(code_text, 3)) = ']d2'
            AND SUBSTRING(code_text, 4, 2) = '01'
            AND SUBSTRING(code_text, 6, 14)
                REGEXP '^[0-9]{14}$'
               THEN SUBSTRING(code_text, 6, 14)

           WHEN LEFT(code_text, 4) = '(01)'
            AND SUBSTRING(code_text, 5, 14)
                REGEXP '^[0-9]{14}$'
               THEN SUBSTRING(code_text, 5, 14)

           WHEN LEFT(code_text, 2) = '01'
            AND SUBSTRING(code_text, 3, 14)
                REGEXP '^[0-9]{14}$'
               THEN SUBSTRING(code_text, 3, 14)

           WHEN LEFT(code_text, 14)
                REGEXP '^[0-9]{14}$'
               THEN LEFT(code_text, 14)

           ELSE NULL
       END
 WHERE gtin IS NULL;


UPDATE gis_mt_violation
   SET gtin =
       CASE
           WHEN LOWER(LEFT(code_text, 3)) = ']d2'
            AND SUBSTRING(code_text, 4, 2) = '01'
            AND SUBSTRING(code_text, 6, 14)
                REGEXP '^[0-9]{14}$'
               THEN SUBSTRING(code_text, 6, 14)

           WHEN LEFT(code_text, 4) = '(01)'
            AND SUBSTRING(code_text, 5, 14)
                REGEXP '^[0-9]{14}$'
               THEN SUBSTRING(code_text, 5, 14)

           WHEN LEFT(code_text, 2) = '01'
            AND SUBSTRING(code_text, 3, 14)
                REGEXP '^[0-9]{14}$'
               THEN SUBSTRING(code_text, 3, 14)

           WHEN LEFT(code_text, 14)
                REGEXP '^[0-9]{14}$'
               THEN LEFT(code_text, 14)

           ELSE gtin
       END
 WHERE (
           gtin IS NULL
           OR TRIM(gtin) = ''
       )
   AND code_text IS NOT NULL
   AND TRIM(code_text) <> '';
