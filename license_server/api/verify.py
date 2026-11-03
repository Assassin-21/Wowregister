"""Vercel license verifier. All storage credentials stay in server environment."""
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler
import json
import os
import re
from urllib import request


class Denied(Exception):
    pass


class Unavailable(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def json_request(url, headers, data=None):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    req = request.Request(url, data=payload, headers={**headers, "Content-Type": "application/json"})
    with request.build_opener(NoRedirect()).open(req, timeout=6) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise Unavailable()
        return json.loads(raw)


def key_hash(card, pepper):
    return hmac.new(pepper.encode("utf-8"), card.encode("ascii"), hashlib.sha256).hexdigest()


def authorize(payload, read_record=None, now=None):
    if not isinstance(payload, dict):
        raise Denied()
    card, machine = payload.get("license_key"), payload.get("device_id")
    if (not isinstance(card, str) or not re.fullmatch(r"WA-[A-F0-9]{32}", card)
            or not isinstance(machine, str) or not re.fullmatch(r"[a-f0-9]{64}", machine)):
        raise Denied()
    pepper = os.environ.get("LICENSE_PEPPER", "")
    if len(pepper) < 32:
        raise Unavailable()
    digest = key_hash(card, pepper)
    if read_record is None:
        bin_id = os.environ.get("JSONBIN_BIN_ID", "")
        access = os.environ.get("JSONBIN_ACCESS_KEY", "")
        if not re.fullmatch(r"[a-fA-F0-9]{24}", bin_id) or not access:
            raise Unavailable()
        read_record = lambda: json_request(f"https://api.jsonbin.io/v3/b/{bin_id}/latest",
                                          {"X-Access-Key": access, "X-Bin-Meta": "false"})
    record = read_record()
    if not isinstance(record, dict) or record.get("schema_version") != 1 or not isinstance(record.get("licenses"), dict):
        raise Unavailable()
    license = record["licenses"].get(digest)
    if not isinstance(license, dict) or license.get("enabled") is not True:
        raise Denied()
    expires = license.get("expires_at")
    if expires is not None:
        try:
            deadline = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if deadline.tzinfo is None or deadline <= (now or datetime.now(timezone.utc)):
                raise Denied()
        except (ValueError, TypeError, AttributeError):
            raise Denied() from None
    bound = license.get("device_id")
    if not isinstance(bound, str) or not re.fullmatch(r"[a-f0-9]{64}", bound) or not hmac.compare_digest(bound, machine):
        raise Denied()  # Read-only, prebound records: clients can never claim or alter a binding.
    return {"ok": True, "device_id": machine, "recheck_after": 45}


class handler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Health endpoint deliberately does not reveal credentials, cards or storage details.
        self.reply(200, {"service": "wowregister-license", "status": "online"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 2048 or self.headers.get_content_type() != "application/json":
                self.reply(400, {"ok": False, "code": "invalid_request"})
                return
            payload = json.loads(self.rfile.read(length))
            self.reply(200, authorize(payload))
        except (Denied, UnicodeError):
            self.reply(403, {"ok": False, "code": "license_denied"})
        except (ValueError, TypeError):
            self.reply(400, {"ok": False, "code": "invalid_request"})
        except Exception:
            # Never return upstream errors: they can include headers or storage details.
            self.reply(503, {"ok": False, "code": "temporarily_unavailable"})

    def log_message(self, format, *args):
        pass  # No request payload / card logging.
