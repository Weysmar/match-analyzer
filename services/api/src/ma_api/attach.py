"""What signing in does to a player's matches."""

import uuid

from ma_api.account import DEFAULT_DISPLAY_NAME
from ma_api.db import Connection


def attach_anonymous(connection: Connection, session: uuid.UUID, user: uuid.UUID) -> None:
    """Hands an anonymous session's matches, uploads and memorized players over to a user, then
    ends the session. All its matches come along, verified or not (D5)."""
    # A match the user already has: their link stays, and takes the identity they chose here if it
    # holds none. An anonymous link is never verified, so this cannot verify anything.
    connection.execute(
        """
        UPDATE user_matches mine
        SET match_player_id = theirs.match_player_id, identity_source = theirs.identity_source
        FROM user_matches theirs
        WHERE mine.user_id = %s
            AND theirs.anonymous_session_id = %s
            AND theirs.match_id = mine.match_id
            AND mine.identity_source = 'none'
            AND theirs.identity_source <> 'none'
        """,
        (user, session),
    )
    connection.execute(
        """
        DELETE FROM user_matches theirs
        USING user_matches mine
        WHERE theirs.anonymous_session_id = %s
            AND mine.user_id = %s
            AND mine.match_id = theirs.match_id
        """,
        (session, user),
    )
    connection.execute(
        "UPDATE user_matches SET user_id = %s, anonymous_session_id = NULL "
        "WHERE anonymous_session_id = %s",
        (user, session),
    )
    connection.execute(
        "UPDATE uploads SET user_id = %s, anonymous_session_id = NULL "
        "WHERE anonymous_session_id = %s",
        (user, session),
    )
    connection.execute(
        "INSERT INTO player_claims (user_id, platform, platform_id) "
        "SELECT %s, platform, platform_id FROM player_claims WHERE anonymous_session_id = %s "
        "ON CONFLICT DO NOTHING",
        (user, session),
    )
    connection.execute("DELETE FROM anonymous_sessions WHERE id = %s", (session,))


def refresh_verification(connection: Connection, user: uuid.UUID) -> None:
    """Applies the database's rule, then names an account that still has no name: Steam gives none,
    but a verified replay holds the player's own. A name hidden in the game is not taken."""
    connection.execute("SELECT refresh_verification(%s)", (user,))
    connection.execute(
        """
        UPDATE users
        SET display_name = latest.display_name
        FROM (
            SELECT player.display_name
            FROM user_matches link
            JOIN match_players player ON player.id = link.match_player_id
            JOIN matches match ON match.id = link.match_id
            WHERE link.user_id = %(user)s AND link.verified AND NOT player.anonymized
            ORDER BY match.played_at DESC NULLS LAST
            LIMIT 1
        ) latest
        WHERE users.id = %(user)s AND users.display_name = %(default)s
        """,
        {"user": user, "default": DEFAULT_DISPLAY_NAME},
    )
