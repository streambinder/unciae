"""Unit tests for the conscribo runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import main
import pymupdf
import pytest

SCORE_URL = "https://musescore.com/user/19710/scores/4766391"
SCORE_ID = "4766391"
TINY_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="140">'
    b'<rect width="100" height="140" fill="white"/></svg>'
)


def page_count(pdf: bytes) -> int:
    return len(pymupdf.open(stream=pdf, filetype="pdf"))


def jmuse_body(signed_url: str) -> bytes:
    return json.dumps({"status": 200, "info": {"url": signed_url}}).encode()


class FakeSession:
    """A session that answers from a script of queued responses per URL."""

    def __init__(self, script: dict[str, list[tuple[int, bytes]]]) -> None:
        self.script = {url: list(responses) for url, responses in script.items()}
        self.calls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        self.calls.append(url)
        responses = self.script[url]
        return responses.pop(0) if len(responses) > 1 else responses[0]


def jmuse_url(index: int) -> str:
    return f"https://musescore.com/api/jmuse?id={SCORE_ID}&index={index}&type=img"


def two_page_session() -> FakeSession:
    return FakeSession(
        {
            SCORE_URL: [(200, b"<html></html>")],
            jmuse_url(0): [(200, jmuse_body("https://s3w.example/score_0.svg"))],
            jmuse_url(1): [(200, jmuse_body("https://s3w.example/score_1.svg"))],
            jmuse_url(2): [(200, jmuse_body("https://s3w.example/score_2.svg"))],
            "https://s3w.example/score_0.svg": [(200, TINY_SVG)],
            "https://s3w.example/score_1.svg": [(200, TINY_SVG)],
            "https://s3w.example/score_2.svg": [(404, b"not found")],
        }
    )


def test_score_id_from_score_url() -> None:
    assert main.score_id(SCORE_URL) == SCORE_ID
    assert main.score_id(f"{SCORE_URL}?from=nav") == SCORE_ID


def test_score_id_from_song_url() -> None:
    assert main.score_id("https://musescore.com/song/gymnopedie_no1-2336710") == ("2336710")


def test_score_id_missing() -> None:
    with pytest.raises(main.ConscriboError):
        main.score_id("https://musescore.com/")


def test_token_shape_and_format() -> None:
    expected = hashlib.md5(b"4766391img1,%!),").hexdigest()[:4]
    assert main.token(SCORE_ID, 1) == expected
    assert len(main.token(SCORE_ID, 0)) == 4


def test_signed_page_url_success() -> None:
    session = FakeSession({jmuse_url(2): [(200, jmuse_body("https://s3w.example/score_2.svg"))]})
    assert main.signed_page_url(session, SCORE_ID, 2, SCORE_URL) == (
        "https://s3w.example/score_2.svg"
    )


def test_signed_page_url_retries_on_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: None)
    refused = json.dumps({"status": 422, "info": None}).encode()
    session = FakeSession(
        {
            jmuse_url(0): [
                (200, refused),
                (200, jmuse_body("https://s3w.example/score_0.svg")),
            ]
        }
    )
    assert main.signed_page_url(session, SCORE_ID, 0, SCORE_URL) == (
        "https://s3w.example/score_0.svg"
    )
    assert session.calls == [jmuse_url(0), jmuse_url(0)]


def test_signed_page_url_raises_on_refusal() -> None:
    refused = json.dumps({"status": 403, "info": None}).encode()
    session = FakeSession({jmuse_url(0): [(403, refused)]})
    with pytest.raises(main.ConscriboError):
        main.signed_page_url(session, SCORE_ID, 0, SCORE_URL)


def test_download_pages_stops_at_first_missing_page() -> None:
    session = two_page_session()
    session.get(SCORE_URL)
    assert main.download_pages(session, SCORE_URL) == [TINY_SVG, TINY_SVG]


def test_download_pages_raises_when_no_page_exists() -> None:
    session = FakeSession(
        {
            jmuse_url(0): [(200, jmuse_body("https://s3w.example/score_0.svg"))],
            "https://s3w.example/score_0.svg": [(404, b"not found")],
        }
    )
    with pytest.raises(main.ConscriboError):
        main.download_pages(session, SCORE_URL)


def test_download_pages_raises_on_fetch_error() -> None:
    session = FakeSession(
        {
            jmuse_url(0): [(200, jmuse_body("https://s3w.example/score_0.svg"))],
            "https://s3w.example/score_0.svg": [(500, b"boom")],
        }
    )
    with pytest.raises(main.ConscriboError):
        main.download_pages(session, SCORE_URL)


def test_page_pdf_renders_a_pdf() -> None:
    assert main.page_pdf(TINY_SVG).startswith(b"%PDF")


def test_assemble_pdf_merges_pages() -> None:
    merged = main.assemble_pdf([TINY_SVG, TINY_SVG])
    assert page_count(merged) == 2


def test_run_writes_the_pdf(tmp_path: Path) -> None:
    output = tmp_path / "sheet.pdf"
    assert main.run(SCORE_URL, output, two_page_session()) == 0
    assert page_count(output.read_bytes()) == 2


def test_run_raises_when_the_page_fetch_fails() -> None:
    session = FakeSession({SCORE_URL: [(503, b"boom")]})
    with pytest.raises(main.ConscriboError):
        main.run(SCORE_URL, Path("unused.pdf"), session)


def test_main_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "HttpSession", two_page_session)
    assert main.main([SCORE_URL]) == 0
    assert (tmp_path / f"{SCORE_ID}.pdf").exists()


def test_main_reports_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_session() -> FakeSession:
        return FakeSession({SCORE_URL: [(503, b"boom")]})

    monkeypatch.setattr(main, "HttpSession", broken_session)
    assert main.main([SCORE_URL]) == 1
    assert main.main(["https://musescore.com/"]) == 1


class StubTransportResponse:
    """A minimal stand-in for a transport response."""

    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


class StubTransportSession:
    """A transport session that returns a canned response or raises."""

    def __init__(self, outcome: StubTransportResponse | Exception) -> None:
        self.outcome = outcome

    def get(self, _url: str, headers: Any = None, timeout: int = 0) -> StubTransportResponse:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def stub_session(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> main.HttpSession:
    transport = StubTransportSession(outcome)
    monkeypatch.setattr(main.requests, "Session", lambda **_kwargs: transport)
    return main.HttpSession()


def test_http_session_get_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session = stub_session(monkeypatch, StubTransportResponse(200, b"body"))
    assert session.get("https://example.com") == (200, b"body")


def test_http_session_get_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = stub_session(monkeypatch, StubTransportResponse(404, b"nope"))
    assert session.get("https://example.com") == (404, b"nope")


def test_http_session_get_request_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = main.requests.exceptions.RequestException("boom")
    session = stub_session(monkeypatch, failure)
    with pytest.raises(main.ConscriboError):
        session.get("https://example.com")
