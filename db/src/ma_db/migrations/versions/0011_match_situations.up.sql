-- Ids and facts only, never a name: players are match_players.id. Written by the analysis, over
-- the previous run's; read by the match sheet (step 16). `turnover` comes in with possession,
-- before annex F's list; `double_commit`, `overcommit` and `goal_context` with steps 14 and 15.
CREATE TABLE match_situations (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id         uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    kind             text NOT NULL CHECK (kind IN
                     ('turnover', 'kickoff', 'fifty_fifty', 'double_commit', 'overcommit',
                      'goal_context')),
    time_s           double precision NOT NULL CHECK (time_s >= 0),
    game_time_s      double precision CHECK (game_time_s >= 0),
    team             smallint CHECK (team IN (0, 1)),
    player_ids       bigint[] NOT NULL DEFAULT '{}',
    tags             text[] NOT NULL DEFAULT '{}',
    details          jsonb NOT NULL DEFAULT '{}',
    analysis_version text NOT NULL
);
CREATE INDEX match_situations_match ON match_situations (match_id, time_s);

GRANT SELECT ON match_situations TO ma_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON match_situations TO ma_worker;
