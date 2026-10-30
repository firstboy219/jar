-- ADR-087 wave 9 gaps: a snoozed message comes back at its time; an interview gets its preparation notes.
ALTER TABLE inbox_items ADD COLUMN snoozed_until timestamptz;
CREATE INDEX inbox_items_snoozed ON inbox_items (snoozed_until) WHERE status = 'snoozed';
