CREATE TABLE player_match_metrics (
    match_player_id  bigint NOT NULL REFERENCES match_players (id) ON DELETE CASCADE,
    metric_id        text NOT NULL,
    -- Null when undefined, like the last back of a 1v1.
    value            double precision,
    analysis_version text NOT NULL,
    computed_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_player_id, metric_id)
);
CREATE INDEX player_match_metrics_version ON player_match_metrics (analysis_version);

-- Claimed with SELECT ... FOR UPDATE SKIP LOCKED: no Redis in V1.
CREATE TABLE jobs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind         text NOT NULL CHECK (kind IN ('parse', 'reparse', 'analyze', 'gc_match')),
    payload      jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'done', 'dead')),
    priority     smallint NOT NULL DEFAULT 0,
    attempts     smallint NOT NULL DEFAULT 0,
    max_attempts smallint NOT NULL DEFAULT 3,
    run_at       timestamptz NOT NULL DEFAULT now(),
    locked_by    text,
    locked_at    timestamptz,
    last_error   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);
CREATE INDEX jobs_ready ON jobs (priority DESC, run_at) WHERE status = 'queued';
CREATE INDEX jobs_running ON jobs (locked_at) WHERE status = 'running';

CREATE TABLE rate_limit_buckets (
    bucket_key   text NOT NULL,
    window_start timestamptz NOT NULL,
    hits         integer NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_key, window_start)
);
CREATE INDEX rate_limit_buckets_window ON rate_limit_buckets (window_start);

GRANT SELECT ON player_match_metrics TO ma_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON player_match_metrics TO ma_worker;
-- The API only enqueues: it cannot read or change what the worker does.
GRANT INSERT ON jobs TO ma_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON jobs TO ma_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON rate_limit_buckets TO ma_api;
GRANT SELECT, DELETE ON rate_limit_buckets TO ma_worker;
