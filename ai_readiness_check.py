#!/usr/bin/env python3
"""
ai-readiness-check: Zero-dependency CLI to audit whether a website (WordPress,
static site, or SPA) is readable by AI search crawlers and answer engines.
"""

from __future__ import annotations

import argparse
import html.parser
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

AI_CRAWLERS = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
)

USER_AGENT = "ai-readiness-check/0.1 (+https://github.com/rackychen/ai-readiness-check)"


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str


class _HtmlInspector(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.in_h1 = False
        self.skip_depth = 0
        self.in_ld_json = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.text_parts: list[str] = []
        self.ld_json_chunks: list[str] = []
        self._current_ld: list[str] = []
        self.meta_description = ""
        self.canonical = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg"):
            self.skip_depth += 1
            if t == "script" and attr_map.get("type", "").lower() == "application/ld+json":
                self.in_ld_json = True
                self._current_ld = []
            return
        if t == "title":
            self.in_title = True
        elif t == "h1":
            self.in_h1 = True
        elif t == "meta" and attr_map.get("name", "").lower() == "description":
            self.meta_description = attr_map.get("content", "").strip()
        elif t == "link" and "canonical" in attr_map.get("rel", "").lower().split():
            self.canonical = attr_map.get("href", "").strip()

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg"):
            if self.in_ld_json and t == "script":
                self.ld_json_chunks.append("".join(self._current_ld).strip())
                self.in_ld_json = False
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if t == "title":
            self.in_title = False
        elif t == "h1":
            self.in_h1 = False

    def handle_data(self, data: str) -> None:
        if self.in_ld_json:
            self._current_ld.append(data)
            return
        if self.skip_depth > 0:
            return
        if self.in_title:
            self.title_parts.append(data)
        if self.in_h1:
            self.h1_parts.append(data)
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)


def fetch(url: str, timeout: int = 12) -> tuple[int, dict[str, str], str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, headers, body
    except urllib.error.HTTPError as err:
        headers = {k.lower(): v for k, v in err.headers.items()} if err.headers else {}
        body = err.read().decode("utf-8", errors="replace") if err.fp else ""
        return err.code, headers, body
    except urllib.error.URLError as err:
        return 0, {}, str(err.reason)


def parse_robots_blocks(robots_text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current_agents: list[str] = []
    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = [x.strip() for x in line.split(":", 1)]
        kl = key.lower()
        if kl == "user-agent":
            if current_agents and any(a in blocks and blocks[a] for a in current_agents):
                current_agents = [val.lower()]
            else:
                current_agents.append(val.lower())
            blocks.setdefault(val.lower(), [])
        elif kl in ("disallow", "allow") and current_agents:
            for agent in current_agents:
                blocks[agent].append(f"{kl}:{val}")
    return blocks


def check_robots(origin: str) -> CheckResult:
    code, _, body = fetch(f"{origin}/robots.txt")
    if code != 200 or not body.strip():
        return CheckResult("robots.txt", "WARN", f"HTTP {code}; missing or empty robots.txt")

    blocks = parse_robots_blocks(body)
    wildcard_rules = blocks.get("*", [])
    wildcard_blocked = "disallow:/" in wildcard_rules and "allow:/" not in wildcard_rules

    blocked_bots: list[str] = []
    for bot in AI_CRAWLERS:
        rules = blocks.get(bot.lower())
        if rules is not None:
            if "disallow:/" in rules and "allow:/" not in rules:
                blocked_bots.append(bot)
        elif wildcard_blocked:
            blocked_bots.append(f"{bot}(*)")

    if blocked_bots:
        return CheckResult("robots.txt", "FAIL", f"Blocked AI crawlers: {', '.join(blocked_bots)}")
    explicit = [b for b in AI_CRAWLERS if b.lower() in blocks]
    note = f"explicitly configured: {', '.join(explicit)}" if explicit else "allowed via default rules"
    return CheckResult("robots.txt", "PASS", f"HTTP 200; AI crawlers {note}")


def check_llms_txt(origin: str) -> CheckResult:
    code, headers, body = fetch(f"{origin}/llms.txt")
    if code != 200:
        return CheckResult("llms.txt", "FAIL", f"HTTP {code}; /llms.txt not found")
    ctype = headers.get("content-type", "")
    if "html" in ctype.lower() or body.lstrip().lower().startswith("<!doctype html"):
        return CheckResult("llms.txt", "FAIL", "Returned HTML instead of plain text/markdown (SPA fallback?)")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    links = len(re.findall(r"\[[^\]]+\]\(https?://[^)]+\)", body))
    has_h1 = any(ln.lstrip().startswith("# ") for ln in lines)
    if not has_h1 or len(body.strip()) < 80:
        return CheckResult("llms.txt", "WARN", f"HTTP 200 ({len(body)} chars), missing '# Title' or too short")
    return CheckResult("llms.txt", "PASS", f"HTTP 200 ({len(body)} chars, {links} markdown links)")


def check_sitemap(origin: str) -> CheckResult:
    code, _, body = fetch(f"{origin}/sitemap.xml")
    if code != 200 or "<urlset" not in body.lower() and "<sitemapindex" not in body.lower():
        return CheckResult("sitemap.xml", "WARN", f"HTTP {code}; valid XML sitemap not detected")
    urls = len(re.findall(r"<loc>", body, flags=re.IGNORECASE))
    return CheckResult("sitemap.xml", "PASS", f"HTTP 200 ({urls} <loc> entries)")


def extract_schema_types(chunks: list[str]) -> list[str]:
    types: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(str(x) for x in t)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for chunk in chunks:
        try:
            walk(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return sorted(set(types))


def check_html_page(url: str) -> list[CheckResult]:
    code, _, body = fetch(url)
    if code != 200:
        return [CheckResult("raw_html", "FAIL", f"HTTP {code} fetching {url}")]

    parser = _HtmlInspector()
    parser.feed(body)
    title = "".join(parser.title_parts).strip()
    h1 = "".join(parser.h1_parts).strip()
    visible_text = " ".join(parser.text_parts)
    text_len = len(visible_text)

    results: list[CheckResult] = []
    if text_len < 250 or not h1:
        results.append(
            CheckResult(
                "raw_html_ssr",
                "FAIL",
                f"Low pre-rendered content ({text_len} visible chars, h1={'yes' if h1 else 'missing'}); likely CSR JS shell",
            )
        )
    else:
        results.append(
            CheckResult("raw_html_ssr", "PASS", f"{text_len} visible chars in raw HTML; H1: {h1[:48]}")
        )

    meta_ok = bool(title and parser.meta_description and parser.canonical)
    results.append(
        CheckResult(
            "metadata",
            "PASS" if meta_ok else "WARN",
            f"title={'yes' if title else 'no'}, description={'yes' if parser.meta_description else 'no'}, canonical={'yes' if parser.canonical else 'no'}",
        )
    )

    schema_types = extract_schema_types(parser.ld_json_chunks)
    if not schema_types:
        results.append(CheckResult("json_ld", "WARN", "No valid application/ld+json Schema.org blocks found"))
    else:
        results.append(CheckResult("json_ld", "PASS", f"Schema types: {', '.join(schema_types)}"))
    return results


def audit_url(target_url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(target_url)
    if not parsed.scheme:
        target_url = f"https://{target_url}"
        parsed = urllib.parse.urlparse(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    checks = [
        check_robots(origin),
        check_llms_txt(origin),
        check_sitemap(origin),
        *check_html_page(target_url),
    ]
    summary = {
        "pass": sum(1 for c in checks if c.status == "PASS"),
        "warn": sum(1 for c in checks if c.status == "WARN"),
        "fail": sum(1 for c in checks if c.status == "FAIL"),
    }
    return {"url": target_url, "origin": origin, "summary": summary, "checks": [asdict(c) for c in checks]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit a website (WordPress, SSG, or SPA) for AI search readiness (GEO)."
    )
    parser.add_argument("url", help="Target page or site URL (e.g. https://smartseo.org)")
    parser.add_argument("--json", action="store_true", help="Output report as JSON")
    args = parser.parse_args()

    report = audit_url(args.url)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"AI Search Readiness Audit: {report['url']}\n")
        for c in report["checks"]:
            print(f"[{c['status']:4}] {c['name']:14} {c['detail']}")
        s = report["summary"]
        print(f"\nSummary: {s['pass']} PASS, {s['warn']} WARN, {s['fail']} FAIL")

    return 1 if report["summary"]["fail"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
