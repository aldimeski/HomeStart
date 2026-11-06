"""Separates ICY metadata (the current track title) from the audio of a stream."""

import re

MAX_TITLE_LENGTH = 200
_STREAM_TITLE = re.compile(rb"StreamTitle='(.*?)';", re.DOTALL)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def decode_title(raw: bytes) -> str | None:
    match = _STREAM_TITLE.search(raw)
    if match is None:
        return None
    try:
        text = match.group(1).decode("utf-8")
    except UnicodeDecodeError:
        text = match.group(1).decode("latin-1")
    text = _CONTROL_CHARS.sub("", text).strip()
    return text[:MAX_TITLE_LENGTH] or None


class IcyDemuxer:
    """Passes audio through and picks the metadata blocks out of it.

    The station sends `metaint` bytes of audio, then one length byte (times 16) and that many metadata bytes.
    """

    def __init__(self, metaint: int):
        self.metaint = metaint
        self.title: str | None = None
        self._audio_left = metaint
        self._meta_left = -1  # -1: the length byte is next
        self._meta = bytearray()

    def feed(self, data: bytes) -> bytes:
        out = bytearray()
        view = memoryview(data)
        pos = 0
        while pos < len(view):
            if self._audio_left > 0:
                take = min(self._audio_left, len(view) - pos)
                out += view[pos : pos + take]
                pos += take
                self._audio_left -= take
            elif self._meta_left < 0:
                self._meta_left = view[pos] * 16
                pos += 1
                self._meta.clear()
                if self._meta_left == 0:
                    self._finish_block()
            else:
                take = min(self._meta_left, len(view) - pos)
                self._meta += view[pos : pos + take]
                pos += take
                self._meta_left -= take
                if self._meta_left == 0:
                    self._finish_block()
        return bytes(out)

    def _finish_block(self) -> None:
        if self._meta:
            # An empty block means "unchanged"; a block without a title clears it.
            self.title = decode_title(bytes(self._meta))
        self._meta_left = -1
        self._audio_left = self.metaint
