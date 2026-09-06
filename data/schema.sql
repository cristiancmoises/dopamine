CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY,
 nickname TEXT NOT NULL,
 nickname_key TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL,
 recovery_hash TEXT NOT NULL,
 display_name TEXT NOT NULL DEFAULT '',
 bio TEXT NOT NULL DEFAULT '',
 country TEXT NOT NULL DEFAULT '',
 language TEXT NOT NULL DEFAULT 'pt-br' CHECK(language IN ('pt-br','en','zh','ja')),
 reduced_motion INTEGER NOT NULL DEFAULT 0 CHECK(reduced_motion IN (0,1)),
 casino_hidden INTEGER NOT NULL DEFAULT 0 CHECK(casino_hidden IN (0,1)),
 excluded_until INTEGER NOT NULL DEFAULT 0,
 adult_confirmed INTEGER NOT NULL CHECK(adult_confirmed=1),
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY,
 csrf TEXT NOT NULL,
 user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
 created_at INTEGER NOT NULL,
 touched_at INTEGER NOT NULL,
 expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS purchases (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_key TEXT NOT NULL,
 created_at INTEGER NOT NULL,
 UNIQUE(user_id, request_key)
);
CREATE INDEX IF NOT EXISTS purchase_user_time ON purchases(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS purchase_items (
 id INTEGER PRIMARY KEY,
 purchase_id TEXT NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
 product_id TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99),
 unit_credits INTEGER NOT NULL CHECK(unit_credits > 0)
);
CREATE INDEX IF NOT EXISTS items_purchase ON purchase_items(purchase_id);
CREATE TABLE IF NOT EXISTS cart (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 product_id TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99),
 PRIMARY KEY (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS favorites (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 product_id TEXT NOT NULL,
 PRIMARY KEY(user_id, product_id)
);
CREATE TABLE IF NOT EXISTS rounds (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 game TEXT NOT NULL CHECK(game IN ('prism','orbit','cards')),
 request_key TEXT NOT NULL,
 stake INTEGER NOT NULL CHECK(stake IN (100,500,1000)),
 bonus INTEGER NOT NULL CHECK(bonus=100),
 created_at INTEGER NOT NULL,
 result_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(user_id, request_key)
);
CREATE INDEX IF NOT EXISTS rounds_user_time ON rounds(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS rate_limits (
 key TEXT PRIMARY KEY,
 count INTEGER NOT NULL,
 expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_expiry ON rate_limits(expires_at);
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
PRAGMA user_version = 1;

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
