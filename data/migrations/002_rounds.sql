-- v1 -> v2: preserve original round IDs, keys, amounts and timestamps.
-- Transaction boundaries are owned by app.db.initialize.
DROP INDEX IF EXISTS rounds_user_time;
ALTER TABLE rounds RENAME TO rounds_v1;
CREATE TABLE IF NOT EXISTS rounds (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 game TEXT NOT NULL CHECK(game IN ('prism','orbit','cards','dice','roulette','blackjack','baccarat','keno','plinko')),
 request_key TEXT NOT NULL,
 stake INTEGER NOT NULL CHECK(stake IN (100,500,1000)),
 bonus INTEGER NOT NULL CHECK(bonus=100),
 result_json TEXT NOT NULL DEFAULT '{}',
 created_at INTEGER NOT NULL,
 UNIQUE(user_id, request_key)
);
INSERT INTO rounds(id,user_id,game,request_key,stake,bonus,created_at)
SELECT id,user_id,game,request_key,stake,bonus,created_at FROM rounds_v1;
DROP TABLE rounds_v1;
CREATE INDEX rounds_user_time ON rounds(user_id,created_at DESC);
PRAGMA user_version=2;
