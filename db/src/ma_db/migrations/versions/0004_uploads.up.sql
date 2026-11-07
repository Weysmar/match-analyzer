CREATE TABLE uploads (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid REFERENCES users (id) ON DELETE CASCADE,
    anonymous_session_id uuid REFERENCES anonymous_sessions (id) ON DELETE CASCADE,
    file_name            text NOT NULL,
    declared_size        bigint NOT NULL CHECK (declared_size > 0),
    -- Given by the browser: only ever compared within the same owner's uploads.
    declared_sha256      char(64),
    -- Computed by the worker: the only hash that counts.
    sha256               char(64),
    status               text NOT NULL DEFAULT 'awaiting_file' CHECK (status IN
                         ('awaiting_file', 'uploaded', 'processing', 'done', 'duplicate',
                          'rejected', 'failed')),
    rejection            text CHECK (rejection IN
                         ('not_a_replay', 'corrupt', 'too_large', 'size_mismatch')),
    incoming_key         text NOT NULL,
    match_id             uuid REFERENCES matches (id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    completed_at         timestamptz,
    CHECK (num_nonnulls(user_id, anonymous_session_id) = 1),
    CHECK ((status = 'rejected') = (rejection IS NOT NULL))
);
CREATE INDEX uploads_user ON uploads (user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX uploads_anon ON uploads (anonymous_session_id, created_at DESC)
    WHERE anonymous_session_id IS NOT NULL;
CREATE INDEX uploads_stale ON uploads (created_at) WHERE status = 'awaiting_file';
CREATE INDEX uploads_match ON uploads (match_id) WHERE match_id IS NOT NULL;

CREATE TABLE user_matches (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              uuid REFERENCES users (id) ON DELETE CASCADE,
    anonymous_session_id uuid REFERENCES anonymous_sessions (id) ON DELETE CASCADE,
    match_id             uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    match_player_id      bigint,
    identity_source      text NOT NULL DEFAULT 'none' CHECK (identity_source IN
                         ('none', 'linked_account', 'claimed', 'memorized')),
    verified             boolean NOT NULL DEFAULT false,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(user_id, anonymous_session_id) = 1),
    -- A claimed or memorized identity never verifies a match.
    CHECK (NOT verified OR identity_source = 'linked_account'),
    CHECK ((identity_source = 'none') = (match_player_id IS NULL)),
    -- The chosen player has to be a player of this match.
    FOREIGN KEY (match_id, match_player_id) REFERENCES match_players (match_id, id)
);
CREATE UNIQUE INDEX user_matches_user ON user_matches (user_id, match_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX user_matches_anon ON user_matches (anonymous_session_id, match_id)
    WHERE anonymous_session_id IS NOT NULL;
CREATE INDEX user_matches_match ON user_matches (match_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON uploads, user_matches TO ma_api;
GRANT SELECT, UPDATE, DELETE ON uploads TO ma_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_matches TO ma_worker;
