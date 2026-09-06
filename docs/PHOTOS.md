# Model-specific photographs — v1.2

The previous 32 reused category illustrations are no longer publication inputs. `data/catalog.json` contains 1,056 DISTINCT CANDIDATES, not a preverified live inventory. Build-time `app/real_photos.py` creates `data/catalog-live.json` only after >=513 and <=640 candidates pass source, identity, licensing, image decode and duplicate checks. Categories are interleaved to avoid starving smaller categories. Candidates without a suitable source are excluded rather than mislabeled.

Evidence includes exact article title and revision, Wikidata subject ID, Commons lead-image filename, model tokens in the file description/name, per-file license/author, source checksum, optimized-byte/pixel SHA-256 and dHash. Exact model IDs, source files/hashes and optimized hashes may not repeat. dHash distance <=5 is rejected; this conservative heuristic can produce false positives and does not prove all conceivable near-duplicates are impossible. No automated metadata system guarantees correct visual identity. Review accepted photos through their source links; nothing in this release is a human visual certification.

Sources: HTTPS en.wikipedia.org and commons.wikimedia.org metadata APIs; HTTPS upload.wikimedia.org/thumb.wikimedia.org raster assets only. Redirects outside this scope, oversized replies, tiny/huge/animated/non-raster images and unsuitable licenses are rejected. Images are at most 960 px WebP and served locally. The old importer remains only for legacy regression coverage, not the production photo command.

License metadata may allow CC BY, CC BY-SA, CC0 or public-domain content. The original license is retained; source links, author, credit and processing notice are displayed. Original file metadata is removed from the optimized raster while provenance stays in a separate record. Refreshing cached downloads still refreshes rights metadata. Unknown attribution is never invented. Artwork/building/brand or personality rights may be independent of a photograph's license. This is not a rights warranty.

Wikimedia Commons explicitly states that per-file requirements differ and copyright/metadata correctness is not guaranteed. Sources consulted 2026-09-06:
- https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia
- https://www.mediawiki.org/wiki/API:Imageinfo
- https://www.mediawiki.org/wiki/Extension:PageImages
- https://www.mediawiki.org/wiki/API:Etiquette

Example identity metadata inspected externally: Wikipedia's free lead-image API identifies Nikon D850 (article 54656273, Q37933342, file 20171009_D850_front.jpg) and Porsche 911 (article 48345830, Q219357). This is metadata evidence only; it is NOT evidence that these photographs were downloaded or visually reviewed in the authoring runtime.

The source archive contains ZERO production photo binaries. Network/DNS prevented fetching them here. The VPS build must retrieve and verify a complete publication before the updater touches the running application. If it cannot, keep the old deployment; never use generated or category placeholders to obtain a false pass.

## Early-1.1 bridge publication floor
The configured floor for 1.2.1 is 513, exceeding the old 512 fictional listings. No import was executed in this session.
