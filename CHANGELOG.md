# 1.1.0 — 2026-09-06

- Expand 128 → 384 fictional items; preserve original IDs and numerical values.
- Expand 3 → 10 scripted games with validated choices and persistent outcomes.
- Use pure black default backgrounds and versioned CSS.
- Fix no-referrer/Origin form incompatibility without weakening CSRF checks.
- Add translated recoverable authentication errors; atomic account/session creation.
- Display BRL, USD, CNY or JPY notation by language; no currency conversion.
- Preserve receipt/round navigation when changing language.
- Add a backward-compatible extended game history schema and complete exports/deletion.
- Correct Gunicorn forwarder_headers type in distributed source.
- Preserve the working npm-bridge deployment; add manifest-checked updater,
  private backups, exact-image retention and code/image-only rollback.
- Record 88 tests, 372 offline layouts, 152 local TLS/proxy HTTP requests and
  an old-source compatibility test. See AUDIT.md for unexecuted checks.
