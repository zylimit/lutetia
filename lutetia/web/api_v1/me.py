"""/api/v1/me: who the credential in this request is. The project dashboard asks it before showing any page (401 -> sign-in)."""
from aiohttp import web

from ..auth import require_api
from ..callers import API_CALLER
from .envelope import data_response, errors_as_responses, now_utc

SESSION_PREFIX = "session:"


@require_api(None)  # any valid key or session, whatever its scopes: the answer is only the name it was issued to
@errors_as_responses
async def me(request: web.Request) -> web.Response:
    caller = request[API_CALLER]
    account = caller if "Authorization" in request.headers else caller[len(SESSION_PREFIX):]  # key: caller name; session: account name
    return data_response({"account": account}, now_utc())
