# Dopamine 1.2.1 — early11-schema2-v1

- Recognize the confirmed early 1.1.0 source and runtime by content hashes, not
  by the ambiguous 1.1.0 version string. Known prior documentation copies accepted.
- Report all unsupported local changes at once; do not normalize source files.
- Add new tables/indices/views in a single transaction for the known schema-2
  layout. Preserve the original rounds table and keep user_version=2.
- Render original early-1.1 result JSON and preserve all 512 historical catalog
  identities. Do not merge the two incompatible catalogs sharing old IDs.
- Retain the original image and unchanged .env/volume. Rehearse on a snapshot,
  stop only web for a final snapshot/rehearsal, and keep POSTs gated until checks pass.
- Roll back source/image without overwriting later live database activity.
- Remove only four verified obsolete functional/test files, with rollback copies.
- Require at least 513 qualifying real catalog entries (maximum 640), rather than
  silently publishing fewer items than the early 512-listing source.
- Add 33 bridge-specific regression tests; 156 total tests passed in this session.

Docker, Fish, production Gunicorn/NPM, photo downloads and a current CVE scan were
not executed in this authoring environment. No live VPS access was performed.
