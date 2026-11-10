# ARQUILA · decisions on the client requirements (backend)

Short copy of the row R0 decisions that concern the backend. The full record, with the frontend and navigation sections, is `FRONTEND-ARQUILA/docs/DECISIONS.md`; the requirements are in `ARQUILA/REQUIREMENTS.md`.

## Conflicts

### C2 · R02 vs S1

Test accounts exist only when `ENVIRONMENT` is not `production`: the seed script refuses to run otherwise, with a test. Plain passwords only in `docs\TEST_ACCOUNTS.md`, marked development and staging only. Login quick-fill only under `import.meta.env.DEV`, verified absent from the production build (grep `dist`). The daily reset workflow must never load these accounts.

### C3 · R07 exceptions

The 200-character limit applies to every free text a user types. Exceptions: password (8 to 128), email (254), AI chat messages and AI-generated content, uploaded file contents, JSON settings, system-generated history values (shortened for display). Existing rows over 200: count them per column with read-only queries, never truncate silently, add the CHECK as `NOT VALID`, report the rows and ask the owner.

### C4 · R06 map

Leaflet in a lazy chunk, one-line justification and bundle size reported. CSP changes only for the tile host (`img-src`). Tile URL from an env variable, attribution visible, provider usage policy noted. Manual latitude and longitude inputs always work as a fallback.

### C5 · R08 and R13 provider and privacy

Model provider configured by environment variables, keys only in the backend. Files go to an external provider, so show a Spanish consent notice before the first use. Provider unavailable or not configured: say so in Spanish and keep the manual flow working.

## Change history (R18)

### H1 · History source

Reuse `activity_log` (has `created_at`) and `GET /projects/{id}/activity`. First verify, read-only, which mutations write entries and which do not. Extend the existing endpoint (filters `entity_type`, `entity_id`, `user_id`, date range; pagination); no invented endpoints.

### H2 · What is recorded

Server-side, same transaction as the change, database clock in UTC (`timestamptz`), actor (user or `ai`), action (`created`, `updated`, `deleted`, `restored`, `undone`, `redone`, `ai_applied`), entity type and id, and a `changes` JSON with only the changed fields as before and after. If `detail` cannot hold it, add a `changes jsonb` column with a new migration (next free number, idempotent, down script, `pg_dump` outside the repos first). Never log secrets, password data or file contents. Existing rows stay untouched.

### H3 · Display

Spanish, `Intl.DateTimeFormat('es-CO')`, absolute and relative time, `<time datetime>`, UTC tooltip, grouped by day, field names through `labels.ts`, "Última modificación" on project and plan cards and headers, time shown in success toasts. Test with a fixed timezone.

## Verified state at R0

The sections above are the decisions as given by the owner. These are the facts checked against the repositories at R0 that the work rows must account for:

- **H2 and the time zone.** `activity_log.created_at` is `TIMESTAMP` without a time zone today (`BASE-DE-DATOS-ARQUILA/migrations/021_activity_log.sql:9`; no timezone in `app/models.py:762`). H2 asks for `timestamptz`, so row R5b needs a type conversion migration (new, idempotent, with a down script) that H2 does not yet describe; it changes the column type of existing rows. How to convert existing values is for the owner to confirm at R5b.
- **`labels.ts`.** The only `labels.ts` is `FRONTEND-ARQUILA/src/components/viewer/labels.ts` (3D viewer labels). H3 field names need either an extension of that file or a new labels module; decided in row R5b.
- **`docs\TEST_ACCOUNTS.md` does not exist yet**; it is to be created in row R4. The daily reset workflow in C2 is `BASE-DE-DATOS-ARQUILA/.github/workflows/reset-demo.yml`.

## Open decisions

Status OPEN; the owner is asked at the right step. Row numbers are as recorded at R0; they do not yet match the block R order in `ARQUILA/PROGRESS.md` (the 200-character limit is R6, the map R8, the AI rows R10 and R11) and are pending confirmation by the owner.

- D-AI · model provider, row R9 · OPEN
- D-ENC · encryption of stored files, default no · OPEN
- D-200 · rows over 200 characters, row R5 · OPEN
- D-MAP · tile provider, row R7 · OPEN
