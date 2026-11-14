"""Check, step by step, whether the Nemotron server answers (never prints the key).

Usage (from the repository root):
    python analysis/check_nemotron.py

Each step narrows down where a problem is:
  1. internet works at all (a Wikipedia request)
  2. the server's name resolves and its port 443 accepts a connection
  3. the API answers the model list (no model work needed)
  4. the model answers a 2-word question
"""

import os
import socket
import time
from urllib.parse import urlparse

import httpx

from env import load_env, nemotron_config, use_mock


def step(name: str, fn) -> bool:
    started = time.time()
    try:
        detail = fn()
        print(f"OK    {name} ({time.time() - started:.1f} s) {detail or ''}")
        return True
    except Exception as e:
        print(f"FAIL  {name} ({time.time() - started:.1f} s) {type(e).__name__}: {str(e)[:150]}")
        return False


def main() -> None:
    load_env()
    # This tool exists to reach the real server: in mock mode there is nothing to check, so say so.
    if use_mock():
        raise SystemExit("USE_MOCK=true: no request sent. Set USE_MOCK=false in .env to check the real server.")
    config = nemotron_config()
    if not config["key"]:
        raise SystemExit(f"{config['key_name']} is missing from .env")
    base = config["base_url"].rstrip("/")
    host = urlparse(base).hostname
    headers = {"Authorization": f"Bearer {config['key']}"}
    print(f"Provider: {config['provider']}\nServer:   {base}\nModel:    {config['model']}\n")

    def internet():
        r = httpx.get("https://fi.wikipedia.org/w/api.php?action=query&format=json&meta=siteinfo",
                      headers={"User-Agent": os.environ.get("WIKI_USER_AGENT", "TimeProof check")}, timeout=15)
        return f"HTTP {r.status_code}"

    def tcp():
        ip = socket.gethostbyname(host)
        socket.create_connection((host, 443), timeout=10).close()
        return f"{host} -> {ip}"

    def models():
        # Long timeouts: under load the shared server took up to 220 s to answer (Saturday).
        r = httpx.get(base + "/models", headers=headers, timeout=300)
        return f"HTTP {r.status_code} {r.text[:120]}"

    def chat():
        r = httpx.post(base + "/chat/completions", headers=headers, timeout=300,
                       json={"model": config["model"], "max_tokens": 200,   # room for reasoning tokens
                             "messages": [{"role": "user", "content": "Reply with the word OK."}]})
        if r.status_code != 200:
            return f"HTTP {r.status_code} {r.text[:200]}"
        return f"HTTP 200, answer: {(r.json()['choices'][0]['message'].get('content') or '').strip()[:40]!r}"

    results = [step("1. internet (Wikipedia)", internet),
               step("2. server reachable (DNS + port 443)", tcp),
               step("3. API answers /models", models),
               step("4. model answers a tiny prompt", chat)]

    print()
    if not results[0]:
        print("-> Our own internet connection is the problem (venue Wi-Fi?).")
    elif not results[1]:
        print("-> The server address does not answer at all: server down or address changed. Ask on Discord.")
    elif not results[2] or not results[3]:
        print("-> The machine is up but the API did not answer within 5 min: overloaded or stuck. Ask on Discord.")
    else:
        print("-> Everything answers. If a step said HTTP 401/403, the key is the problem; 429 means rate limit.")


if __name__ == "__main__":
    main()
