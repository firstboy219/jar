-- Owner 2026-10-31: "Tambahkan fitur di transaksi untuk menandakan mana yang sudah direalisasi dan mana yg belum". A transaction not yet
-- realised (a bill to pay, a planned purchase) is kept apart: it counts in no spending, pot or budget until he marks it done.
ALTER TABLE money_tx ADD COLUMN realized boolean NOT NULL DEFAULT true;
CREATE INDEX money_tx_pending ON money_tx (at) WHERE NOT realized;
