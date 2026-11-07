"""What every provider's sign-in has in common.

These take their connections by hand: none may stay held while waiting for a provider, or a slow
provider would use up the pool and stop the whole API.
"""

import logging

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from ma_api import account, attach, flow, ratelimit, sessions
from ma_api.db import Database
from ma_api.errors import ApiError
from ma_api.owner import Owner
from ma_api.settings import Settings

log = logging.getLogger("ma_api")


def count_attempt(request: Request, settings: Settings) -> None:
    database: Database = request.app.state.database
    with database.transaction() as connection:
        ratelimit.limit_auth(connection, request, settings)


def begin(
    request: Request, settings: Settings, flow_name: str, return_to: str
) -> tuple[Response, flow.Flow]:
    """A redirect whose destination the provider's module fills in, and the flow it opened."""
    count_attempt(request, settings)
    target = flow.safe_return_to(return_to)
    if target is None:
        fields = [{"field": "query.return_to", "rule": "relative_path"}]
        raise ApiError(400, "invalid_request", {"fields": fields})
    response = RedirectResponse("", status_code=303)
    return response, flow.start(response, settings, flow_name, target)


def failure(settings: Settings, flow_name: str, code: str) -> Response:
    response = RedirectResponse(f"{settings.site_url}/?auth_error={code}", status_code=303)
    flow.finish(response, settings, flow_name)
    return response


def complete(
    request: Request,
    settings: Settings,
    flow_name: str,
    started: flow.Flow,
    provider: str,
    account_id: str,
    display_name: str | None,
) -> Response:
    """The provider has proven this account: sign in or link, then bring the matches along."""
    response = RedirectResponse(f"{settings.site_url}{started.return_to}", status_code=303)
    flow.finish(response, settings, flow_name)
    database: Database = request.app.state.database
    with database.transaction() as connection:
        owner = sessions.identify(connection, settings, request.cookies).owner
        current_user = None if owner is None else owner.user_id
        try:
            user = account.sign_in(connection, provider, account_id, display_name, current_user)
        except account.AccountAlreadyLinkedError:
            log.info("sign-in refused: account_already_linked")
            return failure(settings, flow_name, "account_already_linked")
        anonymous = sessions.anonymous_session_of(connection, settings, request.cookies)
        if anonymous is not None:
            attach.attach_anonymous(connection, anonymous, user)
            sessions.clear_anonymous_cookie(response, settings)
        attach.apply_claims(connection, Owner(user_id=user))
        attach.refresh_verification(connection, user)
        if current_user is None:
            sessions.open_user_session(connection, settings, user, response)
    return response
