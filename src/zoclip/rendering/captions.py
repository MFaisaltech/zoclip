"""Generated ASS only; client text never enters a filter expression or ASS tag."""

import math
import unicodedata

from zoclip.rendering.schemas import Preferences


def escape(text: str) -> str:
    text = " ".join(text.split())
    return (
        "".join(c for c in text if not unicodedata.category(c).startswith("C"))
        .replace("\\", "＼")
        .replace("{", "｛")
        .replace("}", "｝")
    )


def words_for(prefs: Preferences, transcript: list[dict]) -> list[tuple[int, int, str]]:
    raw = [w.model_dump() for w in prefs.words] if prefs.words is not None else transcript
    words = []
    previous = prefs.start_ms
    for word in raw:
        try:
            if prefs.words is not None:
                start, end, text = word["start_ms"], word["end_ms"], word["text"]
            else:
                start, end = float(word["start"]) * 1000, float(word["end"]) * 1000
                text = word.get("punctuated_word", word["word"])
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
            start, end = max(round(start), previous, prefs.start_ms), min(round(end), prefs.end_ms)
            if end - start < 20 or not isinstance(text, str):
                continue
            # Extremely long tokens wrap deterministically; no arbitrary subtitle directives.
            text = escape(text)[:80]
            if not text:
                continue
            words.append((start - prefs.start_ms, end - prefs.start_ms, text))
            previous = end
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return words


def timestamp(ms: int) -> str:
    cs = max(0, ms // 10)
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def ass(prefs: Preferences, transcript: list[dict]) -> str:
    alignment = {"bottom": 2, "middle": 5, "top": 8}[prefs.placement]
    size = 42 if prefs.preset == "bold" else 36
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
[V4+ Styles]
{
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    }
{
        f"Style: Default,{prefs.font},{size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,3,1,{alignment},70,70,180,1"
    }
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if not prefs.captions:
        return header
    words = words_for(prefs, transcript)
    groups: list[list[tuple[int, int, str]]] = []
    for word in words:
        if (
            not groups
            or len(groups[-1]) >= 6
            or sum(len(w[2]) + 1 for w in groups[-1]) + len(word[2]) > 48
            or word[0] - groups[-1][-1][1] > 700
        ):
            groups.append([])
        groups[-1].append(word)
    events = []
    for group in groups:
        # Max 24 visible characters per line; max two lines per generated phrase.
        chunks: list[list[str]] = []
        line = 0
        for _, _, text in group:
            parts = [text[i : i + 24] for i in range(0, len(text), 24)]
            chunks.append(parts)

        def phrase(active: int | None, chunks: list[list[str]] = chunks) -> str:
            nonlocal line
            line = 0
            result = []
            for index, parts in enumerate(chunks):
                for part in parts:
                    if line and line + len(part) + 1 > 24:
                        result.append(r"\N")
                        line = 0
                    elif line:
                        result.append(" ")
                    if active == index:
                        result.append(r"{\c&H00FFFF&}")
                    result.append(part)
                    if active == index:
                        result.append(r"{\c&HFFFFFF&}")
                    line += len(part) + 1
            return "".join(result)

        intervals = (
            [(w[0], w[1], i) for i, w in enumerate(group)]
            if prefs.preset == "karaoke"
            else [(group[0][0], group[-1][1], None)]
        )
        for start, end, active in intervals:
            if end // 10 > start // 10:
                events.append(
                    f"Dialogue: 0,{timestamp(start)},{timestamp(end)},Default,,0,0,0,,"
                    + r"{\fad(20,20)}"
                    + phrase(active)
                    + "\n"
                )
    return header + "".join(events)
