# Gamebook Dashboard Reliability Release Checklist

Status: **STAGING ONLY.** Do not merge or copy these changes directly to `main`
until the automated tests and manual checks below pass.

## Release scope
- Archive protection: reject absent, unreadable, malformed, or duplicate historical data.
- Preserve all existing game identities and previously saved report links.
- Write archive files atomically after successful validation.
- Check each proposed archive against the checked-out Git baseline before any
  regular update or historical backfill is published.
- No change to game discovery, official PDF verification, public UI, or scheduling.

## Required checks for each league
1. Begin from the current `main` commit (never assume old staging is current).
2. Verify a backup ref exists and record the current `main` commit SHA.
3. Run **Archive integrity safety tests (staging)** on the correct branch.
4. Confirm tests for corrupt JSON, duplicate records, missing files, simulated
   write failure, existing-link retention, and actual repository archive data.
5. Confirm the release gate checks both ordinary updates and historical backfills.
6. For NBA, separately verify WNBA update and WNBA historical backfill checks.
7. Review all warnings and errors; a green check is not proof of live completeness.
8. Review the precise diff against current production. Do **not** overwrite the
   production archive with the stale copy from staging.
9. Deploy only code, tests and protective workflow steps, one repository at a time.
10. Run a fresh production workflow and check the workflow's commit SHA, archive
    count and previously verified report links.
11. Confirm the website and Mega Board show expected records, and review alerts.

## Failure/rollback
- If validation fails, leave `main` unchanged and fix staging first.
- If a deployed workflow blocks publication, inspect the archive and the
  failing gate; do not bypass safety checks just to get a green run.
- Preserve and inspect the last healthy committed `archive.json`.
- Roll back only the code/workflow change if needed; NEVER overwrite newer data
  with an old backup branch without comparing historical records.
- Each regular or backfill workflow must finish the integrity gate **before**
  its commit/push step. Local runner writes are not production publications.

## Known limitations / follow-up
- Backfill Python scripts still write their local working files directly;
  the pre-publication gate blocks data loss before pushing, but atomicity of
  backfill-local writes is a separate proposed improvement.
- A Git checkout baseline is not an independent off-platform backup.
- Rebase/push conflict handling requires a separate integration review.
- Large MLB archive readability must be verified via an actual GitHub Actions
  checkout; connector text-fetch limitations are not proof of corruption.
- Individual link correctness and all-league independent schedule completeness
  are separate reviews; these safeguards protect historical continuity, not
  proof that each link is the correct official report.
