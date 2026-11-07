-- The one rule deciding whether a match is verified, in one place for the API and the worker, which
-- share no code. A user's match is verified if and only if one of its players carries a platform id
-- of one of the user's linked accounts. That player is then who the user is in this match, whoever
-- they claimed to be: the proof wins over a claim.
CREATE FUNCTION refresh_verification(p_user uuid) RETURNS void
LANGUAGE sql AS $$
    WITH proven AS (
        SELECT link.id, min(player.id) AS player_id
        FROM user_matches link
        JOIN match_players player ON player.match_id = link.match_id
        JOIN linked_accounts account
            ON account.user_id = link.user_id
            AND account.provider = player.platform
            AND account.provider_account_id = player.platform_id
        WHERE link.user_id = p_user
        GROUP BY link.id
    ), gained AS (
        UPDATE user_matches link
        SET match_player_id = proven.player_id, identity_source = 'linked_account', verified = true
        FROM proven
        WHERE link.id = proven.id
    )
    -- Proof lost, when a reprocessed replay no longer holds that id. A claim is left alone.
    UPDATE user_matches link
    SET match_player_id = NULL, identity_source = 'none', verified = false
    WHERE link.user_id = p_user
        AND link.identity_source = 'linked_account'
        AND NOT EXISTS (SELECT FROM proven WHERE proven.id = link.id);
$$;

REVOKE ALL ON FUNCTION refresh_verification(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION refresh_verification(uuid) TO ma_api, ma_worker;
