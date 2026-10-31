-- Owner 2026-10-31: "buat saya bisa add dana darurat diluar dari gaji … sehingga saya tahu per hari ini running dana darurat saya total ada
-- brp baik berbentuk cair atau tidak cair tapi bisa dicairkan (emas/saham) atau beku (deposit,dll)". Where his emergency money sits, by how
-- quickly it can be used: likuid (cash, savings, e-wallet), semi-likuid (money-market funds, gold, shares — sold in a few days), tidak likuid
-- (time deposits and the like — locked until they mature or cost a penalty).
CREATE TABLE emergency_assets (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    kind        text NOT NULL DEFAULT 'tabungan',
    liquidity   text NOT NULL CHECK (liquidity IN ('likuid', 'semi_likuid', 'tidak_likuid')),
    amount      numeric NOT NULL CHECK (amount >= 0),
    note        text NOT NULL DEFAULT '',
    updated_at  timestamptz NOT NULL DEFAULT now(),
    created_at  timestamptz NOT NULL DEFAULT now()
);
-- what he typed before as "Dana darurat sekarang" becomes his first asset
INSERT INTO emergency_assets (name, kind, liquidity, amount, note)
SELECT 'Dana darurat (saldo awal)', 'tabungan', 'likuid', (value->>'emergency_saved')::numeric, 'dipindahkan dari pengaturan gaji'
FROM settings_kv WHERE key = 'app:money' AND coalesce((value->>'emergency_saved')::numeric, 0) > 0;
