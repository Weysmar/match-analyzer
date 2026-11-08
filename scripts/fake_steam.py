"""A stand-in for Steam's OpenID provider, for end-to-end tests only (A70). It signs everyone in as
one made-up account, at once, and confirms every answer it is asked about. The API only talks to it
when `STEAM_OPENID_URL` points here, which production refuses.

The SteamID64 sits below the first individual account (76561197960265728): no real player has it.

Usage: `python scripts/fake_steam.py [port]`, by `scripts/e2e.sh`.
"""

import secrets
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPENID_NS = "http://specs.openid.net/auth/2.0"
STEAM_ID = "76561190000000001"
IDENTITY = f"https://steamcommunity.com/openid/id/{STEAM_ID}"
PATH = "/openid/login"


class Provider(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        if url.path != PATH or query.get("openid.mode") != "checkid_setup":
            self.send_error(404)
            return
        endpoint = f"http://{self.headers['Host']}{PATH}"
        answer = {
            "openid.ns": OPENID_NS,
            "openid.mode": "id_res",
            "openid.op_endpoint": endpoint,
            "openid.claimed_id": IDENTITY,
            "openid.identity": IDENTITY,
            "openid.return_to": query.get("openid.return_to", ""),
            "openid.response_nonce": f"2026-01-01T00:00:00Z{secrets.token_hex(8)}",
            "openid.assoc_handle": "fake",
            "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,"
            "assoc_handle",
            "openid.sig": "fake",
        }
        return_to = answer["openid.return_to"]
        separator = "&" if "?" in return_to else "?"
        self.send_response(302)
        self.send_header("Location", f"{return_to}{separator}{urllib.parse.urlencode(answer)}")
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
        valid = form.get("openid.mode") == "check_authentication"
        body = f"ns:{OPENID_NS}\nis_valid:{'true' if valid else 'false'}\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Quiet: the requests carry nothing worth a line."""


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    ThreadingHTTPServer(("127.0.0.1", port), Provider).serve_forever()


if __name__ == "__main__":
    main()
