-- Meeting context (ADR-032): who is in the room and what it is about, typed in the app before recording.
-- Used for the speech recogniser's vocabulary (names, projects), the minutes' prompt and action-item owners.
ALTER TABLE meetings ADD COLUMN context jsonb NOT NULL DEFAULT '{}';  -- {"participants": ["Bu Rina", ...], "agenda": "..."}
