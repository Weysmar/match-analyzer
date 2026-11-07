"""Links an owner to a match, and works out who they are in it. Both rules live in the database,
shared with the API: a memorized player identifies, and only a linked account verifies."""

import uuid

from ma_worker.queue import Connection


def link(
    connection: Connection,
    match_id: uuid.UUID,
    user_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> None:
    connection.execute(
        "INSERT INTO user_matches (user_id, anonymous_session_id, match_id) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (user_id, session_id, match_id),
    )
    connection.execute("SELECT apply_player_claims(%s, %s)", (user_id, session_id))
    if user_id is not None:
        connection.execute("SELECT refresh_verification(%s)", (user_id,))
