"""
Common public-page collector for the Visa and Regulatory Change module.

Collection only: this file downloads one public HTML page or PDF and keeps the
original HTML, a plain-text view and compact "content blocks" (list items,
articles, table rows, headings and paragraphs, each with its first link).
It does not decide whether anything is a visa change; processing/ does that.

It never logs in, solves challenges or renders pages in a browser. A blocked or
failed request is raised so run_scraper.py can record it as a failed attempt.
"""

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from urllib.parse import urljoin, urlparse
import re

import requests
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except ImportError:
    # Only needed when a PDF source is collected, so HTML collection still works
    # from a plain requests/beautifulsoup4 install.
    PdfReader = None


# -------------- Request --------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; RMIT-Market-Intelligence-Project/1.0)"
    )
}

TIMEOUT = 30

HTML_MEDIA_TYPE = "text/html"
PDF_MEDIA_TYPE = "application/pdf"
PDF_SIGNATURE = b"%PDF-"

SNAPSHOT_SCHEMA_VERSION = "1.0"

# A page with this little text and this many scripts is probably drawn by
# JavaScript, so an empty-looking snapshot is not evidence that nothing changed.
CLIENT_RENDERED_MAX_WORDS = 80
CLIENT_RENDERED_MIN_SCRIPTS = 5

BLOCK_CONTAINERS = ["article", "li", "tr"]
BLOCK_TEXT_TAGS = ["h1", "h2", "h3", "h4", "p"]
NOISE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "form", "svg"]

LAST_UPDATED = re.compile(
    r"last\s+updated\s*:?\s*"
    r"(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2}\s*[AP]M)?|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    re.I,
)


# -------------- Downloading --------------

def response_media_type(response):
    """Declared media type without its charset parameter."""
    return (response.headers.get("content-type") or "").split(";")[0].strip().lower()


def is_pdf(payload, media_type):
    """Trust the declared type, then the file signature: a served file may lack one."""
    return media_type == PDF_MEDIA_TYPE or (
        isinstance(payload, bytes) and payload.startswith(PDF_SIGNATURE))


def decode_html(content, fallback_encoding=None):
    """Prefer BOM/meta declarations over requests' default Latin-1 decoding."""
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig")
    declared = re.search(br"charset\s*=\s*[\"']?([a-zA-Z0-9_-]+)", content[:8192], re.I)
    if declared:
        try:
            return content.decode(declared.group(1).decode("ascii"))
        except (LookupError, UnicodeError):
            pass
    try:
        return content.decode("utf-8")
    except UnicodeError:
        return content.decode(fallback_encoding or "windows-1252", errors="replace")


def download_page(url):
    """
    Download one public document.

    Returns (payload, final_url, status_code, media_type). The payload is decoded
    text for HTML and undecoded bytes for PDF. Non-2xx responses raise
    requests.HTTPError; there is no retry-with-another-client fallback.
    """
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    media_type = response_media_type(response)

    # Decoding PDF bytes as text silently yields an empty extraction with HTTP 200.
    if is_pdf(response.content, media_type):
        return response.content, response.url, response.status_code, PDF_MEDIA_TYPE

    return (decode_html(response.content, response.encoding),
            response.url, response.status_code, media_type or HTML_MEDIA_TYPE)


# -------------- HTML extraction --------------

def _text(element):
    return " ".join(element.get_text(" ", strip=True).split())


def content_blocks(soup, final_url):
    """
    Split a page into compact evidence blocks.

    Smallest list item, article or table row first (a news card keeps its title,
    date and link together), then headings and paragraphs outside those blocks.
    Each block keeps its first absolute link so a record can cite a specific
    notice instead of only the listing page. Text is deduplicated.
    """
    blocks, used, seen = [], set(), set()

    def add(element):
        text = _text(element)
        if not text or text in seen:
            return
        seen.add(text)
        anchor = element if element.name == "a" else (
            element.find("a", href=True) or element.find_parent("a", href=True))
        href = urljoin(final_url, anchor["href"]) if anchor is not None else None
        if href and not href.startswith(("http://", "https://")):
            href = None
        blocks.append({
            "block_id": f"b{len(blocks)}",
            "tag": element.name,
            "text": text,
            "link_text": _text(anchor) if anchor is not None else None,
            "href": href,
        })

    for element in soup.find_all(BLOCK_CONTAINERS):
        if element.find(BLOCK_CONTAINERS):
            continue  # outer container; its inner items are collected instead
        add(element)
        used.update(id(node) for node in element.descendants)

    for element in soup.find_all(BLOCK_TEXT_TAGS):
        if id(element) not in used:
            add(element)

    return blocks


def extract_page_data(html, requested_url, final_url):
    """Extract evidence from one HTML page. The original HTML is always kept."""
    soup = BeautifulSoup(html, "html.parser")
    script_count = len(soup.find_all("script"))

    title = _text(soup.title) if soup.title else ""
    links = list(dict.fromkeys(
        urljoin(final_url, a["href"]) for a in soup.find_all("a", href=True)
        if urljoin(final_url, a["href"]).startswith(("http://", "https://"))))

    page_text = _text(soup)
    updated = LAST_UPDATED.search(page_text)

    # Navigation, headers, footers and forms are boilerplate, not notices.
    for node in soup.find_all(NOISE_TAGS):
        node.decompose()

    headings = [{"level": int(h.name[1]), "text": _text(h)}
                for h in soup.find_all(["h1", "h2", "h3", "h4"]) if _text(h)]
    paragraphs = []
    for element in soup.find_all(["p", "li"]):
        text = _text(element)
        if text and (not paragraphs or paragraphs[-1] != text):
            paragraphs.append(text)

    blocks = content_blocks(soup, final_url)
    full_text = "\n".join(paragraphs)

    warnings = []
    if not paragraphs and not blocks:
        warnings.append("no_text_extracted")
    if len(full_text.split()) < CLIENT_RENDERED_MAX_WORDS and script_count >= CLIENT_RENDERED_MIN_SCRIPTS:
        warnings.append("possible_client_rendered_page")

    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "media_type": HTML_MEDIA_TYPE,

        # Decoded original page. Hashes detect change, not a verified rule change.
        "raw_html": html,
        "raw_html_hash": sha256(html.encode("utf-8")).hexdigest(),

        "requested_url": requested_url,
        "final_url": final_url,
        "domain": urlparse(final_url).netloc,

        "page_title": title,
        "page_last_updated_text": updated.group(1) if updated else None,
        "headings": headings,
        "paragraphs": paragraphs,
        "content_blocks": blocks,
        "full_text": full_text,
        "word_count": len(full_text.split()),

        "number_of_links": len(links),
        "links": links,

        # Hash of extracted paragraph text only; raw_html_hash covers the whole page.
        "content_hash": sha256(full_text.encode("utf-8")).hexdigest(),
        "quality_warnings": warnings,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


# -------------- PDF extraction --------------

def pdf_paragraphs(text):
    """Group extracted PDF lines into paragraphs split on blank lines."""
    paragraphs = []
    for group in re.split(r"\n\s*\n", text or ""):
        joined = " ".join(group.split())
        if joined:
            paragraphs.append(joined)
    return paragraphs


def extract_pdf_data(content, requested_url, final_url):
    """Extract text from a government PDF notice or fact sheet."""
    if PdfReader is None:
        raise RuntimeError("pypdf is required to collect PDF sources; install requirements.txt")

    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    paragraphs = pdf_paragraphs(text)
    full_text = "\n".join(paragraphs)

    try:
        title = (reader.metadata or {}).get("/Title") or ""
    except (AttributeError, KeyError, TypeError, ValueError):
        title = ""

    blocks = [{"block_id": f"b{i}", "tag": "pdf_paragraph", "text": p,
               "link_text": None, "href": None} for i, p in enumerate(paragraphs)]

    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "media_type": PDF_MEDIA_TYPE,
        "pdf_page_count": len(reader.pages),

        # Source bytes are not embedded in JSON; the hash still detects a changed file.
        "raw_html": None,
        "raw_html_hash": None,
        "raw_document_hash": sha256(content).hexdigest(),

        "requested_url": requested_url,
        "final_url": final_url,
        "domain": urlparse(final_url).netloc,

        "page_title": title,
        "page_last_updated_text": None,
        "headings": [],
        "paragraphs": paragraphs,
        "content_blocks": blocks,
        "full_text": full_text,
        "word_count": len(full_text.split()),

        "number_of_links": 0,
        "links": [],

        "content_hash": sha256(full_text.encode("utf-8")).hexdigest(),
        "quality_warnings": [] if paragraphs else ["no_text_extracted"],
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_document_data(payload, requested_url, final_url, media_type=HTML_MEDIA_TYPE):
    """Route a downloaded payload to the extractor for its media type."""
    if is_pdf(payload, media_type):
        return extract_pdf_data(payload, requested_url, final_url)
    return extract_page_data(payload, requested_url, final_url)


# -------------- One source --------------

def scrape_source(source):
    """Download and extract one configured source, adding its identity."""
    print(f"Collecting {source['organisation']} - {source['source_id']}")

    payload, final_url, status_code, media_type = download_page(source["url"])
    data = extract_document_data(payload, source["url"], final_url, media_type)

    data["module"] = "visa_regulatory"
    data["source_id"] = source["source_id"]
    data["organisation"] = source["organisation"]
    data["source_group"] = source.get("source_group")
    data["source_role"] = source.get("source_role")
    data["primary_government_source"] = bool(source.get("primary_government_source"))
    data["http_status"] = status_code
    data["collection_method"] = "http"
    data["source_metadata"] = {k: v for k, v in source.items()
                               if k not in {"url", "source_id", "organisation"}}
    return data
