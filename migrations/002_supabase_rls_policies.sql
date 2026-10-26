-- AuthenTra Database Migration 002: Supabase Schema & Row-Level Security (RLS) Policies
-- This migration configures Row-Level Security for PostgreSQL / Supabase deployments.
-- Roles: USER, INSTITUTION_ADMIN, SYSTEM_ADMIN

-- ==============================================================================
-- 1. Helper Function: Extract User Role and ID from Supabase Auth JWT
-- ==============================================================================

CREATE OR REPLACE FUNCTION auth.current_authentra_user()
RETURNS TABLE (user_id BIGINT, role TEXT, approval_status TEXT) AS $$
  SELECT
    (auth.jwt() -> 'app_metadata' ->> 'user_id')::BIGINT AS user_id,
    COALESCE(auth.jwt() -> 'app_metadata' ->> 'role', 'USER') AS role,
    COALESCE(auth.jwt() -> 'app_metadata' ->> 'approval_status', 'PENDING_APPROVAL') AS approval_status;
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- ==============================================================================
-- 2. Enable Row-Level Security (RLS) on all tables
-- ==============================================================================

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE registrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit ENABLE ROW LEVEL SECURITY;

-- ==============================================================================
-- 3. RLS Policies: users table
-- ==============================================================================

-- SYSTEM_ADMIN can view all users
CREATE POLICY system_admin_select_users ON users
  FOR SELECT
  TO authenticated
  USING ((SELECT role FROM auth.current_authentra_user()) = 'SYSTEM_ADMIN');

-- Users can view their own profile
CREATE POLICY users_select_own_profile ON users
  FOR SELECT
  TO authenticated
  USING (id = (SELECT user_id FROM auth.current_authentra_user()));

-- SYSTEM_ADMIN can update approval_status (e.g. approve, reject, suspend, revoke institutions)
CREATE POLICY system_admin_update_users ON users
  FOR UPDATE
  TO authenticated
  USING ((SELECT role FROM auth.current_authentra_user()) = 'SYSTEM_ADMIN')
  WITH CHECK ((SELECT role FROM auth.current_authentra_user()) = 'SYSTEM_ADMIN');

-- Users and Institutions CANNOT modify their own roles or approval_status
-- (Enforced by backend and column triggers)

-- ==============================================================================
-- 4. RLS Policies: verifications table (Private verification history)
-- ==============================================================================

-- USER can only select their own verification records
CREATE POLICY user_select_own_verifications ON verifications
  FOR SELECT
  TO authenticated
  USING (
    user_id = (SELECT user_id FROM auth.current_authentra_user())
    AND (SELECT role FROM auth.current_authentra_user()) IN ('USER', 'INSTITUTION_ADMIN')
  );

-- USER can insert their own verification records (max 5 per batch enforced at API level)
CREATE POLICY user_insert_verifications ON verifications
  FOR INSERT
  TO authenticated
  WITH CHECK (
    user_id = (SELECT user_id FROM auth.current_authentra_user())
    AND (SELECT role FROM auth.current_authentra_user()) IN ('USER', 'INSTITUTION_ADMIN')
  );

-- SYSTEM_ADMIN can inspect all verification records for platform auditing (read-only)
CREATE POLICY system_admin_select_all_verifications ON verifications
  FOR SELECT
  TO authenticated
  USING ((SELECT role FROM auth.current_authentra_user()) = 'SYSTEM_ADMIN');

-- SYSTEM_ADMIN cannot insert verifications (no upload/verify permission)
-- No INSERT policy for SYSTEM_ADMIN on verifications

-- ==============================================================================
-- 5. RLS Policies: registrations table (Certificate Blockchain Records)
-- ==============================================================================

-- INSTITUTION_ADMIN can view their own registered certificates
CREATE POLICY institution_select_own_registrations ON registrations
  FOR SELECT
  TO authenticated
  USING (
    issuer_id = (SELECT user_id FROM auth.current_authentra_user())
    AND (SELECT role FROM auth.current_authentra_user()) = 'INSTITUTION_ADMIN'
  );

-- Only APPROVED and ACTIVE INSTITUTION_ADMIN can insert registrations
CREATE POLICY institution_insert_registrations ON registrations
  FOR INSERT
  TO authenticated
  WITH CHECK (
    issuer_id = (SELECT user_id FROM auth.current_authentra_user())
    AND (SELECT role FROM auth.current_authentra_user()) = 'INSTITUTION_ADMIN'
    AND (SELECT approval_status FROM auth.current_authentra_user()) = 'APPROVED'
  );

-- SYSTEM_ADMIN can inspect all registered certificates across institutions (read-only)
CREATE POLICY system_admin_select_all_registrations ON registrations
  FOR SELECT
  TO authenticated
  USING ((SELECT role FROM auth.current_authentra_user()) = 'SYSTEM_ADMIN');

-- SYSTEM_ADMIN CANNOT insert registrations (no blockchain certificate writing permission)
-- No INSERT policy for SYSTEM_ADMIN on registrations

-- USER CANNOT view registrations table directly or insert
-- (USER only gets public verification results via verification endpoint)

-- ==============================================================================
-- 6. RLS Policies: audit table
-- ==============================================================================

-- SYSTEM_ADMIN can view the complete platform audit trail
CREATE POLICY system_admin_select_all_audit ON audit
  FOR SELECT
  TO authenticated
  USING ((SELECT role FROM auth.current_authentra_user()) = 'SYSTEM_ADMIN');

-- INSTITUTION_ADMIN can only view their own institution's audit logs
CREATE POLICY institution_select_own_audit ON audit
  FOR SELECT
  TO authenticated
  USING (
    user_id = (SELECT user_id FROM auth.current_authentra_user())
    AND (SELECT role FROM auth.current_authentra_user()) = 'INSTITUTION_ADMIN'
  );

-- Authenticated roles can insert audit records for their own actions
CREATE POLICY authenticated_insert_audit ON audit
  FOR INSERT
  TO authenticated
  WITH CHECK (user_id = (SELECT user_id FROM auth.current_authentra_user()) OR user_id IS NULL);

-- Audit table records are immutable (no UPDATE or DELETE policies)
