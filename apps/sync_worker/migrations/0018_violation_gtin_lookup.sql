ALTER TABLE datamatrix_unit
    ADD KEY ix_datamatrix_unit_gtin_date (
        gtin,
        source_document_date,
        id
    );


ALTER TABLE gis_mt_violation
    ADD KEY ix_gis_mt_violation_kind (
        violation_kind(191)
    );


UPDATE gis_mt_violation AS violation
JOIN datamatrix_unit AS unit
  ON unit.code_sha256 = violation.code_sha256
   SET violation.datamatrix_unit_id = unit.id
 WHERE violation.datamatrix_unit_id IS NULL
   AND violation.code_sha256 IS NOT NULL;