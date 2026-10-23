-- JARVIS' own skills, workers and tools rank above the hundred third-party skills that came with Hermes.
ALTER TABLE capabilities ADD COLUMN own boolean NOT NULL DEFAULT false;
