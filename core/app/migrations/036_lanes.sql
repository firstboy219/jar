-- Blueprint v4 Fase 12 (ADR-081): a third lane for simple look-ups — "ringan" (search + a small cheap model, no Hermes session, no worker slot).
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_runtime_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_runtime_check CHECK (runtime IN ('hermes', 'openjarvis', 'ringan'));
