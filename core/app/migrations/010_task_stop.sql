-- "Netralkan" (ADR-029): the owner can stop everything to free CPU and memory. Stopped work is kept with
-- what it had done so far, so the owner can retry it (it continues with that context) or close it.
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'stopped'));
ALTER TABLE tasks ADD COLUMN progress text;
