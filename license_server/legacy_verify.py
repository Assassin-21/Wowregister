"""Legacy prebound reference and offline HMAC helper; production uses api/verify.js."""
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler
import json
import os
import re
from urllib import request, error


class Denied(Exception):
    pass


class Unavailable(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def json_request(url, headers, data=None):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    req = request.Request(url, data=payload, headers={"User-Agent": "Wowregister-License/0.3",
                                                    "Accept": "application/json", **headers,
                                                    "Content-Type": "application/json"})
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=6) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise Unavailable("storage_response_too_large")
            return json.loads(raw)
    except error.HTTPError as exc:
        # Classify provider errors without recording keys, headers, response bodies or card data.
        try:
            message = str(json.loads(exc.read(2048)).get("message", "")).lower()
        except (ValueError, AttributeError):
            message = ""
        reason = ("invalid_master_key" if "invalid" in message and "master" in message else
                  "invalid_access_key" if "invalid" in message and "access" in message else
                  "permission_denied" if "permission" in message else
                  "quota_or_rate_limit" if any(word in message for word in ("quota", "limit", "credit")) else "unknown")
        details = {"event": "jsonbin_provider_error", "status": exc.code, "reason": reason,
                   "content_type": exc.headers.get_content_type()}
        if re.fullmatch(r"[a-z0-9 _.,:'-]{1,180}", message):
            details["provider_message"] = message
        print(json.dumps(details), flush=True)
        raise Unavailable(f"jsonbin_http_{exc.code}") from None


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
        bin_id = os.environ.get("JSONBIN_BIN_ID", "").strip()
        access = os.environ.get("JSONBIN_ACCESS_KEY", "").strip()
        master = os.environ.get("JSONBIN_MASTER_KEY", "").strip()
        if not re.fullmatch(r"[a-fA-F0-9]{24}", bin_id) or not (access or master):
            raise Unavailable()
        def read_record():
            candidates = [("X-Master-Key", master)] if master else [("X-Access-Key", access)]
            if not master and access:
                # Accept a Master Key placed in the Access Key setting, without exposing it.
                candidates.append(("X-Master-Key", access))
            for index, (header, value) in enumerate(candidates):
                try:
                    data = json_request(f"https://api.jsonbin.io/v3/b/{bin_id}/latest",
                                        {header: value, "X-Bin-Meta": "false"})
                    print(json.dumps({"event": "jsonbin_auth_ok", "header": header}), flush=True)
                    return data
                except Unavailable as exc:
                    if str(exc) not in ("jsonbin_http_401", "jsonbin_http_403") or index == len(candidates)-1:
                        raise
    record = read_record()
    print(json.dumps({"event": "jsonbin_read_ok"}), flush=True)
    if not isinstance(record, dict) or record.get("schema_version") != 1 or not isinstance(record.get("licenses"), dict):
        raise Unavailable("license_schema_invalid")
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
        except Unavailable as exc:
            code = str(exc)
            if not re.fullmatch(r"[a-z0-9_]{1,80}", code):
                code = "configuration_or_storage_unavailable"
            print(json.dumps({"event": "license_unavailable", "reason": code}), flush=True)
            self.reply(503, {"ok": False, "code": "temporarily_unavailable"})
        except Exception:
            # Never return upstream errors: they can include headers or storage details.
            self.reply(503, {"ok": False, "code": "temporarily_unavailable"})

    def log_message(self, format, *args):
        pass  # No request payload / card logging.
