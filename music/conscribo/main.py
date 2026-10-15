#!/usr/bin/env python3
"""Download a MuseScore sheet as a PDF file of vector pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Protocol

import pymupdf
from curl_cffi import requests

JMUSE_URL = "https://musescore.com/api/jmuse"
# the site client signs every jmuse call with the first four hex digits of
# the md5 of score id, type, page index and this fixed suffix, concatenated;
# the suffix ships in clear text inside the public javascript bundle
SIGNING_SUFFIX = ",%!),"
RETRYABLE_API_STATUS = 422
MAX_RETRIES = 3
RETRY_DELAY_S = 2.0
# A4 in pdf points
A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89
TRAILING_ID_RE = re.compile(r"(\d+)/?$")


class ConscriboError(Exception):
    """A download step failed in a way the user can act on."""


class Session(Protocol):
    """The HTTP surface the downloader needs from a session."""

    def get(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        """Fetch a URL. Return the HTTP status and the response body."""
        ...


class HttpSession:
    """A session that keeps the cookies the site sets on the first fetch.

    The transport impersonates the Chrome network fingerprint. The site
    refuses plain HTTP clients from some networks on fingerprint alone.
    """

    def __init__(self) -> None:
        self._session = requests.Session(impersonate="chrome")

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


def download_pages(session: Session, page_url: str) -> list[bytes]:
    """Download every page of the sheet as SVG bytes, in sheet order.

    The session must have fetched the score page first: the API only
    answers requests that carry the cookies of that first fetch.
    """
    sid = score_id(page_url)
    pages: list[bytes] = []
    index = 0
    while True:
        signed = signed_page_url(session, sid, index, page_url)
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


def run(url: str, output: Path, session: Session) -> int:
    """Download the sheet at the URL and write the PDF to the output path."""
    # the first fetch sets the session cookies; without the cookies the API
    # refuses every later request
    status, _ = session.get(url)
    if status != 200:
        raise ConscriboError(f"score page fetch failed with http {status}")
    pages = download_pages(session, url)
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
    args = parser.parse_args(argv)
    try:
        output = args.output or Path(f"{score_id(args.url)}.pdf")
        return run(args.url, output, HttpSession())
    except ConscriboError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
