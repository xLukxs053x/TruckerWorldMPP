from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader

from truckerworld_bot.transcript import TranscriptMessage, build_ticket_transcript


def test_builds_readable_branded_ticket_transcript() -> None:
    timestamp = datetime(2026, 8, 15, 12, 30, tzinfo=timezone.utc)
    pdf, count = build_ticket_transcript(
        reference="SUP-000042",
        subject="Launcher update fails",
        category="Launcher",
        requester="RoadPilot",
        opened_at=timestamp,
        closed_by="SupportAgent",
        generated_at=timestamp,
        messages=[
            TranscriptMessage(
                author="RoadPilot",
                author_id=123456789012345678,
                created_at=timestamp,
                content="The launcher stops at 80%.\nI already restarted it.",
                attachments=("https://example.test/error.png",),
            ),
            TranscriptMessage(
                author="SupportAgent",
                author_id=876543210987654321,
                created_at=timestamp,
                content="Thanks - please clear the download cache and retry.",
            ),
        ],
    )
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert pdf.startswith(b"%PDF-")
    assert count == 2
    assert "SUP-000042" in text
    assert "Launcher update fails" in text
    assert "The launcher stops at 80%" in text
    assert "Private support record" in text
