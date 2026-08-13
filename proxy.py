#!/usr/bin/env python3
"""
AI proxy for nickel dashboard — forwards browser AI requests to zsun AI.
Prevents exposing API key in frontend JavaScript.
Runs on port 8769.
"""
import os
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Load .env if present
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

ZSUN_KEY = os.environ.get("ZSUN_KEY", "")
ZSUN_URL = "https://zsun.funkits.cn/v1/chat/completions"
ZSUN_MODEL = "Qwen36_35B"

# Import analyze module
try:
    from analyze import analyze as run_analysis
except ImportError:
    run_analysis = None

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
        path = self.path.split("?")[0]

        # Route: /analyze or /api/analyze → real-time AI analysis
        if path == "/analyze" or path == "/api/analyze":
            self._handle_analyze()
            return

        # Route: /prompt or /api/prompt → return current prompt template
        if path == "/prompt" or path == "/api/prompt":
            self._handle_prompt()
            return

        # Default: pass-through proxy (original behavior)
        if not ZSUN_KEY:
            self._respond({"error": "SILICONFLOW_KEY not configured"}, 500)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            req_body = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._respond({"error": "Invalid JSON"}, 400)
            return

        payload = {
            "model": req_body.get("model", ZSUN_MODEL),
            "messages": req_body.get("messages", []),
            "max_tokens": req_body.get("max_tokens", 800),
            "temperature": req_body.get("temperature", 0.7),
        }

        try:
            req = urllib.request.Request(
                ZSUN_URL,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {ZSUN_KEY}",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())

            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = result.get("usage", {})

            self._respond({
                "content": text,
                "model": ZSUN_MODEL,
                "usage": usage,
            }, 200)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else str(e)
            self._respond({"error": f"SiliconFlow returned {e.code}: {err_body[:200]}"}, e.code)
        except Exception as e:
            self._respond({"error": str(e)}, 502)

    def _handle_analyze(self):
        """Real-time AI analysis endpoint"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)

        if not run_analysis:
            self._respond({"error": "analyze module not available"}, 500)
            return
        if not ZSUN_KEY:
            self._respond({"error": "SILICONFLOW_KEY not configured"}, 500)
            return

        try:
            result = run_analysis(ZSUN_KEY)
            if "error" in result:
                self._respond(result, 500)
            else:
                result["skill"] = {
                    "name": "nickel-ai-analysis",
                    "version": "3.0",
                    "model": ZSUN_MODEL,
                    "framework": "6步思维链",
                    "indicators": 18,
                    "data_sources": ["Zhiji API", "本地DB", "akshare资讯"],
                    "weights": {"supply": "25%", "inventory": "25%", "demand": "25%", "funding": "15%", "news": "10%"}
                }
                self._respond(result, 200)
        except Exception as e:
            self._respond({"error": f"Analysis failed: {str(e)[:200]}"}, 500)

    def _handle_prompt(self):
        """Return current prompt template and skill info"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)

        try:
            from analyze import build_prompt, load_data, fetch_news, fetch_reports
            data = load_data()
            if not data:
                self._respond({"error": "no data.json"}, 500)
                return
            charts = data.get("charts", {})
            news = fetch_news()
            reports = fetch_reports()
            prompt = build_prompt(charts, news, reports)
            self._respond({
                "prompt": prompt,
                "skill": {
                    "name": "nickel-ai-analyzer",
                    "version": "P3",
                    "model": ZSUN_MODEL,
                    "framework": "6-step chain-of-thought",
                    "indicators": 18,
                    "data_sources": ["Zhiji API", "本地DB (data.json)", "akshare新闻", "SMM研报观点"],
                    "weights": {"supply": "35%", "inventory": "25%", "demand": "20%", "funding": "15%", "news": "5%"}
                },
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, 200)
        except Exception as e:
            self._respond({"error": f"Prompt fetch failed: {str(e)[:200]}"}, 500)

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
