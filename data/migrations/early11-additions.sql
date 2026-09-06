CREATE TABLE IF NOT EXISTS extra_rounds (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 game TEXT NOT NULL CHECK(game IN ('dice','blackjack','baccarat','bingo','keno','plinko','treasure')),
 request_key TEXT NOT NULL,
 stake INTEGER NOT NULL CHECK(stake IN (100,500,1000)),
 bonus INTEGER NOT NULL CHECK(bonus=100),
 created_at INTEGER NOT NULL,
 result_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(user_id, request_key)
);
CREATE INDEX IF NOT EXISTS extra_rounds_user_time ON extra_rounds(user_id, created_at DESC);
CREATE VIEW IF NOT EXISTS all_rounds AS
 SELECT id,user_id,game,request_key,stake,bonus,created_at,result_json FROM rounds
 UNION ALL
 SELECT id,user_id,game,request_key,stake,bonus,created_at,result_json FROM extra_rounds;
CREATE TABLE IF NOT EXISTS schema_features (name TEXT PRIMARY KEY, revision INTEGER NOT NULL);
INSERT INTO schema_features(name,revision) VALUES('expanded_games',1) ON CONFLICT(name) DO NOTHING;
-- Core schema stays compatible with 1.0; additions above do not change its tables' semantics.
-- Preserve early 1.1 core user_version=2 for reversible additive migration.

-- 1.2 practice tables are additive: old records and their semantics are retained.
CREATE TABLE IF NOT EXISTS interactive_rounds (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 game TEXT NOT NULL CHECK(game IN ('roulette','blackjack','baccarat','slots','dice','keno','plinko')),
 request_key TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
 completed INTEGER NOT NULL CHECK(completed IN (0,1)),
 state_json TEXT NOT NULL,
 created_at INTEGER NOT NULL,
 UNIQUE(user_id,request_key)
);
CREATE INDEX IF NOT EXISTS interactive_user_time ON interactive_rounds(user_id,created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS interactive_active ON interactive_rounds(user_id,game) WHERE completed=0;
CREATE TABLE IF NOT EXISTS interactive_actions (
 round_id TEXT NOT NULL REFERENCES interactive_rounds(id) ON DELETE CASCADE,
 request_key TEXT NOT NULL,
 PRIMARY KEY(round_id,request_key)
);
INSERT INTO schema_features(name,revision) VALUES('interactive_tables',1) ON CONFLICT(name) DO NOTHING;

INSERT INTO schema_features(name,revision) VALUES('early11_bridge',1) ON CONFLICT(name) DO NOTHING;
