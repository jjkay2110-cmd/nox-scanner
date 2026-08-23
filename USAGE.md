# NOX Scanner — Usage

A real website audit tool — no fake "AI score." Every point deducted maps to
a specific, checkable finding you can screenshot and send to a prospect.

Checks five categories: **Technical, SEO, Trust & Legal, Performance, Accessibility.**

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.8+.

## Usage

```bash
python scanner.py https://example.com
python scanner.py https://example.com --report report.md
python scanner.py https://example.com --json report.json
```

## Using this as the client-acquisition hook

1. Find a prospect with an obviously outdated or poorly built site (Bark leads,
   local hospitality businesses, cold outreach targets).
2. Run the scanner against their live site.
3. Pull the 3–4 most damning **critical** findings.
4. Lead outreach with those specific findings, not a generic pitch.
5. The Markdown report becomes the audit deliverable if Website Auditing
   becomes a paid line item on its own.

## v1 limitations

- No headless browser — JS-rendered content isn't checked.
- Performance category is a proxy (response time + payload size), not full
  Core Web Vitals.
- Broken-link checking samples the first 12 internal links, not a full crawl.

## Natural next steps (v2)

- Lighthouse/PageSpeed Insights API integration for real Core Web Vitals.
- Playwright for JS-rendered content + screenshot capture.
- Wire into Claude Code as the AUDITOR subagent, callable by JARVIS.
- Lightweight web UI so Alfie/Harvey can run scans without the terminal.
