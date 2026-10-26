-- Blueprint v4 Fase 12 (ADR-060): the owner's notes & task list (in place of the app's Chat tab). A page is a list of blocks (paragraph,
-- headings, bullets, numbers, to-dos, quote, code, callout, divider); a to-do block IS a task (checked, due date, priority, who), so the
-- task views are a query over every page. Meeting minutes become a page of their own, their action items its to-dos.
CREATE TABLE note_pages (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id   uuid REFERENCES note_pages(id) ON DELETE CASCADE,
    title       text NOT NULL DEFAULT '',
    icon        text NOT NULL DEFAULT '',
    kind        text NOT NULL DEFAULT 'page' CHECK (kind IN ('page', 'inbox', 'tasks', 'meeting')),
    meeting_id  uuid REFERENCES meetings(id) ON DELETE SET NULL,
    blocks      jsonb NOT NULL DEFAULT '[]',
    pinned      boolean NOT NULL DEFAULT false,
    archived    boolean NOT NULL DEFAULT false,
    version     int NOT NULL DEFAULT 1,          -- every save bumps it: a stale editor (another device) gets 409, not a silent overwrite
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX note_pages_recent ON note_pages (updated_at DESC) WHERE NOT archived;
CREATE UNIQUE INDEX note_pages_meeting ON note_pages (meeting_id) WHERE meeting_id IS NOT NULL;
CREATE UNIQUE INDEX note_pages_one_inbox ON note_pages (kind) WHERE kind IN ('inbox', 'tasks');
