"""
NOX Scanner — Website Audit Engine
------------------------------------
Fetches a target site and runs a set of deterministic checks across
five categories: Technical, SEO, Trust & Legal, Performance, Accessibility.

No fake AI score. Every point deducted maps to a specific, real finding
that can be shown to a prospect.

Usage:
    python scanner.py https://example.com
    python scanner.py https://example.com --json report.json
    python scanner.py https://example.com --report report.md
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "NOXScanner/1.0 (+https://noxagency.co.uk) audit-bot"
TIMEOUT = 10
MAX_LINKS_TO_CHECK = 12  # sample size for broken-link checking


@dataclass
class Finding:
    category: str
    severity: str  # "critical" | "warning" | "note" | "pass"
    title: str
    detail: str
    points: int  # points deducted from that category's 100 (0 if pass)


@dataclass
class ScanResult:
    url: str
    fetched_ok: bool = True
    status_code: int = 0
    response_time_ms: int = 0
    page_size_kb: float = 0.0
    findings: list = field(default_factory=list)
    category_scores: dict = field(default_factory=dict)
    overall_score: int = 0

    def add(self, category, severity, title, detail, points=0):
        self.findings.append(Finding(category, severity, title, detail, points))


CATEGORIES = ["Technical", "SEO", "Trust & Legal", "Performance", "Accessibility"]
CATEGORY_MAX = 100


def fetch(url: str) -> tuple:
    """Fetch a URL, returning (response, elapsed_ms, error)."""
    headers = {"User-Agent": USER_AGENT}
    start = time.time()
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        elapsed_ms = int((time.time() - start) * 1000)
        return resp, elapsed_ms, None
    except requests.exceptions.RequestException as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return None, elapsed_ms, str(e)


def check_technical(result: ScanResult, soup: BeautifulSoup, url: str, resp):
    parsed = urlparse(url)

    if parsed.scheme == "https":
        result.add("Technical", "pass", "HTTPS in use", "Site is served over a secure connection.")
    else:
        result.add("Technical", "critical", "No HTTPS",
                    "Site is served over plain HTTP. Browsers flag this as 'Not secure' — "
                    "an instant trust killer for any client-facing business.", points=30)

    icon_tags = soup.find_all("link", rel=re.compile("icon", re.I))
    if icon_tags:
        result.add("Technical", "pass", "Favicon present", "A favicon is declared.")
    else:
        result.add("Technical", "warning", "No favicon",
                    "No favicon link found. Shows as a blank/generic tab icon — "
                    "small detail, but it's on the '20 vibecoded website tells' list for a reason.",
                    points=8)

    if not soup.find("meta", charset=True) and not soup.find("meta", attrs={"http-equiv": re.compile("content-type", re.I)}):
        result.add("Technical", "warning", "No charset declared",
                    "No <meta charset> found — can cause encoding issues on some browsers/locales.",
                    points=5)
    else:
        result.add("Technical", "pass", "Charset declared", "Character encoding is explicitly set.")

    generator = soup.find("meta", attrs={"name": "generator"})
    body_text = soup.get_text(" ", strip=True).lower()
    tell_markers = {
        "lovable": "lovable" in body_text or "lovable" in (resp.text[:2000].lower() if resp else ""),
        "vercel preview url": "vercel.app" in url,
    }
    hit_tells = [k for k, v in tell_markers.items() if v]
    if hit_tells:
        result.add("Technical", "warning", "Builder/template tells present",
                    f"Detected: {', '.join(hit_tells)}. These read as unfinished/template site to a "
                    "careful visitor and undercut a premium positioning.", points=10)
    else:
        result.add("Technical", "pass", "No obvious builder tells", "No exposed template/builder branding found.")

    try:
        robots_url = urljoin(url, "/robots.txt")
        r = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=5)
        if r.status_code == 200 and len(r.text.strip()) > 0:
            result.add("Technical", "pass", "robots.txt present", "A robots.txt file exists.")
        else:
            result.add("Technical", "note", "robots.txt missing or empty",
                        "No robots.txt found — minor, but standard practice for crawl control.", points=3)
    except requests.exceptions.RequestException:
        result.add("Technical", "note", "robots.txt unreachable", "Could not fetch robots.txt.", points=3)


def check_seo(result: ScanResult, soup: BeautifulSoup, url: str):
    title = soup.find("title")
    if title and title.text.strip():
        length = len(title.text.strip())
        if 10 <= length <= 60:
            result.add("SEO", "pass", "Title tag present and well-sized",
                        f"'{title.text.strip()}' ({length} chars).")
        else:
            result.add("SEO", "warning", "Title tag length suboptimal",
                        f"Title is {length} chars — outside the ~10-60 char range that displays "
                        "cleanly in search results.", points=8)
    else:
        result.add("SEO", "critical", "No title tag",
                    "Page has no <title>. This is one of the strongest on-page SEO signals — "
                    "its absence is a red flag to search engines and browsers alike.", points=20)

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content", "").strip():
        length = len(meta_desc["content"].strip())
        if 50 <= length <= 160:
            result.add("SEO", "pass", "Meta description present and well-sized", f"{length} chars.")
        else:
            result.add("SEO", "warning", "Meta description length suboptimal",
                        f"{length} chars — outside the ~50-160 char range Google typically displays.",
                        points=6)
    else:
        result.add("SEO", "critical", "No meta description",
                    "No meta description found. Search engines will auto-generate a snippet instead, "
                    "which is rarely as compelling as a written one.", points=15)

    h1s = soup.find_all("h1")
    if len(h1s) == 1:
        result.add("SEO", "pass", "Single H1 present", f"'{h1s[0].get_text(strip=True)[:60]}'")
    elif len(h1s) == 0:
        result.add("SEO", "critical", "No H1 tag",
                    "No H1 found. Every page should have exactly one — it's the clearest heading "
                    "signal for both users and search engines.", points=15)
    else:
        result.add("SEO", "warning", "Multiple H1 tags",
                    f"Found {len(h1s)} H1 tags. Multiple competing H1s dilute the page's topical signal.",
                    points=8)

    og_title = soup.find("meta", property="og:title")
    og_image = soup.find("meta", property="og:image")
    if og_title and og_image:
        result.add("SEO", "pass", "Open Graph tags present", "Social share previews are configured.")
    else:
        result.add("SEO", "note", "Open Graph tags missing/incomplete",
                    "Links shared on social/LinkedIn/iMessage will show a blank or generic preview "
                    "card instead of branded imagery.", points=6)

    canonical = soup.find("link", rel="canonical")
    if canonical:
        result.add("SEO", "pass", "Canonical tag present", "Duplicate-content signal is set.")
    else:
        result.add("SEO", "note", "No canonical tag", "Minor — helps prevent duplicate-content issues.", points=3)


def check_trust_legal(result: ScanResult, soup: BeautifulSoup, url: str):
    body_text = soup.get_text(" ", strip=True).lower()
    links_text = " ".join(a.get_text(" ", strip=True).lower() for a in soup.find_all("a"))
    combined = body_text + " " + links_text

    has_privacy = "privacy" in combined
    has_terms = ("terms" in combined) or ("t&c" in combined) or ("terms of service" in combined)

    if has_privacy:
        result.add("Trust & Legal", "pass", "Privacy policy referenced", "Found reference to a privacy policy.")
    else:
        result.add("Trust & Legal", "critical", "No privacy policy found",
                    "No privacy policy link/reference detected. Required by UK GDPR for any site "
                    "collecting personal data (contact forms, analytics, cookies) — this is a "
                    "compliance risk, not just a trust one.", points=25)

    if has_terms:
        result.add("Trust & Legal", "pass", "Terms referenced", "Found reference to terms/T&Cs.")
    else:
        result.add("Trust & Legal", "warning", "No terms & conditions found",
                    "No T&Cs link detected. Standard expectation for any commercial site.", points=15)

    stat_pattern = re.findall(r"(\d{2,3},?\d{3}\+?)\s*(customers|users|clients|downloads|visitors)", body_text)
    if stat_pattern:
        result.add("Trust & Legal", "note", "Large round-number stat found — verify",
                    f"Found claim(s) like '{stat_pattern[0][0]} {stat_pattern[0][1]}'. Not necessarily "
                    "fake, but round large numbers with no source are a common vibecoded tell — "
                    "worth verifying before repeating this claim to the client.", points=0)

    has_email = bool(re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", body_text))
    has_phone_like = bool(re.search(r"(\+?\d[\d\s\-\(\)]{7,}\d)", body_text))
    if has_email or has_phone_like:
        result.add("Trust & Legal", "pass", "Contact information findable", "Email or phone pattern detected on page.")
    else:
        result.add("Trust & Legal", "warning", "No visible contact info",
                    "No email or phone pattern found in visible text — may be hidden in a form only, "
                    "which is weaker for trust signals.", points=10)


def check_performance(result: ScanResult, resp, elapsed_ms: int):
    result.response_time_ms = elapsed_ms
    if resp is not None:
        size_kb = len(resp.content) / 1024
        result.page_size_kb = round(size_kb, 1)

        if elapsed_ms < 800:
            result.add("Performance", "pass", "Fast initial response", f"{elapsed_ms}ms to first byte + download.")
        elif elapsed_ms < 2000:
            result.add("Performance", "warning", "Moderate response time",
                        f"{elapsed_ms}ms — noticeable but not severe. Worth investigating server/hosting.",
                        points=12)
        else:
            result.add("Performance", "critical", "Slow response time",
                        f"{elapsed_ms}ms — well above the ~2s threshold where visitors start bouncing.",
                        points=25)

        if size_kb < 500:
            result.add("Performance", "pass", "Reasonable HTML payload size", f"{result.page_size_kb} KB.")
        elif size_kb < 1500:
            result.add("Performance", "warning", "Heavy HTML payload",
                        f"{result.page_size_kb} KB of HTML alone — check for unminified markup or "
                        "excessive inline content.", points=10)
        else:
            result.add("Performance", "critical", "Very heavy HTML payload",
                        f"{result.page_size_kb} KB — this alone will slow first paint significantly.",
                        points=20)


def check_accessibility(result: ScanResult, soup: BeautifulSoup):
    images = soup.find_all("img")
    if images:
        missing_alt = [img for img in images if not img.get("alt", "").strip()]
        pct_missing = round(len(missing_alt) / len(images) * 100)
        if pct_missing == 0:
            result.add("Accessibility", "pass", "All images have alt text", f"{len(images)} images checked.")
        elif pct_missing < 30:
            result.add("Accessibility", "warning", "Some images missing alt text",
                        f"{len(missing_alt)}/{len(images)} images ({pct_missing}%) have no alt attribute.",
                        points=10)
        else:
            result.add("Accessibility", "critical", "Most images missing alt text",
                        f"{len(missing_alt)}/{len(images)} images ({pct_missing}%) have no alt attribute — "
                        "a significant accessibility and SEO gap.", points=25)
    else:
        result.add("Accessibility", "note", "No images found on page", "Nothing to check here.")

    viewport = soup.find("meta", attrs={"name": "viewport"})
    if viewport and "width=device-width" in viewport.get("content", ""):
        result.add("Accessibility", "pass", "Mobile viewport configured", "Responsive viewport meta tag present.")
    else:
        result.add("Accessibility", "critical", "No mobile viewport meta tag",
                    "Without this, mobile browsers render a zoomed-out desktop layout. On a site "
                    "where most traffic is mobile, this alone can tank usability.", points=20)

    inputs = soup.find_all("input")
    labelled_inputs = 0
    for inp in inputs:
        input_id = inp.get("id")
        if input_id and soup.find("label", attrs={"for": input_id}):
            labelled_inputs += 1
        elif inp.get("aria-label") or inp.get("placeholder"):
            labelled_inputs += 1
    if inputs:
        if labelled_inputs == len(inputs):
            result.add("Accessibility", "pass", "Form inputs are labelled", f"{len(inputs)} inputs checked.")
        else:
            result.add("Accessibility", "warning", "Some form inputs lack labels",
                        f"{len(inputs) - labelled_inputs}/{len(inputs)} inputs have no associated label — "
                        "a real barrier for screen reader users.", points=10)


def check_broken_links(result: ScanResult, soup: BeautifulSoup, base_url: str):
    links = soup.find_all("a", href=True)
    internal_links = []
    seen = set()
    base_domain = urlparse(base_url).netloc

    for a in links:
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = urljoin(base_url, href)
        if urlparse(full).netloc == base_domain and full not in seen:
            seen.add(full)
            internal_links.append(full)
        if len(internal_links) >= MAX_LINKS_TO_CHECK:
            break

    broken = []
    for link in internal_links:
        try:
            r = requests.head(link, headers={"User-Agent": USER_AGENT}, timeout=5, allow_redirects=True)
            if r.status_code >= 400:
                broken.append((link, r.status_code))
        except requests.exceptions.RequestException:
            broken.append((link, "unreachable"))

    if not internal_links:
        result.add("Technical", "note", "No internal links found to sample", "Could not test link health.")
    elif not broken:
        result.add("Technical", "pass", "Sampled internal links healthy",
                    f"Checked {len(internal_links)} internal links — no broken links found.")
    else:
        detail = "; ".join(f"{link} ({status})" for link, status in broken[:5])
        result.add("Technical", "critical", "Broken internal links found",
                    f"{len(broken)}/{len(internal_links)} sampled links are broken: {detail}",
                    points=min(30, len(broken) * 8))


def score_category(findings: list, category: str) -> int:
    deductions = sum(f.points for f in findings if f.category == category)
    return max(0, CATEGORY_MAX - deductions)


def run_scan(url: str) -> ScanResult:
    if not url.startswith("http"):
        url = "https://" + url

    result = ScanResult(url=url)
    resp, elapsed_ms, error = fetch(url)

    if error or resp is None:
        result.fetched_ok = False
        result.add("Technical", "critical", "Site unreachable", f"Could not fetch {url}: {error}", points=100)
        for cat in CATEGORIES:
            result.category_scores[cat] = 0 if cat == "Technical" else 100
        result.overall_score = 0
        return result

    result.status_code = resp.status_code
    soup = BeautifulSoup(resp.text, "html.parser")

    check_technical(result, soup, url, resp)
    check_seo(result, soup, url)
    check_trust_legal(result, soup, url)
    check_performance(result, resp, elapsed_ms)
    check_accessibility(result, soup)
    check_broken_links(result, soup, url)

    for cat in CATEGORIES:
        result.category_scores[cat] = score_category(result.findings, cat)

    result.overall_score = round(sum(result.category_scores.values()) / len(CATEGORIES))
    return result


def print_report(result: ScanResult):
    print(f"\n{'='*60}")
    print(f"  NOX SCANNER — {result.url}")
    print(f"{'='*60}")
    if not result.fetched_ok:
        print("  Site unreachable — see finding below.\n")
    else:
        print(f"  Overall score: {result.overall_score}/100")
        print(f"  Response time: {result.response_time_ms}ms  |  Page size: {result.page_size_kb} KB\n")
        for cat in CATEGORIES:
            print(f"  {cat}: {result.category_scores[cat]}/100")
    print()

    severity_order = {"critical": 0, "warning": 1, "note": 2, "pass": 3}
    sorted_findings = sorted(result.findings, key=lambda f: (severity_order[f.severity], f.category))

    icons = {"critical": "[CRITICAL]", "warning": "[WARNING] ", "note": "[NOTE]    ", "pass": "[PASS]    "}
    for f in sorted_findings:
        print(f"  {icons[f.severity]} [{f.category}] {f.title}")
        print(f"             {f.detail}")
    print(f"\n{'='*60}\n")


def write_markdown_report(result: ScanResult, path: str):
    lines = [f"# NOX Scanner Report — {result.url}\n"]
    if not result.fetched_ok:
        lines.append("**Site unreachable.** See findings below.\n")
    else:
        lines.append(f"**Overall score: {result.overall_score}/100**\n")
        lines.append(f"Response time: {result.response_time_ms}ms | Page size: {result.page_size_kb} KB\n")
        lines.append("| Category | Score |")
        lines.append("|---|---|")
        for cat in CATEGORIES:
            lines.append(f"| {cat} | {result.category_scores[cat]}/100 |")
        lines.append("")

    severity_order = {"critical": 0, "warning": 1, "note": 2, "pass": 3}
    sorted_findings = sorted(result.findings, key=lambda f: (severity_order[f.severity], f.category))
    severity_labels = {"critical": "Critical", "warning": "Warning", "note": "Note", "pass": "Pass"}

    lines.append("## Findings\n")
    for f in sorted_findings:
        lines.append(f"**[{severity_labels[f.severity]}] {f.category} — {f.title}**")
        lines.append(f"{f.detail}\n")

    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def write_json_report(result: ScanResult, path: str):
    data = {
        "url": result.url,
        "fetched_ok": result.fetched_ok,
        "status_code": result.status_code,
        "response_time_ms": result.response_time_ms,
        "page_size_kb": result.page_size_kb,
        "overall_score": result.overall_score,
        "category_scores": result.category_scores,
        "findings": [
            {"category": f.category, "severity": f.severity, "title": f.title,
             "detail": f.detail, "points_deducted": f.points}
            for f in result.findings
        ],
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


def main():
    parser = argparse.ArgumentParser(description="NOX Scanner — website audit tool")
    parser.add_argument("url", help="URL to scan, e.g. https://example.com")
    parser.add_argument("--report", help="Write a Markdown report to this path")
    parser.add_argument("--json", help="Write a JSON report to this path")
    args = parser.parse_args()

    result = run_scan(args.url)
    print_report(result)

    if args.report:
        write_markdown_report(result, args.report)
        print(f"Markdown report written to {args.report}")
    if args.json:
        write_json_report(result, args.json)
        print(f"JSON report written to {args.json}")


if __name__ == "__main__":
    main()
