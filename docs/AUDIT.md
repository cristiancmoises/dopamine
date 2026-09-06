# Dopamine 1.2.0 — engineering review and validation

Date: 2026-09-06. Scope: supplied source, new catalog importer, interactive tables, additive database changes and conservative updater. This is an implementation review with automated regression evidence, not an independent security certification or a guarantee that all bugs are eliminated. The source basis is the final 384-item/10-game 1.1 bundle; original 1.0 is an additional supported upgrade/rollback baseline.

## Changes reviewed
- Replaced the active fictional/category-photo catalog with a candidate-to-live publication pipeline. Current source contains 1,056 candidates across 18 categories. Minimum publication 400, cap 640, category-interleaved processing. Every published subject needs stable identity and unique source/optimized image. Archived fictional identities are used only for history, not renamed into branded goods.
- Added seven server-authoritative tables. Roulette and cards calculate outcomes, not scripted wins. Blackjack actions are persisted, with a private deck, hidden dealer hole card, first-decision double and optimistic revision checks. Baccarat implements the documented third-card variant. Custom slot/dice/Keno/Plinko paytables are displayed explicitly.
- Kept unlimited demo balance using a separately labeled simulated stake refund and 100-unit grant. Actual table wins, losses and pushes remain distinct. No autoplay, real money, cashouts, payment credentials or promotional casino links were added.
- Added one local unminified MIT/Expat enhancement file (8,631 bytes at review), GNU-style license labels, SRI and CSP script/connect scope only on /play/ paths. Forms also work without JavaScript. No eval, inline event handlers, third-party scripts or client-trusted payout values.
- Preserved CSRF, same-origin referrer policy, exact trusted proxy addresses, secure cookies, parameterized SQL, account-bound access, pause enforcement and rate limits. Requests use nonce uniqueness/transactions; blackjack uses revision checks. In-flight network failure is not auto-retried. The UI marks a replaced table busy until its animation completes.
- Preserved .env, secret, named data volume, working npm-bridge and NPM upstream. Build/photo failure prevents source/container switching. Migrations are additive, tested twice on a snapshot copy before production switch. Source/image rollback does not overwrite the current database with an old snapshot.

## Executed evidence
**123 unittest methods passed** in the final run (19.374 seconds). Evidence: `docs/test-results.txt`. The suite includes the earlier regression cases plus 35 new table/photo cases. Product-page tests include **4,224 candidate/language response checks** (1,056 × four languages); those checks do NOT establish real photograph availability or visual correctness.

Engine cases include all 37 roulette pockets, 216 reel combinations, 36 two-dice outcomes per choice, all 256 Plinko paths, 80 banker third-card cases, natural blackjack, soft-ace totals, doubling, illegal moves, hidden-deck redaction, Keno uniqueness and disclosed payouts. The slot enumeration produces total expected return 205/216 before grants for this exact custom paytable, not a claim about commercial machines.

Web cases cover account creation/security regression, foreign/null origins, CSRF, ownership, replayed starts, stale/concurrent blackjack actions, pause enforcement, saved rounds, private export, deletion cascade, current versus historical product identity, all table languages and scoped free-script licensing. The existing Python HTTP integration test passed; this is not a production Gunicorn/NPM test.

Photo cases use synthetic TEST fixtures only: strict source/redirect allowlist, identity mismatch, unknown/missing attribution, bounded raster decoding, exact/perceptual duplicate detection, insufficient inventory, network failure without placeholders, normalized Commons filenames and cached rights updates. A test log line such as `PHOTO 001: Nikon D850` is a mocked metadata/PNG fixture, NOT a real imported image. Likewise the inherited `PHOTOS VERIFIED: 2` output comes from legacy unit fixtures.

**56 offline Chromium interaction flows passed**, across seven tables, four languages and desktop/mobile widths, with 72 real WSGI handler POSTs backed by disposable SQLite and no JavaScript errors. The harness executes production HTML/CSS/JS with ONLY a test-injected transport/location/history bridge. **Seven additional flows at 320 px with animations enabled passed**, including nine WSGI POSTs. Evidence: `browser-interactions.json`, `browser-motion-320.json`. These are NOT native browser HTTP, cookie-transport, CSP enforcement, TLS or NPM validation.

**372 offline JavaScript-disabled layout checks passed**, across three viewport sizes and four languages, covering shop/authentication/profile/collection/classic game pages. No horizontal overflow; body background black. Native language details and motion checkbox passed. No product photo binaries were present. Evidence: `browser-layout-report.json`.

**Source-level backward compatibility passed separately for untouched 1.0.0 and final 1.1.0.** Earlier source could initialize/access an upgraded disposable database, authenticate, view purchase history/receipt and make an old-catalog purchase. Re-upgrade preserved account, both purchases, original fictional receipt identity and interactive round; SQLite integrity and foreign keys passed. Old versions do not display new practice routes while their data stays stored. Evidence: `compatibility-100.json`, `compatibility-110.json`. This is NOT an old-image Docker rollback test.

Node syntax check for tables.js and Python compileall passed. Updater unit tests use mocked Docker; they do not constitute an actual container deployment. Release manifest baseline/hash checks are recorded separately in `manifest-verification.json` when the final bundle is packaged.

## Photo publication limitations — important
There are **zero production photo binaries in this archive**. Runtime network/DNS failures prevented a complete Commons import here. External browsing inspected API documentation and example identity records, not hundreds of downloaded pictures. The build on the VPS must import 400–640 qualifying subjects/photos and recheck every local file before switching the app. It may fail safely if sources cannot meet that floor. Candidate count and category count are not promises of the eventual published count or coverage.

Automated filename/description/model matching cannot guarantee visual identity. SHA-256/pixel hashes and dHash reject identified exact/near duplicates but do not prove no possible visual alias exists. License/creator metadata can be wrong; Commons explicitly does not warrant it. Per-photo source/author/license/change links are preserved so operators can review the publication. Non-copyright rights may still apply. No generated image or category fallback is used to obtain a passing count.

## Not executed / not claimed
Docker, Fish and Gunicorn were unavailable here. The required commands run during the VPS update, but no success is claimed in advance. A native Chromium localhost request failed with ERR_BLOCKED_BY_ADMINISTRATOR; no attempt was made to bypass that policy. The bridge tests must not be described as browser-native end-to-end HTTP. The LibreJS extension was not run; license declarations/source labels are provided, not an extension certification. There was no independent penetration test, production load test, current dependency/image CVE scan, complete photo visual/rights audit or live deployment.

The base image remains python:3.13-slim rather than a pinned digest, and source metadata can change between imports. This release is not byte-reproducible across all build dates. Dependency pins are retained from the baseline, adding Pillow 12.3.0; pin existence is not a security audit. Revalidate dependencies and the final container on the VPS.

## Operational risks and mitigations
Photo/network failure: refuse publication, keep current app, retain public BuildKit cache/report for diagnosis. Incorrect photo attribution/identity: retain source evidence and require operator review; do not silently substitute. Unknown local changes/conflicting early 1.1 archive: stop preflight rather than overwrite. Failed deployment after switch: attempt exact source/image rollback on the same volume; do not erase newer transactions. Private backups contain secrets/user records without encryption; owner must protect and retain them deliberately. No automatic pruning or irreversible cleanup is introduced.

## Primary references used
- Wikimedia reuse and limitations: https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia
- MediaWiki Imageinfo: https://www.mediawiki.org/wiki/API:Imageinfo
- MediaWiki PageImages: https://www.mediawiki.org/wiki/Extension:PageImages
- GNU JavaScript labels: https://www.gnu.org/licenses/javascript-labels.html
- Free JavaScript guidance: https://www.gnu.org/software/librejs/free-your-javascript.html
- Pillow upstream: https://github.com/python-pillow/Pillow/releases
- Baccarat rules reference: https://www.theoceanac.com/casino/table-games/how-to-play-mini-baccarat

The project's own rule implementations/tests are the source of claims about this simulator's outcomes. These references do not certify Dopamine or imply endorsement.
