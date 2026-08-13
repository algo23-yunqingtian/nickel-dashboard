1|#!/usr/bin/env python3
2|"""
3|AI proxy for nickel dashboard — forwards browser AI requests to zsun AI.
4|Prevents exposing API key in frontend JavaScript.
5|Runs on port 8769.
6|"""
7|import os
8|import json
9|import urllib.request
10|import urllib.error
11|from http.server import HTTPServer, BaseHTTPRequestHandler
12|from datetime import datetime
13|
14|# Load .env if present
15|env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
16|if os.path.exists(env_file):
17|    with open(env_file) as f:
18|        for line in f:
19|            line = line.strip()
20|            if line and not line.startswith("#") and "=" in line:
21|                k, v = line.split("=", 1)
22|                os.environ.setdefault(k.strip(), v.strip())
23|
24|ZSUN_KEY = os.environ.get("ZSUN_KEY", "")
25|ZSUN_URL = "https://zsun.funkits.cn/v1/chat/completions"
26|ZSUN_MODEL = "Qwen36"
27|
28|# Import analyze module
29|try:
30|    from analyze import analyze as run_analysis
31|except ImportError:
32|    run_analysis = None
33|
34|CORS_HEADERS = {
35|    "Access-Control-Allow-Origin": "*",
36|    "Access-Control-Allow-Methods": "POST, OPTIONS",
37|    "Access-Control-Allow-Headers": "Content-Type",
38|    "Content-Type": "application/json",
39|}
40|
41|
42|class AIProxyHandler(BaseHTTPRequestHandler):
43|    def log_message(self, format, *args):
44|        pass  # Silence logs
45|
46|    def do_OPTIONS(self):
47|        self.send_response(204)
48|        for k, v in CORS_HEADERS.items():
49|            self.send_header(k, v)
50|        self.end_headers()
51|
52|    def do_POST(self):
53|        path = self.path.split("?")[0]
54|
55|        # Route: /analyze or /api/analyze → real-time AI analysis
56|        if path == "/analyze" or path == "/api/analyze":
57|            self._handle_analyze()
58|            return
59|
60|        # Route: /prompt or /api/prompt → return current prompt template
61|        if path == "/prompt" or path == "/api/prompt":
62|            self._handle_prompt()
63|            return
64|
65|        # Default: pass-through proxy (original behavior)
66|        if not ZSUN_KEY:
67|            self._respond({"error": "SILICONFLOW_KEY not configured"}, 500)
68|            return
69|
70|        content_length = int(self.headers.get("Content-Length", 0))
71|        body = self.rfile.read(content_length)
72|
73|        try:
74|            req_body = json.loads(body) if body else {}
75|        except json.JSONDecodeError:
76|            self._respond({"error": "Invalid JSON"}, 400)
77|            return
78|
79|        payload = {
80|            "model": req_body.get("model", ZSUN_MODEL),
81|            "messages": req_body.get("messages", []),
82|            "max_tokens": req_body.get("max_tokens", 800),
83|            "temperature": req_body.get("temperature", 0.7),
84|        }
85|
86|        try:
87|            req = urllib.request.Request(
88|                ZSUN_URL,
89|                data=json.dumps(payload).encode(),
90|                headers={
91|                    "Content-Type": "application/json",
92|                    "Authorization": f"Bearer {ZSUN_KEY}",
93|                },
94|            )
95|            with urllib.request.urlopen(req, timeout=60) as resp:
96|                result = json.loads(resp.read())
97|
98|            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
99|            usage = result.get("usage", {})
100|
101|            self._respond({
102|                "content": text,
103|                "model": ZSUN_MODEL,
104|                "usage": usage,
105|            }, 200)
106|        except urllib.error.HTTPError as e:
107|            err_body = e.read().decode() if e.fp else str(e)
108|            self._respond({"error": f"SiliconFlow returned {e.code}: {err_body[:200]}"}, e.code)
109|        except Exception as e:
110|            self._respond({"error": str(e)}, 502)
111|
112|    def _handle_analyze(self):
113|        """Real-time AI analysis endpoint"""
114|        content_length = int(self.headers.get("Content-Length", 0))
115|        if content_length > 0:
116|            self.rfile.read(content_length)
117|
118|        if not run_analysis:
119|            self._respond({"error": "analyze module not available"}, 500)
120|            return
121|        if not ZSUN_KEY:
122|            self._respond({"error": "SILICONFLOW_KEY not configured"}, 500)
123|            return
124|
125|        try:
126|            result = run_analysis(ZSUN_KEY)
127|            if "error" in result:
128|                self._respond(result, 500)
129|            else:
130|                result["skill"] = {
131|                    "name": "nickel-ai-analysis",
132|                    "version": "3.0",
133|                    "model": ZSUN_MODEL,
134|                    "framework": "6步思维链",
135|                    "indicators": 18,
136|                    "data_sources": ["Zhiji API", "本地DB", "akshare资讯"],
137|                    "weights": {"supply": "25%", "inventory": "25%", "demand": "25%", "funding": "15%", "news": "10%"}
138|                }
139|                self._respond(result, 200)
140|        except Exception as e:
141|            self._respond({"error": f"Analysis failed: {str(e)[:200]}"}, 500)
142|
143|    def _handle_prompt(self):
144|        """Return current prompt template and skill info"""
145|        content_length = int(self.headers.get("Content-Length", 0))
146|        if content_length > 0:
147|            self.rfile.read(content_length)
148|
149|        try:
150|            from analyze import build_prompt, load_data, fetch_news, fetch_reports
151|            data = load_data()
152|            if not data:
153|                self._respond({"error": "no data.json"}, 500)
154|                return
155|            charts = data.get("charts", {})
156|            news = fetch_news()
157|            reports = fetch_reports()
158|            prompt = build_prompt(charts, news, reports)
159|            self._respond({
160|                "prompt": prompt,
161|                "skill": {
162|                    "name": "nickel-ai-analyzer",
163|                    "version": "P3",
164|                    "model": ZSUN_MODEL,
165|                    "framework": "6-step chain-of-thought",
166|                    "indicators": 18,
167|                    "data_sources": ["Zhiji API", "本地DB (data.json)", "akshare新闻", "SMM研报观点"],
168|                    "weights": {"supply": "35%", "inventory": "25%", "demand": "20%", "funding": "15%", "news": "5%"}
169|                },
170|                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
171|            }, 200)
172|        except Exception as e:
173|            self._respond({"error": f"Prompt fetch failed: {str(e)[:200]}"}, 500)
174|
175|    def _respond(self, data, status=200):
176|        self.send_response(status)
177|        for k, v in CORS_HEADERS.items():
178|            self.send_header(k, v)
179|        self.end_headers()
180|        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
181|
182|
183|def main():
184|    port = int(os.environ.get("PORT", 8769))
185|    server = HTTPServer(("0.0.0.0", port), AIProxyHandler)
186|    print(f"AI proxy listening on port {port}")
187|    server.serve_forever()
188|
189|
190|if __name__ == "__main__":
191|    main()
192|