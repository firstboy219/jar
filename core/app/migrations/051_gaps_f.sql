-- ADR-087 gap batch F: spending read from email receipts too.
ALTER TABLE money_tx DROP CONSTRAINT IF EXISTS money_tx_source_check;
ALTER TABLE money_tx ADD CONSTRAINT money_tx_source_check CHECK (source IN ('notif', 'manual', 'jarvis', 'email'));
