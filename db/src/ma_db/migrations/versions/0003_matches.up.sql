CREATE TABLE matches (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game                text NOT NULL DEFAULT 'rocket_league',
    dedupe_key          char(64) NOT NULL UNIQUE,
    match_guid          text,
    status              text NOT NULL DEFAULT 'pending' CHECK (status IN
                        ('pending', 'parsing', 'header_only', 'parsed', 'analyzing', 'ready', 'failed')),
    game_build          text,
    build_id            bigint,
    changelist          bigint,
    replay_major        integer,
    replay_minor        integer,
    replay_net          integer,
    map                 text,
    played_at           timestamptz,
    played_at_source    text CHECK (played_at_source IN ('epoch', 'date_without_timezone')),
    duration_s          real,
    match_type          text,
    playlist            text,
    team_size           smallint,
    score_blue          smallint,
    score_orange        smallint,
    -- A car left the standard arena in live play: the metrics should not be trusted.
    arena_out_of_bounds boolean NOT NULL DEFAULT false,
    raw_key             text,
    raw_deleted_at      timestamptz,
    frames_key          text,
    events_key          text,
    parser_version      text NOT NULL,
    analysis_version    text,
    error_code          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    parsed_at           timestamptz,
    analyzed_at         timestamptz
);
CREATE INDEX matches_build ON matches (game_build, status);
CREATE INDEX matches_parser_version ON matches (parser_version);
CREATE INDEX matches_analysis_version ON matches (analysis_version);
CREATE INDEX matches_raw_retention ON matches (status, parsed_at) WHERE raw_deleted_at IS NULL;

-- Every distinct file known for a match (first level of deduplication).
CREATE TABLE match_files (
    sha256      char(64) PRIMARY KEY,
    match_id    uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX match_files_match ON match_files (match_id);

-- Includes third parties: platform_id is never returned by the API. display_name is the anonymized
-- name of a player who asked for anonymity in the game.
CREATE TABLE match_players (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id     uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    -- player_idx in frames.parquet; null when header_only.
    frames_idx   smallint,
    platform     text NOT NULL
                 CHECK (platform IN ('steam', 'epic', 'psn', 'xbox', 'switch', 'bot', 'unknown')),
    -- Null for bots and when the replay does not carry it.
    platform_id  text,
    display_name text NOT NULL,
    team         smallint NOT NULL CHECK (team IN (0, 1)),
    score        integer,
    goals        smallint,
    assists      smallint,
    saves        smallint,
    shots        smallint,
    is_bot       boolean NOT NULL DEFAULT false,
    anonymized   boolean NOT NULL DEFAULT false,
    UNIQUE (match_id, frames_idx),
    -- Lets other tables state that a player belongs to the match they name.
    UNIQUE (match_id, id)
);
CREATE INDEX match_players_identity ON match_players (platform, platform_id)
    WHERE platform_id IS NOT NULL;

CREATE TABLE match_events (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id         uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN ('goal', 'demolition')),
    frame            integer NOT NULL,
    time_s           real NOT NULL,
    team             smallint CHECK (team IN (0, 1)),
    actor_player_id  bigint,
    victim_player_id bigint,
    FOREIGN KEY (match_id, actor_player_id) REFERENCES match_players (match_id, id)
        ON DELETE SET NULL (actor_player_id),
    FOREIGN KEY (match_id, victim_player_id) REFERENCES match_players (match_id, id)
        ON DELETE SET NULL (victim_player_id)
);
CREATE INDEX match_events_match ON match_events (match_id, time_s);

GRANT SELECT ON matches, match_players, match_events TO ma_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON matches, match_files, match_players, match_events
    TO ma_worker;
