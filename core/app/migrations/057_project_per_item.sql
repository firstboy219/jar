-- Owner 2026-10-31: "Buat apply job yg khusus eksekusi apply menggunakan buka app jobstreet nya langsung … setelah worker search list jalan
-- nextnya yg jalan adalah worker yg buka app jobstreet dan langsung melakukan apply job". A phone-app role that runs once PER ITEM the
-- previous stage found (one JobStreet application per job, one after another).
ALTER TABLE project_roles ADD COLUMN per_item boolean NOT NULL DEFAULT false;
