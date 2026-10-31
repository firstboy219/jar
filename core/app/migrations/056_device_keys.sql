-- Approvals with the phone's own lock (owner 2026-10-31: "Approval dibikin dari apps saja pakai pin/konfirmasi hp"): the public half of a
-- signing key kept in the phone's Keystore (usable only after its PIN / fingerprint), registered once with the admin password.
CREATE TABLE device_keys (
    device_id   uuid PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    public_key  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_used   timestamptz
);
