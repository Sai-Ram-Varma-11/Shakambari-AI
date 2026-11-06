-- Shakambari AI: Email OTP, Auth Hardening, Handover Codes, and Persistence (PostgreSQL)

-- 1. Users table upgrades
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE NOT NULL;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITHOUT TIME ZONE;

-- Seed / existing legacy users verified by default
UPDATE public.users SET email_verified = TRUE, email_verified_at = CURRENT_TIMESTAMP WHERE email_verified IS NULL OR email_verified = FALSE;

-- 2. NGO Partner upgrades
ALTER TABLE public.ngo_partners ADD COLUMN IF NOT EXISTS document_url VARCHAR(500);
ALTER TABLE public.ngo_partners ADD COLUMN IF NOT EXISTS approval_note VARCHAR(500);

-- 3. Redistribution Requests upgrades
ALTER TABLE public.redistribution_requests ADD COLUMN IF NOT EXISTS handover_code_hash VARCHAR(128);
ALTER TABLE public.redistribution_requests ADD COLUMN IF NOT EXISTS handover_code_enc VARCHAR(256);

-- 4. Image Observations upgrades
ALTER TABLE public.image_observations ADD COLUMN IF NOT EXISTS provider VARCHAR(40) DEFAULT 'heuristic' NOT NULL;
ALTER TABLE public.image_observations ADD COLUMN IF NOT EXISTS model_name VARCHAR(80) DEFAULT 'color-heuristic-v1' NOT NULL;

-- 5. Alerts upgrades
ALTER TABLE public.alerts ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(120);
ALTER TABLE public.alerts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE public.alerts ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP WITHOUT TIME ZONE;
CREATE INDEX IF NOT EXISTS ix_alerts_fingerprint ON public.alerts (fingerprint);

-- 6. Notifications upgrades
ALTER TABLE public.notifications ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(120);
CREATE INDEX IF NOT EXISTS ix_notifications_user_read ON public.notifications (user_id, is_read);
CREATE INDEX IF NOT EXISTS ix_notifications_dedup_key ON public.notifications (dedup_key);

-- 7. Email OTP table
CREATE TABLE IF NOT EXISTS public.email_otps (
    id SERIAL PRIMARY KEY,
    email VARCHAR(254) NOT NULL,
    purpose VARCHAR(20) NOT NULL,
    code_hash VARCHAR(128) NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    attempts INTEGER DEFAULT 0 NOT NULL,
    max_attempts INTEGER DEFAULT 5 NOT NULL,
    consumed_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ip VARCHAR(45)
);
CREATE INDEX IF NOT EXISTS ix_email_otps_lookup ON public.email_otps (email, purpose, created_at);

-- 8. Model Blobs table for ML models persistence
CREATE TABLE IF NOT EXISTS public.model_blobs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) UNIQUE NOT NULL,
    data BYTEA NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_model_blobs_name ON public.model_blobs (name);

-- 9. Additional Performance Indexes
CREATE INDEX IF NOT EXISTS ix_bookings_student_schedule ON public.bookings (student_id, schedule_id);
