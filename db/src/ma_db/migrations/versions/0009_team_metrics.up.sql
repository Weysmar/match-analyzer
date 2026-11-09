-- A metric of a team rather than of a player, like its share of possession. Same shape as
-- player_match_metrics, keyed by match and team: a team is no row of match_players.
CREATE TABLE team_match_metrics (
    match_id         uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    team             smallint NOT NULL CHECK (team IN (0, 1)),
    metric_id        text NOT NULL,
    -- Null when undefined, like the possession of a match without detected touches.
    value            double precision,
    analysis_version text NOT NULL,
    computed_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team, metric_id)
);
CREATE INDEX team_match_metrics_version ON team_match_metrics (analysis_version);

GRANT SELECT ON team_match_metrics TO ma_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON team_match_metrics TO ma_worker;
