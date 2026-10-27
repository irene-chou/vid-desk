import pytest

from vid_snatch.core import clean_url


@pytest.mark.parametrize("raw,expected", [
    ("https://www.youtube.com/watch?v=abc123", "https://www.youtube.com/watch?v=abc123"),
    ("  https://youtu.be/abc123?si=xyz  ", "https://youtu.be/abc123"),
    ("https://www.youtube.com/watch?v=abc123&list=PL1&index=3&t=42s", "https://www.youtube.com/watch?v=abc123"),
    ("youtube.com/shorts/abc123", "https://youtube.com/shorts/abc123"),
    ("https://www.youtube.com/live/abc123?feature=share", "https://www.youtube.com/live/abc123"),
    ("https://music.youtube.com/watch?v=abc123&feature=share", "https://music.youtube.com/watch?v=abc123"),
    ("　https://youtu.be/abc123　", "https://youtu.be/abc123"),
])
def test_clean_url_valid(raw, expected):
    assert clean_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "https://vimeo.com/123", "not a url", "https://www.youtube.com/playlist?list=PL1"])
def test_clean_url_invalid(raw):
    assert clean_url(raw) is None
