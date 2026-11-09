-- Where the analysis stored the match's 2D view (`views/<match_id>.json.gz`): NULL before it
-- runs, for a match read from its header only, and while a new parse waits for its analysis.
ALTER TABLE matches ADD COLUMN view_key text;
