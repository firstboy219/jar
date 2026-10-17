# JARVIS Personal AI Assistant

## Knowledge Base, Product Requirements & Development Handoff untuk Claude Code

**Dokumen:** `JARVIS_KNOWLEDGE_BASE.md`\
**Tujuan:** Menjadi sumber konteks utama bagi Claude Code untuk
merancang dan mengembangkan backend serta APK Android Jarvis.\
**Bahasa produk:** Bahasa Indonesia sebagai default, dengan dukungan
bahasa Inggris.\
**Status:** Product vision dan requirements awal. Keputusan teknis
tertentu masih perlu divalidasi berdasarkan repository, server, dan
perangkat yang tersedia.

------------------------------------------------------------------------

# 1. Ringkasan Produk

Jarvis adalah personal AI assistant yang proaktif, interaktif, memiliki
konteks jangka panjang, mampu mengusulkan dan menjalankan tugas dengan
izin yang sesuai, serta meningkatkan kualitas bantuannya dari data dan
feedback yang dimiliki.

Jarvis **bukan sekadar chatbot yang menunggu prompt**. Sistem harus
dapat menjalankan pemeriksaan terjadwal, memantau sumber data yang
diizinkan, menemukan hal yang relevan, membuat rekomendasi, dan mengirim
notifikasi atau meminta persetujuan pengguna.

Pengguna ingin mengembangkan **APK Android** dan berencana menggunakan
**Claude Code** untuk membantu mengembangkan backend sekaligus aplikasi
Android.

## Prinsip produk

1.  **Proaktif, bukan mengganggu:** mencari hal yang relevan dan
    mengusulkan tindakan, tetapi menghindari notifikasi berlebihan.
2.  **Context-aware:** menggunakan konteks, tujuan, proyek, preferensi,
    dokumen, serta riwayat yang memang diizinkan untuk diakses.
3.  **Human-in-the-loop:** tindakan berisiko atau tindakan eksternal
    memerlukan persetujuan kecuali telah diotorisasi secara eksplisit
    melalui kebijakan terbatas.
4.  **Belajar dengan aman:** memperbaiki memory, knowledge base, skills,
    dan rekomendasi berdasarkan feedback. Jangan menganggap setiap
    informasi baru otomatis benar.
5.  **Model-agnostic:** jangan mengikat keseluruhan sistem ke satu model
    AI atau provider.
6.  **Modular:** gunakan layanan yang sudah ada dan komponen yang tepat
    guna; jangan membangun ulang infrastruktur yang telah tersedia.
7.  **Private by design:** pengguna mengontrol data, izin, koneksi,
    retensi, dan penghapusan.
8.  **Auditability:** tindakan agent harus bisa ditelusuri, dijelaskan,
    dan dihentikan.

------------------------------------------------------------------------

# 2. Konteks Pengguna dan Use Cases Prioritas

Jarvis diharapkan mendukung beberapa domain sekaligus dengan konteks dan
izin yang terpisah.

## 2.1 Work / IT Business Analyst

Kebutuhan: - Membantu analisis proses bisnis, BRD/FSD, UAT,
requirements, risiko, action items, dan status proyek. - Menyusun draft
email, meeting minutes, ringkasan, laporan, dan daftar tindak lanjut. -
Membantu troubleshooting teknis, analisis log, SQL, API, repository, dan
deployment. - Membantu mengorganisasi pekerjaan dan menemukan item yang
berpotensi terlupakan. - Memberikan rekomendasi berdasarkan dokumen dan
konteks yang telah diizinkan.

**Batasan penting:** dokumen, source code, kredensial, atau data
perusahaan tidak boleh otomatis disalin ke layanan AI pribadi/cloud.
Integrasi ke sistem perusahaan harus mengikuti kebijakan perusahaan dan
memerlukan otorisasi yang sesuai. Pisahkan workspace personal dan
corporate.

## 2.2 Business / E-commerce Assistant

Kebutuhan: - Membantu workflow bisnis online dan proyek Autotoko. -
Menganalisis data tren, ide produk, kompetisi, margin, konten, serta
hasil penjualan jika sumber datanya tersedia. - Menyiapkan rekomendasi
dan laporan terjadwal. - Membantu workflow melalui API dan automation
yang sudah tersedia.

## 2.3 Technical / Infrastructure Assistant

Kebutuhan: - Membantu memeriksa server, service, log, dan health
checks. - Membantu diagnosis masalah serta menyiapkan langkah
pemulihan. - Membuat usulan perubahan kode/configuration dan rencana
deployment. - Default akses awal adalah read-only atau sandbox. Perintah
destruktif, perubahan production, penghapusan data, dan tindakan yang
berpotensi memutus layanan memerlukan persetujuan.

## 2.4 Personal / Finance Assistant

Kebutuhan: - Mengorganisasi tujuan, tugas, agenda, dan catatan
personal. - Membantu analisis anggaran, cicilan, portofolio, dan
informasi pasar apabila sumber data dihubungkan. - Memberikan ringkasan,
peringatan, dan analisis risiko.

**Batasan:** jangan mengeksekusi transaksi keuangan/trading secara
otomatis pada MVP. Informasi finansial harus diperlakukan sensitif;
akses harus opt-in dan dibatasi.

------------------------------------------------------------------------

# 3. Pengalaman Pengguna yang Diinginkan

## 3.1 Contoh perilaku proaktif

### Daily briefing

Jarvis mengirim briefing sesuai jadwal yang dapat diatur, berisi
prioritas, temuan, pengingat, dan rekomendasi yang relevan.

### Follow-up proyek

Jika ada data tugas atau tenggat yang tersedia, Jarvis dapat mendeteksi
tindak lanjut yang berisiko terlewat, menjelaskan sumber konteksnya,
lalu menawarkan draft atau task. Jangan mengirim email atau mengubah
sistem eksternal tanpa izin yang sesuai.

### Monitoring teknis

Jarvis dapat menjalankan health check read-only yang diizinkan,
mengonfirmasi anomali melalui pemeriksaan kedua jika sesuai, lalu
memberi notifikasi beserta bukti dan rekomendasi.

### Business insight

Jarvis menganalisis data bisnis yang terhubung, menemukan perubahan atau
peluang, menyampaikan asumsi dan sumber, lalu menawarkan analisis
lanjutan.

### Learning from feedback

Pengguna dapat menyetujui, menolak, mengedit, atau memberi feedback
terhadap rekomendasi. Sistem menyimpan preferensi yang relevan dan
memperbaiki rekomendasi berikutnya tanpa melakukan retraining model
otomatis.

## 3.2 Prinsip interaksi

-   Pengguna dapat berinteraksi melalui teks terlebih dahulu; voice
    dapat dikembangkan sebagai fitur.
-   Push notification digunakan untuk hal penting dan tindakan yang
    memerlukan perhatian.
-   Setiap rekomendasi penting harus menyertakan alasan, sumber konteks,
    waktu data, tingkat keyakinan bila tersedia, serta tindakan
    berikutnya.
-   Jarvis harus dapat mengatakan "saya belum tahu" atau meminta
    klarifikasi jika konteks tidak cukup.
-   Hindari membuat klaim bahwa Jarvis telah melakukan tindakan jika
    hanya menyiapkan draft atau rekomendasi.
-   Sediakan kontrol quiet hours, frekuensi notifikasi, kategori
    notifikasi, dan pause/resume proactive monitoring.

------------------------------------------------------------------------

# 4. Otonomi dan Persetujuan

Gunakan tiga tingkat otonomi berikut.

## Level 1 --- Observe

Boleh mengumpulkan data yang diizinkan, memeriksa status, mengindeks
dokumen yang diizinkan, dan menganalisis informasi tanpa mengubah sistem
eksternal.

## Level 2 --- Propose

Boleh menyiapkan draft email, task, laporan, rekomendasi, command plan,
atau perubahan kode. Pengguna meninjau sebelum tindakan eksternal
dilakukan.

## Level 3 --- Execute

Boleh menjalankan tindakan tertentu yang sudah masuk allowlist, dengan
scope, jadwal, dan batas risiko yang jelas. Tidak berarti agent memiliki
akses tanpa batas.

**Default MVP:** Level 1 dan Level 2. Level 3 hanya untuk tindakan
berisiko rendah yang secara eksplisit diaktifkan, seperti membuat
laporan atau menjalankan health check read-only.

Wajib ada: - Approval Center. - Daftar tindakan yang diizinkan dan
dilarang. - Konfirmasi untuk tindakan eksternal, destruktif, finansial,
atau production. - Audit log untuk proposal, approval, eksekusi, hasil,
dan error. - Idempotency untuk mencegah tindakan duplikat. - Timeout,
retry limit, rate limit, dan emergency stop. - Pemisahan antara
"drafted", "awaiting approval", "approved", "executing", "completed",
"failed", dan "cancelled".

------------------------------------------------------------------------

# 5. Arsitektur Target

Arsitektur berikut adalah rancangan awal; Claude Code harus memeriksa
repository, server, dan runtime yang sudah tersedia sebelum menentukan
implementasi final.

``` text
Android APK (Flutter)
  ├── Chat / voice UI
  ├── Dashboard & initiative feed
  ├── Memory / knowledge browser
  ├── Task & approval center
  └── Settings, privacy, notification controls
             |
             | HTTPS + authentication
             v
Jarvis Backend API
  ├── Authentication / authorization
  ├── User profile & preferences
  ├── Context collector / source connectors
  ├── Context engine & initiative engine
  ├── Agent orchestration / tool gateway
  ├── Memory & knowledge service
  ├── Task scheduler / event handling
  ├── Approval & policy engine
  ├── Notification service
  └── Audit / observability
       |          |            |
       v          v            v
 PostgreSQL    AI Providers   Existing n8n
 + vector      (local/cloud)  (MUST REUSE)
 search
       |
       v
 Files / documents / connected sources
```

## 5.1 Android application

Rekomendasi awal: Flutter untuk APK Android, kecuali pemeriksaan project
menunjukkan alasan kuat menggunakan stack lain.

Aplikasi harus menjadi interface, bukan satu-satunya tempat proses
proaktif berjalan. Proactive jobs harus tetap berjalan saat aplikasi
ditutup atau HP offline, melalui backend/server dan scheduler.

## 5.2 Backend

Backend bertanggung jawab atas autentikasi, penyimpanan, context
processing, orchestration, policy checks, approval, audit, dan API untuk
aplikasi.

Gunakan struktur modular dan batas domain yang jelas. Jangan membangun
microservices berlebihan pada MVP; satu modular backend dapat lebih
mudah dirawat.

## 5.3 Existing n8n --- HARD CONSTRAINT

**n8n SUDAH TERPASANG pada server existing pengguna. JANGAN membuat,
menginstal, atau men-deploy instance n8n baru.**

Claude Code wajib: 1. Memeriksa konfigurasi/informasi koneksi n8n
existing yang tersedia dan telah diizinkan. 2. Menggunakan n8n existing
melalui API/webhook/credential yang disediakan. 3. Tidak mengasumsikan
URL, port, credential, atau workflow ID. 4. Tidak mencetak secrets atau
token ke log/repository. 5. Tidak mengubah workflow existing tanpa
persetujuan pengguna. 6. Jika akses belum tersedia, membuat integration
interface/config placeholder dan meminta detail yang diperlukan; jangan
membuat n8n baru. 7. Tidak melakukan perubahan server yang tidak diminta
atau berisiko tanpa konfirmasi.

Jarvis backend boleh mengatur atau memanggil workflow melalui integrasi
n8n existing. Hindari membuat scheduler duplikat untuk pekerjaan yang
sudah dikelola n8n tanpa alasan jelas. Tentukan pembagian tanggung jawab
antara scheduler backend dan n8n secara eksplisit.

## 5.4 Agent runtime

Hermes Agent dan OpenClaw adalah kandidat yang perlu dievaluasi. Jangan
langsung menginstal atau menjalankan keduanya secara bersamaan.

Pilihan awal untuk diuji adalah **Hermes Agent**, karena kebutuhan utama
mencakup memory, skills, scheduled work, dan improvement dari
pengalaman. OpenClaw tetap menjadi alternatif jika lebih cocok untuk
chat gateway, channels, dan integrasi yang dibutuhkan.

Sebelum integrasi: - Periksa versi dan dokumentasi terbaru. - Validasi
cara memanggil agent dari backend, authentication, tool permissions,
session handling, concurrency, serta output format. - Hindari menjadikan
agent runtime sebagai satu-satunya database atau sumber kebenaran. -
Simpan user memory, approvals, tasks, dan audit di storage yang dikuasai
Jarvis. - Jangan menjalankan kedua runtime kecuali ada use case konkret
dan pembagian tanggung jawab yang jelas.

## 5.5 AI model strategy

Gunakan provider abstraction agar model dapat diganti tanpa mengubah
business logic.

Model kandidat untuk pengujian: - Qwen: kandidat model lokal
serbaguna. - DeepSeek: kandidat reasoning/technical tasks. - Gemma:
alternatif model lokal. - gpt-oss: alternatif open-weight. - Model
cloud: untuk tugas yang membutuhkan kualitas atau kemampuan lebih
tinggi.

Tidak ada model yang ditetapkan sebagai pemenang final sebelum benchmark
pada hardware dan use case nyata. Periksa ukuran model, quantization,
RAM/VRAM, bahasa Indonesia, latency, context window, structured output,
dan tool calling.

Implementasikan task routing secara bertahap: - Model lokal kecil untuk
klasifikasi atau ekstraksi jika kualitas memadai. - Model lebih kuat
untuk analisis kompleks. - Rules/scripts untuk pemeriksaan deterministik
yang tidak membutuhkan LLM.

Jangan mengunduh atau menjalankan semua model sekaligus. Jangan
mengasumsikan model lokal berjalan pada server pengguna sebelum
memeriksa spesifikasi perangkat.

------------------------------------------------------------------------

# 6. Memory, Knowledge Base, dan Learning Loop

Jarvis harus memiliki sistem memori yang terstruktur dan bisa dikontrol
pengguna.

## 6.1 Kategori memory

1.  **Personal memory:** preferensi, tujuan, kebiasaan interaksi, dan
    batasan yang dinyatakan pengguna.
2.  **Project memory:** proyek, status, keputusan, kendala, dependensi,
    deadline, dan action items.
3.  **Knowledge memory:** dokumen, catatan, panduan, dan hasil riset.
4.  **Experience memory:** rekomendasi yang pernah diberikan, keputusan
    pengguna, hasil tindakan, dan feedback.
5.  **Operational memory:** status tugas, jadwal, event, dan ringkasan
    eksekusi yang diperlukan.

## 6.2 RAG / document retrieval

-   Indeks hanya sumber yang diizinkan.
-   Simpan metadata seperti source ID, source type, owner,
    created/updated timestamp, version, access scope, dan chunk
    reference.
-   Jawaban yang berdasarkan dokumen harus dapat menampilkan
    sumber/citation internal jika memungkinkan.
-   Hormati hak akses sumber saat retrieval.
-   Sediakan re-index, update, dan deletion; data yang dihapus harus
    dihapus dari indeks terkait.
-   Jangan menganggap isi dokumen selalu benar atau mutakhir.
-   Hindari menyimpan kredensial, token, password, atau secret di vector
    store.

## 6.3 Learning loop

Alur yang disarankan:

``` text
New data / completed task / user feedback
       -> extract candidate facts or skill improvement
       -> validate source, freshness, and confidence
       -> detect conflicts with existing memory
       -> apply policy and sensitivity checks
       -> save as candidate or approved memory
       -> evaluate future usefulness
       -> update recommendation/skill where appropriate
```

Pada MVP, "learning" berarti: - memperbarui memori terstruktur; -
mengindeks knowledge; - menyimpan feedback; - meningkatkan
prompt/skills/rules melalui perubahan yang dapat ditinjau; -
mengevaluasi kualitas rekomendasi.

**Jangan melakukan fine-tuning atau mengubah system prompt/permissions
secara otomatis tanpa kontrol.** Perubahan skills dan instruksi yang
berdampak harus versioned, diuji, dan dapat di-rollback.

## 6.4 Memory controls

Pengguna harus dapat: - melihat apa yang Jarvis ingat; - mengedit atau
menghapus memory; - menandai memory sebagai salah/usang; - menghapus
sumber dan memicu penghapusan turunan dari index; - mematikan kategori
memory; - melihat sumber dan waktu informasi disimpan; - membedakan
fakta, asumsi, dan preferensi.

------------------------------------------------------------------------

# 7. Proactive Intelligence Engine

Ini adalah kemampuan pembeda utama Jarvis.

## 7.1 Pipeline

1.  **Collect:** menerima event atau membaca sumber yang telah
    diizinkan.
2.  **Normalize:** menyamakan format data dan metadata.
3.  **Detect:** mencari perubahan, deadline, anomali, pola, dan peluang.
4.  **Prioritize:** memberi skor relevansi, urgensi, dampak, confidence,
    dan biaya.
5.  **Reason:** memanggil model AI hanya jika diperlukan.
6.  **Propose:** menghasilkan rekomendasi dan tindakan berikutnya.
7.  **Policy check:** memastikan tindakan sesuai permission dan autonomy
    level.
8.  **Notify:** mengirim notifikasi berdasarkan urgency dan quiet hours.
9.  **Approve/execute:** menunggu approval atau menjalankan tindakan
    allowlisted.
10. **Learn:** mencatat hasil dan feedback.

## 7.2 Event types

Contoh event: - `deadline_approaching` - `task_overdue` -
`new_document_available` - `project_status_changed` -
`server_health_anomaly` - `business_metric_changed` - `market_alert` -
`scheduled_briefing_due` - `user_feedback_received`

Gunakan event-driven checks jika sumber mendukungnya. Untuk sumber tanpa
event, gunakan polling dengan interval yang dapat dikonfigurasi dan rate
limit.

## 7.3 Prioritization

Buat scoring yang transparan dan dapat dikonfigurasi, misalnya
berdasarkan: - urgency; - potential impact; - relevance to user goals; -
confidence/source quality; - freshness; - estimated cost; - interruption
cost.

Tidak perlu langsung memakai algoritma kompleks. Mulai dari rules dan
weights yang mudah dijelaskan, kemudian evaluasi dengan feedback.

## 7.4 Notification quality

-   Gabungkan temuan serupa agar tidak spam.
-   Deduplikasi berdasarkan event/source/time window.
-   Hormati quiet hours dan notification preferences.
-   Sediakan snooze, dismiss, mute category, dan mark as useful/not
    useful.
-   Jangan mengirim informasi sensitif pada lock-screen notification
    secara default.
-   Bedakan critical alert dengan rekomendasi non-urgent.

------------------------------------------------------------------------

# 8. APK Requirements

## 8.1 Menu / screens

1.  **Home / Dashboard**
    -   Daily briefing.
    -   Prioritas.
    -   Initiative feed.
    -   Task yang sedang berjalan.
    -   Alert penting.
2.  **Chat & Voice**
    -   Chat teks sebagai MVP.
    -   Voice input/output sebagai fitur berikutnya.
    -   Menampilkan status agent: thinking, gathering context, awaiting
        approval, executing, completed, failed.
3.  **Initiatives**
    -   Rekomendasi yang dimulai oleh Jarvis.
    -   Alasan, sumber, confidence, dampak, dan tindakan yang diusulkan.
    -   Mark useful/not useful, dismiss, snooze.
4.  **Tasks**
    -   Daftar tugas, status, deadline, hasil, error, retry, cancel.
5.  **Approval Center**
    -   Tindakan yang menunggu persetujuan.
    -   Detail tindakan, target, dampak, permission yang diminta, dan
        expiry.
    -   Approve / reject / request changes.
    -   Konfirmasi tambahan untuk tindakan high-risk.
6.  **Memory & Knowledge**
    -   Pencarian memory.
    -   Detail sumber, tanggal, confidence, dan scope.
    -   Edit/delete/mark stale.
    -   Status indexing dokumen.
7.  **Skills & Automations**
    -   Skills yang tersedia.
    -   Workflow yang terhubung.
    -   Jadwal, status, hasil terakhir, dan tombol pause/resume.
    -   Tampilkan jelas bahwa workflow tertentu berjalan melalui n8n
        existing.
8.  **Settings & Privacy**
    -   Model/provider.
    -   Notification frequency dan quiet hours.
    -   Autonomy level.
    -   Connected sources dan izin.
    -   Memory controls, data export/deletion, emergency stop.
    -   Usage/cost limits jika memakai API berbayar.

## 8.2 UX principles

-   Interface bersih, modern, mudah dipakai sehari-hari.
-   Dark mode boleh menjadi default, tetapi tidak mengorbankan
    aksesibilitas.
-   Bahasa Indonesia sebagai default.
-   Hindari dashboard yang penuh metrik tanpa tindakan yang jelas.
-   Setiap kartu rekomendasi menjawab: apa yang ditemukan, mengapa
    penting, sumbernya, dan apa yang dapat dilakukan.
-   Sediakan loading/error/offline state yang jelas.
-   Jangan menampilkan "AI telah melakukan X" kecuali backend telah
    mengonfirmasi hasilnya.

## 8.3 Android background behavior

APK tidak boleh menjadi satu-satunya scheduler karena Android membatasi
background execution. Tugas proaktif harus dijalankan backend/server;
aplikasi menerima push notification dan melakukan sync saat dibuka.
Fitur lokal seperti voice atau local notifications dapat ditambahkan
sesuai kebutuhan.

------------------------------------------------------------------------

# 9. API dan Domain Model Awal

Claude Code harus menyempurnakan desain setelah inspeksi repository.
Contoh berikut adalah domain minimum, bukan kewajiban memakai endpoint
persis sama.

## 9.1 Resource/domain

-   `users`
-   `user_preferences`
-   `connected_sources`
-   `memories`
-   `documents`
-   `document_chunks`
-   `projects`
-   `goals`
-   `tasks`
-   `initiatives`
-   `approvals`
-   `agent_runs`
-   `tool_executions`
-   `feedback`
-   `skills`
-   `automation_workflows`
-   `notification_preferences`
-   `audit_events`
-   `model_provider_configs` (tanpa menyimpan secret plaintext)

## 9.2 API examples

-   `POST /api/v1/chat`
-   `GET /api/v1/briefing`
-   `GET /api/v1/initiatives`
-   `POST /api/v1/initiatives/{id}/feedback`
-   `GET /api/v1/tasks`
-   `POST /api/v1/tasks`
-   `POST /api/v1/approvals/{id}/approve`
-   `POST /api/v1/approvals/{id}/reject`
-   `GET /api/v1/memories`
-   `PATCH /api/v1/memories/{id}`
-   `DELETE /api/v1/memories/{id}`
-   `GET /api/v1/sources`
-   `POST /api/v1/sources`
-   `GET /api/v1/agent-runs/{id}`
-   `POST /api/v1/agent-runs/{id}/cancel`
-   `GET /api/v1/settings`
-   `PATCH /api/v1/settings`

Semua endpoint harus memiliki authentication, authorization, validation,
rate limiting sesuai kebutuhan, error schema konsisten, dan audit untuk
aksi sensitif.

## 9.3 Task lifecycle

Gunakan status yang eksplisit: - `queued` - `gathering_context` -
`planning` - `awaiting_approval` - `approved` - `executing` -
`completed` - `failed` - `cancelled` - `expired`

Gunakan idempotency keys untuk action yang bisa menyebabkan side effect.

------------------------------------------------------------------------

# 10. Security, Privacy, dan Reliability

Security bukan fitur tambahan; ini bagian inti dari agent yang dapat
bertindak.

## Wajib

-   Jangan hardcode API keys, passwords, tokens, private keys, atau
    credentials.
-   Gunakan environment variables atau secret manager yang tersedia.
-   Jangan commit `.env` atau file secrets ke repository.
-   Redact secrets dan data sensitif dari logs.
-   Terapkan authentication dan authorization di semua API yang relevan.
-   Gunakan TLS/HTTPS untuk komunikasi eksternal.
-   Batasi tool permissions dan filesystem/network access.
-   Gunakan least privilege untuk database, n8n, server, dan agent
    tools.
-   Pisahkan development, staging, dan production bila memungkinkan.
-   Terapkan backup dan prosedur restore.
-   Sediakan audit trail dan emergency stop.
-   Validasi input dari user, dokumen, webhook, dan tool output.
-   Perlakukan isi dokumen/webpage/tool output sebagai untrusted input
    untuk mengurangi prompt injection.
-   Jangan menjalankan command atau kode dari dokumen yang diindeks
    tanpa validasi dan approval.
-   Jangan expose agent runtime atau database langsung ke internet tanpa
    proteksi.
-   Sediakan batas biaya dan usage untuk model cloud.
-   Sediakan retention dan deletion policy.

## Privacy

-   User harus mengetahui sumber yang sedang terhubung.
-   Semua integrasi bersifat opt-in.
-   Pisahkan data personal dan data perusahaan.
-   Jangan menganggap semua percakapan/dokumen layak disimpan sebagai
    memory.
-   Memory harus dapat dilihat, dikoreksi, dan dihapus.
-   Untuk notifikasi, hindari mengirim detail sensitif jika perangkat
    terkunci.

------------------------------------------------------------------------

# 11. Observability dan Evaluasi

Jarvis perlu dapat menjawab: apa yang diperiksa, mengapa rekomendasi
muncul, model/tool mana yang digunakan, apa yang dijalankan, dan
bagaimana hasilnya.

Minimal: - structured logs dengan redaction; - task execution history; -
error tracking; - latency dan token/cost usage jika relevan; -
retry/failure metrics; - source freshness; - notification delivery
status; - audit events untuk approval dan action; - health endpoints
untuk backend; - status koneksi n8n existing tanpa mengungkap
credential.

Evaluasi kualitas proactive behavior: - berapa banyak temuan yang
dianggap berguna; - false positive; - notifikasi yang di-dismiss; -
tindakan yang berhasil/gagal; - duplicate initiatives; - biaya per
tugas; - latency; - jumlah tindakan yang memerlukan koreksi.

Jangan optimalkan jumlah notifikasi. Optimalkan relevansi dan manfaat.

------------------------------------------------------------------------

# 12. MVP Scope

Tujuan MVP adalah menghasilkan APK dan backend yang bisa digunakan,
bukan membangun semua integrasi sekaligus.

## MVP yang disarankan

1.  Flutter Android app.
2.  Secure backend API.
3.  User profile dan preferences.
4.  Chat dengan satu provider/model yang dikonfigurasi.
5.  Persistent memory sederhana dengan user controls.
6.  Task/initiative feed.
7.  Scheduler/proactive checks di backend.
8.  Approval Center.
9.  Push notifications.
10. Audit log dan task lifecycle.
11. Integrasi awal dengan n8n existing melalui webhook/API, jika detail
    akses tersedia.
12. Admin/configuration yang aman untuk mengatur provider dan schedule.

## Jangan masuk MVP kecuali ada kebutuhan konkret

-   Fine-tuning model.
-   Banyak agent yang berjalan paralel.
-   Trading otomatis.
-   Full control atas seluruh perangkat.
-   Mengirim email atau mengubah production tanpa approval.
-   Integrasi semua aplikasi sejak hari pertama.
-   Membangun ulang n8n.
-   Membuat infrastruktur kompleks yang belum dibutuhkan.
-   Menjalankan beberapa agent runtime bersamaan.

## Definition of Done MVP

-   APK dapat login/terhubung ke backend dengan aman.
-   Chat berjalan dan menampilkan status proses serta error dengan
    benar.
-   Memory dapat disimpan, dilihat, diedit, dan dihapus.
-   Proactive job dapat berjalan di server saat APK tertutup.
-   Jarvis dapat membuat initiative dan mengirim notifikasi.
-   Approval/rejection tercatat dan mengontrol apakah action berjalan.
-   n8n existing dapat dipanggil melalui konfigurasi yang disetujui,
    tanpa membuat instance baru.
-   Tidak ada secret yang di-hardcode atau dicommit.
-   Ada README untuk setup lokal, konfigurasi, deployment, backup, dan
    troubleshooting.
-   Ada test untuk auth, memory, approval, scheduler, dan integrasi
    utama.
-   Ada langkah rollback dan tidak ada deployment production tanpa
    persetujuan pengguna.

------------------------------------------------------------------------

# 13. Instruksi Operasional untuk Claude Code

**Baca dokumen ini sebelum mulai mengubah kode.**

## Langkah awal yang wajib

1.  Periksa repository saat ini, struktur folder, git status, stack yang
    sudah dipakai, dan dokumentasi yang tersedia.
2.  Jangan menghapus atau menimpa pekerjaan yang sudah ada.
3.  Periksa environment/runtime yang tersedia hanya dengan cara
    read-only terlebih dahulu.
4.  Identifikasi lokasi backend, aplikasi Android, dan konfigurasi
    deployment.
5.  Periksa apakah ada database, authentication, push notification, atau
    service yang sudah berjalan sebelum mengusulkan penggantian.
6.  **Konfirmasi bahwa n8n sudah ada pada server existing. Jangan
    membuat atau menginstal n8n baru.**
7.  Buat implementation plan dengan file yang akan dibuat/diubah,
    dependencies, security impact, migration, dan cara test.
8.  Tandai asumsi yang belum diketahui; jangan mengarang URL,
    credential, port, model, RAM, database, atau server details.
9.  Jika butuh secret/akses yang belum diberikan, buat
    interface/configuration placeholder yang aman dan tanyakan informasi
    spesifik yang diperlukan.
10. Implementasikan secara incremental dan jalankan tests setelah tiap
    milestone.

## Guardrails untuk perubahan

-   Jangan melakukan deployment production, restart service existing,
    mengubah firewall, menghapus data, memigrasikan database, atau
    mengubah workflow n8n tanpa konfirmasi eksplisit.
-   Jangan melakukan tindakan destruktif hanya karena dianggap
    memudahkan development.
-   Jangan mencetak environment secrets.
-   Jangan membuka service ke internet tanpa authentication dan review.
-   Jangan mengasumsikan akses SSH atau akses ke server tersedia.
-   Jangan membuat layanan duplikat sebelum memeriksa apa yang sudah
    tersedia.
-   Gunakan migrations yang reversible jika memungkinkan.
-   Dokumentasikan semua konfigurasi baru dan alasan keputusan.
-   Jika ada pilihan teknologi yang belum ditentukan, rekomendasikan
    opsi beserta trade-off, lalu pilih default yang paling sederhana dan
    maintainable untuk MVP; jangan menunda semua progress karena detail
    non-kritis belum tersedia.

## Hasil kerja yang diharapkan

Claude Code diharapkan menghasilkan: 1. Architecture decision record
singkat. 2. Backend yang terstruktur dan teruji. 3. Flutter Android app.
4. Konfigurasi environment example tanpa secrets. 5. Database
schema/migrations. 6. API documentation. 7. Integrasi n8n existing
dengan configuration yang aman. 8. Automated tests. 9. README setup dan
deployment. 10. Daftar asumsi, batasan, risiko, dan pekerjaan lanjutan.

------------------------------------------------------------------------

# 14. Open Decisions yang Perlu Dikonfirmasi

Jangan menganggap item berikut telah diputuskan: - Detail hardware untuk
model lokal. - Provider/model AI final dan anggaran API. - Backend
language/framework final. - Database dan vector search final setelah
inspeksi environment. - Domain, TLS, dan authentication provider. - Push
notification provider/configuration. - Voice stack. - Detail akses dan
credential n8n existing. - Data sources pertama yang akan dihubungkan. -
Agent runtime final setelah compatibility test. - Hosting/deployment
target final.

Pilihan awal yang boleh dievaluasi: - Flutter untuk APK. - Modular
backend yang sederhana. - PostgreSQL dengan vector capability jika
dibutuhkan. - Hermes Agent sebagai kandidat pertama untuk diuji;
OpenClaw sebagai alternatif. - Qwen sebagai kandidat model lokal awal,
dengan cloud model fallback. - n8n existing untuk workflow automation.

------------------------------------------------------------------------

# 15. Ringkasan Keputusan dan Batasan yang Paling Penting

1.  Produk adalah **Jarvis personal AI assistant yang proaktif**, bukan
    chatbot biasa.
2.  Interface yang diminta adalah **APK Android**, direncanakan dibuat
    menggunakan **Claude Code**.
3.  Backend harus berjalan terpisah agar proactive jobs tetap berjalan
    saat APK ditutup.
4.  Jarvis harus mengumpulkan konteks dari sumber yang diizinkan,
    mengidentifikasi kebutuhan, membuat initiative, mengirim notifikasi,
    dan meminta persetujuan sebelum tindakan berisiko.
5.  Jarvis harus memiliki personal/project/knowledge/experience memory,
    RAG jika dibutuhkan, feedback loop, serta kontrol lihat/edit/hapus.
6.  Model harus bisa diganti; Qwen, DeepSeek, Gemma, gpt-oss, dan cloud
    models adalah kandidat untuk diuji, bukan keputusan final yang sudah
    dibuktikan.
7.  Hermes Agent adalah kandidat runtime awal; OpenClaw adalah
    alternatif. Jangan jalankan keduanya sekaligus tanpa alasan konkret.
8.  **n8n sudah ada di server existing. Dilarang membuat atau menginstal
    instance n8n baru. Reuse existing instance.**
9.  Default otonomi: Observe + Propose; Execute hanya untuk tindakan
    yang jelas diizinkan.
10. Security, privacy, auditability, approval, dan emergency stop adalah
    requirements inti.
11. Claude Code harus memeriksa repository dan environment sebelum
    implementasi, menghindari asumsi, dan meminta persetujuan sebelum
    perubahan berisiko.
12. MVP harus sederhana, dapat diuji, dan dapat dikembangkan bertahap.

------------------------------------------------------------------------

**End of knowledge base.**
