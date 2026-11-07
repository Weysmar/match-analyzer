-- Applies an owner's memorized players to their matches without an identity, for the API when a
-- player is chosen and for the worker when a match arrives. Pass the user or the anonymous session,
-- and NULL for the other. A memorized identity never verifies a match: only refresh_verification()
-- does, from a proof.
CREATE FUNCTION apply_player_claims(p_user uuid, p_session uuid) RETURNS void
LANGUAGE sql AS $$
    UPDATE user_matches link
    SET match_player_id = found.player_id, identity_source = 'memorized'
    FROM (
        SELECT link.id, min(player.id) AS player_id
        FROM user_matches link
        JOIN match_players player ON player.match_id = link.match_id
        JOIN player_claims claim
            ON claim.platform = player.platform
            AND claim.platform_id = player.platform_id
            AND (claim.user_id = p_user OR claim.anonymous_session_id = p_session)
        WHERE link.identity_source = 'none'
            AND (link.user_id = p_user OR link.anonymous_session_id = p_session)
        GROUP BY link.id
    ) found
    WHERE link.id = found.id;
$$;

REVOKE ALL ON FUNCTION apply_player_claims(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION apply_player_claims(uuid, uuid) TO ma_api, ma_worker;
