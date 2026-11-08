-- The game clock, in seconds of play (A63). `time_s` counts the replay's own time, countdowns and
-- celebrations included: a timeline of the match needs the clock instead. Written by the analysis,
-- NULL until it runs and for a match read from its header only.
ALTER TABLE matches
    ADD COLUMN game_length_s real CHECK (game_length_s >= 0),
    ADD COLUMN overtime_from_s real CHECK (overtime_from_s >= 0);
ALTER TABLE match_events
    ADD COLUMN game_time_s real CHECK (game_time_s >= 0);
