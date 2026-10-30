-- ADR-087 phase J: spending read from a photo of a receipt (camera or gallery).
ALTER TABLE money_tx DROP CONSTRAINT IF EXISTS money_tx_source_check;
ALTER TABLE money_tx ADD CONSTRAINT money_tx_source_check CHECK (source IN ('notif', 'manual', 'jarvis', 'email', 'struk'));
