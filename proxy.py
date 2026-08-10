#!/usr/bin/env python3
"""
AI proxy for nickel dashboard — forwards browser AI requests to SiliconFlow.
Prevents exposing API key in frontend JavaScript.
Runs on port 8769.
"""
import os
import json
import urllib.request
import urllib.error
import configparser
from http.server import HTTPServer, BaseHTTPRequestHandler

# Load .env if present
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

SF_KEY = os.environ.get("SILICONFLOW_KEY", "")
SF_URL = "https://api.siliconflow.cn/v1/chat/completions"
SF_MODEL = "Qwen/Qwen2.5-72B-Instruct"

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}


class AIProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silence logs

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        if not SF_KEY:
            self._respond({"error": "SILICONFLOW_KEY not configured"}, 500)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            req_body = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._respond({"error": "Invalid JSON"}, 400)
            return

        # Build the SiliconFlow request
        payload = {
            "model": req_body.get("model", SF_MODEL),
            "messages": req_body.get("messages", []),
            "max_tokens": req_body.get("max_tokens", 800),
            "temperature": req_body.get("temperature", 0.7),
        }

        try:
            req = urllib.request.Request(
                SF_URL,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {SF_KEY}",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())

            # Proxy: return just the text
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = result.get("usage", {})

            self._respond({
                "content": text,
                "model": SF_MODEL,
                "usage": usage,
            }, 200)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else str(e)
            self._respond({"error": f"SiliconFlow returned {e.code}: {err_body[:200]}"}, e.code)
        except Exception as e:
            self._respond({"error": str(e)}, 502)

    def _respond(self, data, status=200):
        self.send_response(status)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())


def main():
    port = int(os.environ.get("PORT", 8769))
    server = HTTPServer(("0.0.0.0", port), AIProxyHandler)
    print(f"AI proxy listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
