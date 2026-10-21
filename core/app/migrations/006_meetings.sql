-- Meeting recorder (APK records the room microphone in 60 s chunks; jarvis-core assembles,
-- transcribes, separates speakers and writes the minutes).
CREATE TABLE meetings (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title        text NOT NULL,
    status       text NOT NULL DEFAULT 'recording'
                 CHECK (status IN ('recording', 'queued', 'transcribing', 'summarizing', 'done', 'failed')),
    confidential boolean NOT NULL DEFAULT false,  -- "Rahasia": local models only, end to end
    consent      boolean NOT NULL,                -- the owner confirmed participants agreed to the recording
    device_id    uuid REFERENCES devices(id) ON DELETE SET NULL,
    chunks       int NOT NULL DEFAULT 0,
    duration_s   real,
    marks        jsonb NOT NULL DEFAULT '[]',     -- [{"t": seconds, "note": "..."}] "Tandai penting"
    engine       text,                            -- speech engine used
    transcript   jsonb,                           -- [{"start","end","speaker","text"}]
    speakers     jsonb,                           -- {"0": "Pemilik", "1": "Pembicara 2"}
    summary      jsonb,                           -- {"ringkasan", "keputusan", "action_items", "pertanyaan", "topik"}
    document_id  uuid REFERENCES documents(id) ON DELETE SET NULL,
    error        text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    done_at      timestamptz,
    audio_purged boolean NOT NULL DEFAULT false
);
CREATE INDEX meetings_started_idx ON meetings (started_at DESC);

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_kind_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_kind_check CHECK (kind IN ('owner', 'situation', 'routine', 'selfcheck', 'meeting'));
