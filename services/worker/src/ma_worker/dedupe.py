"""Recognizes one match brought by several players: the second level of deduplication, the first
being the file's hash.

Measured on the corpus, a good third of replays have a `MatchGUID`. Without one, the date stands in.
With neither, or with no player in the header, nothing tells two matches apart: two 0-0 replays with
no players would look the same. Such a file then only ever matches itself.
"""

import hashlib
import json

from ma_schemas import HeaderDocument


def dedupe_key(header: HeaderDocument, file_sha256: str) -> str:
    """The players and the score count alongside the `MatchGUID` (I10): otherwise, a forged file
    with someone's identifier would be taken for their match."""
    anchor = header["match_guid"] or header["played_at"]
    players = sorted(
        # An old replay holds no id for Epic players: their name is all there is.
        [player["platform"], player["platform_id"] or player["name"], player["team"] or 0]
        for player in header["players"]
    )
    if anchor is None or not players:
        content: object = {"file": file_sha256}
    else:
        content = {
            "anchor": anchor,
            "players": players,
            "score": [header["score"]["blue"], header["score"]["orange"]],
        }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
