DELETE FROM sys_schema_migration
WHERE version = '0021'
  AND status IN (
      'FAILED',
      'APPLYING'
  );