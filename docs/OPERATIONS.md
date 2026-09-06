# Dopamine 1.2.0 — deployment and recovery

## What is delivered
An update for /opt/dopamine, not a replacement installation. Supported baselines: original 1.0.0 (including the forwarder_headers hotfix), and the final 384-item/10-game 1.1.0 bundle. Unknown edits and the conflicting early 1.1 archive are refused. No .env or real user database is included in this package.

Photographs are NOT embedded. The VPS image build resolves, downloads and checks the real catalog. Candidate count: 1,056 across 18 categories. Publication floor: 400 unique metadata-verified subjects/photos. Cap: 640. The actual count and category coverage depend on sources passing every check. No human visual audit of the eventual photo set has been done here. The running app is not switched if the build cannot meet the publication floor.

## Upload from your computer (Fish)
Download dopamine-update-1.2.0.tar.gz into ~/Downloads, then run:

```fish
scp -P 5119 ~/Downloads/dopamine-update-1.2.0.tar.gz root@securityops.co:/root/
ssh -p 5119 root@securityops.co
```

## On the VPS (Fish)
Verify the SHA-256 supplied next to the archive before extraction. Use a fresh staging folder; do not rename /opt/dopamine, delete volumes or rerun the old install script.

```fish
function dopamine_update_120
    set -l archive /root/dopamine-update-1.2.0.tar.gz
    test -f "$archive"; or return 1
    set -l stage (mktemp -d /root/dopamine-update-1.2.0.XXXXXXXX)
    test -n "$stage"; or return 1
    tar --no-same-owner --no-same-permissions -xzf "$archive" -C "$stage"; or return 1
    set -l installer "$stage/dopamine-update-1.2.0/apply.fish"
    echo "Extracted package: $stage/dopamine-update-1.2.0"
    fish "$installer" --target /opt/dopamine --npm npm-attachment --check; or return 1
    fish "$installer" --target /opt/dopamine --npm npm-attachment
end
dopamine_update_120
set -l update_status $status
functions -e dopamine_update_120
test "$update_status" -eq 0
```

Preflight needs Docker Engine/Compose, Python 3 and Fish already installed. It checks exact running settings against .env without printing secret values. PROXY_NETWORK must remain npm-bridge. TRUSTED_PROXY_CIDRS must contain the actual current NPM address as /32 or /128; it is checked, not replaced with a historical address. The source files must match a supported baseline. At least 2 GiB free space in the target filesystem is required; Docker's storage partition must also have room for the old and new images and BuildKit cache. The updater does not prune or automatically install dependencies.

## Update sequence
1. Verify baseline and payload hashes, lock deployment, check current NPM-to-app health.
2. Retain the exact old image; create private source/.env backups and a consistent, integrity-checked SQLite snapshot.
3. Build candidate while the existing app runs. Run unit/integration tests and Gunicorn configuration check. Import and verify unique model-specific pictures; no category fallback or old photo reuse. Successful public downloads persist in the local BuildKit cache even across a failed build.
4. Rehearse additive migrations twice on a COPY of the database snapshot inside the candidate image. The rehearsal container has no network or live data-volume mount.
5. Recheck source/configuration, install only manifest-owned files, recreate only web using the existing named volume and npm-bridge. This step causes an application-only interruption; it is not zero-downtime deployment.
6. Verify container/image/volume, photographs and NPM requests to /healthz, /shop, /signup. Copy public import provenance and reports into the printed backup folder.

Neither NPM nor unrelated containers are restarted. No firewall, DNS, certificates, NPM database, host ports or secret are changed. Never move the service back to dopamine-proxy.

## NPM and final public check
Keep the Proxy Host: dopamine.securityops.co, scheme http, hostname dopamine-web, port 8000, current valid certificate and Force SSL. No new websocket support is required.

```fish
curl --fail --silent --show-error --connect-timeout 10 --max-time 20 -D - https://dopamine.securityops.co/healthz
```

Expect HTTP 200, `X-Dopamine-Version: 1.2.0` and body `{"status":"ok","service":"dopamine"}`. This command validates TLS normally; do not add `-k` as a success test. Reopen /signup after upgrading rather than submitting an old form. Then test a fresh registration, one purchase, blackjack hit/stand and a language change in your own browser. No test account is automatically created in production by the updater.

## If the image import cannot finish
Read the build output and the accepted count. The existing app remains running because no source/container switch occurs before the build succeeds. Do not lower the 400-product floor to hide missing photographs, disable hash checks, reuse category photos or invent licenses. Causes can include network/DNS failure, Wikimedia rate limits, exact subject mismatches, unsupported licenses or duplicate images. The candidate registry is not a promise that every record can be published.

The last public import report is retained in cache id `dopamine-real-catalog-v120` for the SAME local BuildKit builder. From the extracted package's `release` directory, read it without changing the cache:

```fish
docker build --no-cache --progress=plain -f Dockerfile.catalog-report .
```

No image from this diagnostic build is deployed. If no report exists, inspect the original failure log; failure may have preceded import. Once publication succeeds, reports are also copied to `/opt/dopamine-backups/<timestamp>/catalog-import-report.json`, `catalog-live.json` and `photos-resolved.json`. The actual WebP files remain in the image at /app/app/static/photos, not an external hotlink.

## Data semantics
Old fictional listings are archived, not renamed into real models. Their original names and stored amounts remain available on receipts. Old cart/favorite rows remain in the database but are excluded from current shopping navigation; there is no meaningful one-to-one conversion. The old 32 category images are not copied into the new image. Brand/model identities and photos refer to real subjects, but acquisitions/prices/currency amounts are fictional, with no sale, title transfer or endorsement.

Practice games use additional tables. Old classic game records remain untouched. Table outcomes can lose; the separate demo refund and 100-unit grant do not alter them. Unlimited wallet amounts cannot be withdrawn. Currency changes only symbols/formatting, not stored numbers or exchange rates.

## Rollback
The updater prints a precise command of the form:

```fish
fish /opt/dopamine-backups/ACTUAL-TIMESTAMP/rollback.fish
```

Use the actual printed path, not the placeholder. It checks the saved .env hash and exact retained image, restores source and uses a Compose override for that old image, recreating ONLY web on the same live volume. It does NOT replace the live database with an older snapshot. This avoids erasing new users/purchases/rounds. Old versions cannot display new interactive games or model photos, but their records remain stored and reappear after re-upgrade. Unknown post-update source/.env edits stop rollback rather than being overwritten.

Automatic rollback is ATTEMPTED after a failed source/container switch, not guaranteed against disk failure, Docker failure or concurrent manual changes. A failure before the switch leaves the original app running. Snapshot restoration is a separate deliberate disaster-recovery action; stop writers and retain the newest data first. Private backups contain credentials and user records and are not encrypted; protect them and apply an intentional retention policy. No automated backup deletion is added.

## Remaining production validation
Actual Docker/Fish/Gunicorn execution, full real photograph downloads and visual/copyright review, production browser TLS/cookie flows, current dependency/image CVE scans, load testing and independent penetration testing were not completed in the authoring environment. The patch gates deployment on its actual build/test/photo checks but cannot substitute for those additional production reviews.
