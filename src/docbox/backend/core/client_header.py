"""The header that marks a state-changing request as coming from DocBox's own client.

Browsers attach Origin to every cross-site POST but can't add a custom header without a
CORS preflight, which the backend fails for any origin it doesn't allow. So `main.py`
refuses unsafe requests that come from another website (an Origin that isn't the
backend's own) unless they carry this header. The frontend (`frontend/src/lib/api.ts`)
and `RemoteEngine` send it.
"""

CLIENT_HEADER = "X-DocBox-Client"
