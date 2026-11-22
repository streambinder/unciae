#!/usr/bin/env python3
"""Download a MuseScore sheet as a PDF file of vector pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pymupdf
from curl_cffi import requests

JMUSE_URL = "https://musescore.com/api/jmuse"
# the site client signs every jmuse call with the first four hex digits of
# the md5 of score id, type, page index and this fixed suffix, concatenated;
# the suffix ships in clear text inside the public javascript bundle
SIGNING_SUFFIX = "0101"
# browser fingerprints to try, in order, when the site refuses one with
# http 403; the first entry is the default, the others are fallbacks
IMPERSONATE_CANDIDATES = ("chrome", "chrome131", "safari18_0")
RETRYABLE_API_STATUS = 422
MAX_RETRIES = 3
RETRY_DELAY_S = 2.0
# A4 in pdf points
A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89
TRAILING_ID_RE = re.compile(r"(\d+)/?$")
CANONICAL_LINK_RE = re.compile(
    r'<link[^>]*rel="canonical"[^>]*href="([^"]+)"'
    r'|<link[^>]*href="([^"]+)"[^>]*rel="canonical"'
)
META_URL_RE = re.compile(
    r'<meta[^>]*property="(?:og:url|al:web:url)"[^>]*content="([^"]+)"'
    r'|<meta[^>]*content="([^"]+)"[^>]*property="(?:og:url|al:web:url)"'
)
SCORE_LINK_RE = re.compile(r"/scores/(\d+)")


class ConscriboError(Exception):
    """A download step failed in a way the user can act on."""


class Session(Protocol):
    """The HTTP surface the downloader needs from a session."""

    def get(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        """Fetch a URL. Return the HTTP status and the response body."""
        ...


class HttpSession:
    """A session that keeps the cookies the site sets on the first fetch.

    The transport impersonates a browser network fingerprint. The site
    refuses plain HTTP clients from some networks on fingerprint alone,
    and a fingerprint can burn out after a burst of requests: pass
    another one when the site starts refusing the default.
    """

    def __init__(self, impersonate: str = "chrome") -> None:
        self._session = requests.Session(impersonate=impersonate)

    def get(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        try:
            response = self._session.get(url, headers=headers, timeout=30)
        except requests.exceptions.RequestException as error:
            raise ConscriboError(f"request failed: {error}") from error
        return response.status_code, response.content


def score_id(url: str) -> str:
    """Extract the trailing numeric score id from a score page URL."""
    path = url.split("?")[0].split("#")[0].rstrip("/")
    match = TRAILING_ID_RE.search(path)
    if match is None:
        raise ConscriboError(f"no score id in URL: {url}")
    return match.group(1)


def resolve_score_id(page: bytes, url: str) -> str:
    """Find the score id in a fetched score page.

    The page carries its own canonical address. Fall back to the most
    frequent score link when the page has no canonical address.
    """
    text = page.decode("utf-8", "ignore")
    for pattern in (CANONICAL_LINK_RE, META_URL_RE):
        match = pattern.search(text)
        if match is None:
            continue
        href: str = next(group for group in match.groups() if group is not None)
        found = TRAILING_ID_RE.search(href.split("?")[0].split("#")[0].rstrip("/"))
        if found is not None:
            return found.group(1)
    links: list[str] = SCORE_LINK_RE.findall(text)
    if links:
        return max(set(links), key=links.count)
    raise ConscriboError(f"no score id in page: {url}")


def token(sid: str, index: int) -> str:
    """Compute the authorization token of one jmuse page request."""
    digest = hashlib.md5(f"{sid}img{index}{SIGNING_SUFFIX}".encode())
    return digest.hexdigest()[:4]


def signed_page_url(session: Session, sid: str, index: int, referer: str) -> str:
    """Ask the jmuse API for the signed URL of one sheet page.

    The API signs a URL for any index, existing page or not. The caller
    detects the end of the sheet from the page fetch itself.
    """
    url = f"{JMUSE_URL}?id={sid}&index={index}&type=img"
    headers = {
        "authorization": token(sid, index),
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    }
    for attempt in range(MAX_RETRIES + 1):
        status, body = session.get(url, headers)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        api_status = payload.get("status") if isinstance(payload, dict) else None
        if api_status == RETRYABLE_API_STATUS and attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_S)
            continue
        info = payload.get("info") if isinstance(payload, dict) else None
        signed = info.get("url") if isinstance(info, dict) else None
        if status == 200 and api_status == 200 and isinstance(signed, str):
            return signed
        raise ConscriboError(f"jmuse refused page {index}: http {status}, api {api_status}")
    raise ConscriboError(f"jmuse kept refusing page {index} after retries")


def download_pages(session: Session, sid: str, referer: str) -> list[bytes]:
    """Download every page of the sheet as SVG bytes, in sheet order.

    The session must have fetched the score page first: the API only
    answers requests that carry the cookies of that first fetch.
    """
    pages: list[bytes] = []
    index = 0
    while True:
        signed = signed_page_url(session, sid, index, referer)
        status, body = session.get(signed)
        if status == 404:
            break
        if status != 200:
            raise ConscriboError(f"page {index} fetch failed with http {status}")
        pages.append(body)
        index += 1
    if not pages:
        raise ConscriboError("the sheet exposes no page to download")
    return pages


def assemble_pdf(pages: list[bytes]) -> bytes:
    """Assemble SVG pages into one PDF document, in sheet order."""
    # pymupdf ships partial type information: the document calls are untyped
    output = pymupdf.open()  # type: ignore[no-untyped-call]
    for svg in pages:
        source = pymupdf.open(stream=svg, filetype="svg")  # type: ignore[no-untyped-call]
        inner = pymupdf.open("pdf", source.convert_to_pdf())  # type: ignore[no-untyped-call]
        page = output.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
        page.show_pdf_page(page.rect, inner, 0)
    return output.tobytes()  # type: ignore[no-any-return, no-untyped-call]


def page_pdf(svg: bytes) -> bytes:
    """Render one SVG page to a one-page A4 PDF."""
    return assemble_pdf([svg])


def fetch_score_page(
    url: str, make_session: Callable[[str], Session], impersonate: str
) -> tuple[Session, bytes]:
    """Fetch the score page, rotating fingerprints on a 403 refusal.

    The preferred fingerprint goes first, then the other candidates.
    A refusal other than 403 is final: another fingerprint will not fix it.
    """
    candidates = [impersonate, *[c for c in IMPERSONATE_CANDIDATES if c != impersonate]]
    for candidate in candidates:
        session = make_session(candidate)
        status, body = session.get(url)
        if status == 200:
            return session, body
        if status != 403:
            raise ConscriboError(f"score page fetch failed with http {status}")
        print(f"fingerprint {candidate} refused with http 403, trying next", file=sys.stderr)
    raise ConscriboError("score page fetch failed with http 403")


def run(
    url: str,
    output: Path | None,
    make_session: Callable[[str], Session],
    impersonate: str = "chrome",
) -> int:
    """Download the sheet at the URL and write the PDF to the output path."""
    # the first fetch sets the session cookies; without the cookies the API
    # refuses every later request
    session, body = fetch_score_page(url, make_session, impersonate)
    try:
        sid = score_id(url)
    except ConscriboError:
        sid = resolve_score_id(body, url)
    pages = download_pages(session, sid, url)
    output = output or Path(f"{sid}.pdf")
    output.write_bytes(assemble_pdf(pages))
    print(f"pages: {len(pages)}", file=sys.stderr)
    print(f"written: {output}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="MuseScore score page URL")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output PDF path (default: <score id>.pdf)",
    )
    parser.add_argument(
        "--impersonate",
        default="chrome",
        help="browser fingerprint to try first (default: chrome)",
    )
    args = parser.parse_args(argv)
    try:
        return run(args.url, args.output, HttpSession, args.impersonate)
    except ConscriboError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
