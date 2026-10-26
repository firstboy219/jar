-- Blueprint v4 Fase 2 (ADR-043): OpenJarvis as an optional heavy worker next to Hermes-Brain.
-- runtime: who does the task ('hermes' by default; 'openjarvis' for a heavy task while the owner has it on);
-- runtime_note: why it ended up elsewhere (OpenJarvis gave no usable answer → Hermes did it).
ALTER TABLE tasks ADD COLUMN runtime text NOT NULL DEFAULT 'hermes' CHECK (runtime IN ('hermes', 'openjarvis'));
ALTER TABLE tasks ADD COLUMN runtime_note text;
