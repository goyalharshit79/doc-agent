-- ── DocAgent Monetization: Supabase Migration ──────────────────────────────
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- Creates user_profiles table + razorpay_events audit log + auto-create trigger

-- ────────────────────────────────────────────────────────────────────────────
-- 1. user_profiles — one row per user, tracks plan + usage
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.user_profiles (
    user_id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    plan            TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pro')),
    is_unlimited    BOOLEAN NOT NULL DEFAULT FALSE,

    -- Razorpay subscription tracking
    razorpay_subscription_id TEXT,
    razorpay_customer_id     TEXT,
    subscription_status      TEXT DEFAULT 'none' CHECK (subscription_status IN ('none', 'created', 'authenticated', 'active', 'pending', 'halted', 'cancelled', 'completed', 'expired')),

    -- Daily query counter (simple: resets when query_date != today)
    queries_today   INT NOT NULL DEFAULT 0,
    query_date      DATE NOT NULL DEFAULT CURRENT_DATE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for quick lookup by subscription
CREATE INDEX IF NOT EXISTS idx_user_profiles_subscription
    ON public.user_profiles(razorpay_subscription_id);

-- ────────────────────────────────────────────────────────────────────────────
-- 2. razorpay_events — audit log of all webhook payloads
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.razorpay_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────────────────────
-- 3. Auto-create user_profiles row on signup (trigger on auth.users)
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_profiles (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Drop existing trigger if any, then create
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- ────────────────────────────────────────────────────────────────────────────
-- 4. Backfill existing users who don't have a profile yet
-- ────────────────────────────────────────────────────────────────────────────
INSERT INTO public.user_profiles (user_id)
SELECT id FROM auth.users
WHERE id NOT IN (SELECT user_id FROM public.user_profiles)
ON CONFLICT (user_id) DO NOTHING;

-- ────────────────────────────────────────────────────────────────────────────
-- 5. RLS policies (service key bypasses RLS, but good practice)
-- ────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.razorpay_events ENABLE ROW LEVEL SECURITY;

-- Users can read their own profile
CREATE POLICY "Users can read own profile" ON public.user_profiles
    FOR SELECT USING (auth.uid() = user_id);

-- Service role can do everything (backend uses service key)
CREATE POLICY "Service role full access on profiles" ON public.user_profiles
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access on events" ON public.razorpay_events
    FOR ALL USING (auth.role() = 'service_role');
