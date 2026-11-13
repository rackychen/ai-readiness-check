# ai-readiness-check

Zero-dependency Python CLI to audit whether a website (WordPress, static site, or SPA) is structurally readable by AI search crawlers and answer engines (ChatGPT Search, Perplexity, Claude, Google AI Overviews).

## Why this exists

Most SEO tools check Googlebot rendering with a full headless browser. AI retrieval bots (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `OAI-SearchBot`) often do **not** execute heavy client-side JavaScript—if your site serves an empty `<div id="root"></div>` or blocks AI user-agents in `robots.txt`, answer engines see nothing.

`ai-readiness-check` fetches raw HTTP responses (no JS execution) and checks 6 fundamentals:

1. **`robots.txt`** — Verifies `GPTBot`, `OAI-SearchBot`, `ChatGPT-User`, `ClaudeBot`, `PerplexityBot`, and `Google-Extended` are not blocked.
2. **`/llms.txt`** — Checks existence, plain-text/markdown `Content-Type` (catches SPA HTML fallbacks), heading, and curated links.
3. **`/sitemap.xml`** — Verifies valid XML and counts `<loc>` entries.
4. **Raw HTML visibility (SSR/SSG)** — Ensures `<h1>` and visible body copy exist in the initial HTML without JavaScript.
5. **Metadata** — Checks `<title>`, `<meta name="description">`, and `<link rel="canonical">`.
6. **JSON-LD (`Schema.org`)** — Parses `application/ld+json` blocks and lists detected `@type` entities (`Organization`, `Service`, `Product`, `FAQPage`, etc.).

## Usage

Requires Python 3.9+ (standard library only, no `pip install` needed).

```bash
python3 ai_readiness_check.py https://smartseo.org/services/ai-readiness/
```

Example output:

```text
AI Search Readiness Audit: https://smartseo.org/services/ai-readiness/

[PASS] robots.txt     HTTP 200; AI crawlers explicitly configured: GPTBot, ClaudeBot, PerplexityBot, Google-Extended
[PASS] llms.txt       HTTP 200 (1744 chars, 4 markdown links)
[PASS] sitemap.xml    HTTP 200 (10 <loc> entries)
[PASS] raw_html_ssr   3667 visible chars in raw HTML; H1: AI Search Readiness Sprint
[PASS] metadata       title=yes, description=yes, canonical=yes
[PASS] json_ld        Schema types: Answer, FAQPage, Offer, Organization, Person, Question, Service

Summary: 6 PASS, 0 WARN, 0 FAIL
```

JSON output for CI or scripts (exits with code `1` if any check is `FAIL`):

```bash
python3 ai_readiness_check.py https://example.com --json
```

## Reference Implementation

Built and maintained by Racky as part of the [SmartSEO.org AI Search Readiness Sprint](https://smartseo.org/services/ai-readiness/) for WordPress and custom web stacks.

## License

MIT
