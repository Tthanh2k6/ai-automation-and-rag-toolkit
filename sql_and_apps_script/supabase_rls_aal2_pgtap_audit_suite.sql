-- =============================================================================
-- RegiMet Health (MIP) — PR #146 Independent RLS & pgTAP Verification Template
-- Offline / Static Audit Reference (Zero External AI Upload • Synthetic Only)
-- =============================================================================

-- 1. VERIFYING RESTRICTIVE AAL2 + ACTIVE CLINICIAN-PATIENT ASSIGNMENT POLICY
-- Why: Standard PERMISSIVE policies combine with OR. If any legacy policy on
-- laboratory_results is permissive, an AAL1 session could still read rows.
-- Making the MFA/AAL2 guard RESTRICTIVE enforces an AND condition across all policies.

CREATE POLICY "enforce_aal2_and_active_clinician_assignment"
ON public.laboratory_results
AS RESTRICTIVE
FOR ALL
TO authenticated
USING (
    (auth.jwt() ->> 'aal') = 'aal2'
    AND EXISTS (
        SELECT 1
        FROM public.clinician_patient_assignments cpa
        WHERE cpa.patient_id = laboratory_results.patient_id
          AND cpa.clinician_id = auth.uid()
          AND cpa.status = 'active'
          AND cpa.revoked_at IS NULL
    )
)
WITH CHECK (
    (auth.jwt() ->> 'aal') = 'aal2'
    AND EXISTS (
        SELECT 1
        FROM public.clinician_patient_assignments cpa
        WHERE cpa.patient_id = laboratory_results.patient_id
          AND cpa.clinician_id = auth.uid()
          AND cpa.status = 'active'
          AND cpa.revoked_at IS NULL
    )
);

-- 2. HARDENING SECURITY DEFINER HELPER FUNCTIONS
-- Why: Prevents schema-shadowing privilege escalation and unauthorized execution.
CREATE OR REPLACE FUNCTION public.is_assigned_clinician_aal2(target_patient_id uuid)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
STABLE
AS $func$
    SELECT (auth.jwt() ->> 'aal') = 'aal2'
       AND EXISTS (
           SELECT 1
           FROM public.clinician_patient_assignments
           WHERE patient_id = target_patient_id
             AND clinician_id = auth.uid()
             AND status = 'active'
             AND revoked_at IS NULL
       );
$func$;

REVOKE ALL ON FUNCTION public.is_assigned_clinician_aal2(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_assigned_clinician_aal2(uuid) TO authenticated;

-- 3. NON-VACUOUS pgTAP REGRESSION TEST PATTERN (PREVENTING FALSE POSITIVES)
-- Why pgTAP suites often pass 150/150 while vulnerabilities remain:
--   (a) Running assertions before executing SET LOCAL ROLE authenticated (postgres has BYPASSRLS).
--   (b) Asserting 0 rows at AAL1 without first proving the synthetic fixture row exists at AAL2.
--   (c) Testing SELECT visibility but omitting UPDATE/DELETE/INSERT negative assertions.

BEGIN;
SELECT plan(4);

-- Switch out of superuser into standard Supabase authenticated role
SET LOCAL ROLE authenticated;

-- Case A: Clinician at AAL1 MUST be denied laboratory_results access (0 rows visible)
SELECT set_config(
    'request.jwt.claims',
    json_build_object('sub', 'clinician-uuid-A', 'role', 'authenticated', 'aal', 'aal1')::text,
    true
);
SELECT is_empty(
    'SELECT id FROM public.laboratory_results',
    'AAL1 session must return 0 laboratory_results even when clinician assignment is active'
);

-- Case B: Same Clinician elevated to AAL2 MUST see assigned patient lab result (proves fixture is non-empty)
SELECT set_config(
    'request.jwt.claims',
    json_build_object('sub', 'clinician-uuid-A', 'role', 'authenticated', 'aal', 'aal2')::text,
    true
);
SELECT results_eq(
    'SELECT count(*)::int FROM public.laboratory_results',
    ARRAY[1],
    'AAL2 session with active assignment must see exactly 1 synthetic laboratory result'
);

SELECT * FROM finish();
ROLLBACK;

