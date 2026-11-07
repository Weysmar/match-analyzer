CREATE TABLE users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name text NOT NULL,
    locale       text NOT NULL DEFAULT 'fr' CHECK (locale IN ('fr', 'en')),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE linked_accounts (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    provider            text NOT NULL CHECK (provider IN ('steam', 'epic')),
    provider_account_id text NOT NULL,
    display_name        text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_account_id),
    UNIQUE (user_id, provider)
);

CREATE TABLE auth_sessions (
    token_hash bytea PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX auth_sessions_user ON auth_sessions (user_id);
CREATE INDEX auth_sessions_expiry ON auth_sessions (expires_at);

CREATE TABLE anonymous_sessions (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX anonymous_sessions_expiry ON anonymous_sessions (expires_at);

-- "Which of these players are you?", remembered. A claim never proves anything.
CREATE TABLE player_claims (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              uuid REFERENCES users (id) ON DELETE CASCADE,
    anonymous_session_id uuid REFERENCES anonymous_sessions (id) ON DELETE CASCADE,
    platform             text NOT NULL
                         CHECK (platform IN ('steam', 'epic', 'psn', 'xbox', 'switch')),
    platform_id          text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(user_id, anonymous_session_id) = 1)
);
CREATE UNIQUE INDEX player_claims_user ON player_claims (user_id, platform, platform_id)
    WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX player_claims_anon ON player_claims (anonymous_session_id, platform, platform_id)
    WHERE anonymous_session_id IS NOT NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON users, linked_accounts, auth_sessions, anonymous_sessions,
    player_claims TO ma_api;
GRANT SELECT ON users, linked_accounts, player_claims TO ma_worker;
-- The worker purges expired sessions.
GRANT SELECT, DELETE ON auth_sessions, anonymous_sessions TO ma_worker;
