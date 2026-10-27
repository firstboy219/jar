-- ADR-065: a dev team job that can only be done by a human developer (it needs the protected zone) stops as such, instead of looping.
ALTER TABLE dev_jobs DROP CONSTRAINT IF EXISTS dev_jobs_status_check;
ALTER TABLE dev_jobs ADD CONSTRAINT dev_jobs_status_check
    CHECK (status IN ('analysing', 'coding', 'testing', 'reviewing', 'awaiting_owner', 'done', 'failed', 'cancelled', 'needs_human'));
