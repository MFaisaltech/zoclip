"""Deterministic on-box moment selection (no paid API).

Scores candidate windows of the assembled transcript with a feature
model, not a single keyword list:

- TF-IDF salience: terms weighted by how distinctive they are to this
  window versus the whole transcript (segment-level document frequency).
- Hook signals: questions, numbers, a hook lexicon.
- Arousal lexicon hits per 100 words (emotional peaks).
- Pause structure: fraction of the window that is internal silence
  (gaps > 0.35 s between words) — dead air is penalized.
- Speech density as a z-score against this video's own mean rate.
- Sentence completeness, mean word confidence, length fit.

Raw feature sums are converted to 0..100 with a z-score mapping across
all windows of the same video, so scores are calibrated per video.
Everything is O(words + windows); titles, hooks and keywords are taken
verbatim from the transcript — nothing is invented. The output shape
matches the Gemini path, so the shared ``selection.select_moments``
alignment/dedup stage and everything downstream stay identical.
"""

import math
import re
from collections import Counter

from zoclip.ai import selection
from zoclip.ai.schemas import Moment, Word
from zoclip.core.config import Settings

_HOOK_WORDS = {
    "secret",
    "never",
    "always",
    "stop",
    "mistake",
    "wrong",
    "money",
    "free",
    "truth",
    "nobody",
    "everyone",
    "warning",
    "important",
    "remember",
    "imagine",
    "believe",
    "actually",
    "suddenly",
    "shocking",
    "amazing",
    "best",
    "worst",
    "first",
}
_AROUSAL_WORDS = {
    "love",
    "hate",
    "afraid",
    "fear",
    "angry",
    "anger",
    "happy",
    "sad",
    "cry",
    "laugh",
    "shock",
    "shocked",
    "kill",
    "death",
    "dead",
    "alive",
    "pain",
    "hurt",
    "beautiful",
    "ugly",
    "crazy",
    "insane",
    "win",
    "lose",
    "lost",
    "fight",
    "war",
    "blood",
    "fire",
    "heart",
    "soul",
    "god",
    "hell",
    "heaven",
    "dream",
}
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "than",
    "so",
    "of",
    "at",
    "by",
    "for",
    "with",
    "to",
    "from",
    "in",
    "on",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "my",
    "your",
    "his",
    "her",
    "our",
    "their",
    "me",
    "him",
    "us",
    "them",
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "how",
    "why",
    "not",
    "no",
    "yes",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "will",
    "would",
    "can",
    "could",
    "should",
    "just",
    "like",
    "one",
    "get",
    "got",
    "going",
    "go",
    "know",
    "think",
    "really",
    "very",
}
_SENTENCE_END = (".", "!", "?")
_TOKEN = re.compile(r"[a-z0-9']+")
_MAX_CANDIDATES = 240
_PAUSE_GAP = 0.35


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(",;:") + "…"


def _content_tokens(text: str) -> list[str]:
    return [
        tok
        for tok in _TOKEN.findall(text.lower())
        if len(tok) >= 4 and tok not in _STOPWORDS and not tok.isdigit()
    ]


class _Window:
    __slots__ = ("start_idx", "words", "text", "raw", "factors", "keywords")

    def __init__(self, start_idx: int, words: list[Word], text: str) -> None:
        self.start_idx = start_idx
        self.words = words
        self.text = text
        self.raw = 0.0
        self.factors: list[str] = []
        self.keywords: list[str] = []


def candidates(words: list[Word], settings: Settings, count: int) -> list[Moment]:
    """Score transcript windows and return Moment candidates, best first."""
    if not words:
        return []
    segments = selection._segments(words)
    seg_texts = [" ".join(w.punctuated_word for w in group) for group in segments]
    seg_tokens = [_content_tokens(t) for t in seg_texts]

    # Document frequency across segments -> IDF for salience.
    n_seg = len(segments)
    doc_freq: Counter[str] = Counter()
    for toks in seg_tokens:
        doc_freq.update(set(toks))
    idf = {t: math.log((n_seg + 1) / (df + 1)) + 1.0 for t, df in doc_freq.items()}

    # Whole-video speech-rate stats for density z-scores.
    total_duration = max(words[-1].end - words[0].start, 0.01)
    mean_rate = len(words) / total_duration

    target = max(
        settings.ai_min_clip_seconds,
        min(
            settings.ai_max_clip_seconds,
            (settings.ai_min_clip_seconds + settings.ai_max_clip_seconds) // 2,
        ),
    )

    windows: list[_Window] = []
    for i, group in enumerate(segments):
        start = group[0].start
        window: list[Word] = []
        j = i
        while j < len(segments):
            window.extend(segments[j])
            duration = window[-1].end - start
            if duration >= target or duration > settings.ai_max_clip_seconds:
                break
            j += 1
        if not window:
            continue
        duration = window[-1].end - start
        if not settings.ai_min_clip_seconds <= duration <= settings.ai_max_clip_seconds:
            continue
        last = min(j, len(segments) - 1)
        text = " ".join(seg_texts[i : last + 1])
        win = _Window(i, window, text)

        # --- feature computation -------------------------------------
        win_tokens = [t for k in range(i, last + 1) for t in seg_tokens[k]]
        tf = Counter(win_tokens)
        salience = sum(c * idf[t] for t, c in tf.items()) / max(len(win_tokens), 1)
        win.raw += 6.0 * salience
        win.keywords = [
            t for t, _ in sorted(tf.items(), key=lambda kv: (-kv[1] * idf[kv[0]], kv[0]))[:5]
        ]

        lowered = text.lower()
        toks_all = _TOKEN.findall(lowered)
        if "?" in text:
            win.raw += 3.0
            win.factors.append("question hook")
        if any(ch.isdigit() for ch in text):
            win.raw += 1.5
            win.factors.append("mentions a number")
        hook_hits = sum(1 for t in toks_all if t in _HOOK_WORDS)
        if hook_hits:
            win.raw += min(4.0, 0.8 * hook_hits)
            win.factors.append(f"{hook_hits} hook word(s)")
        arousal = sum(1 for t in toks_all if t in _AROUSAL_WORDS)
        if arousal:
            win.raw += min(3.0, 0.6 * arousal)
            win.factors.append("emotional peak")

        silence = sum(
            max(0.0, window[k + 1].start - window[k].end)
            for k in range(len(window) - 1)
            if window[k + 1].start - window[k].end > _PAUSE_GAP
        )
        pause_ratio = silence / duration
        if pause_ratio > 0.10:
            win.raw -= min(4.0, (pause_ratio - 0.10) * 20)
            win.factors.append(f"{pause_ratio:.0%} dead air")

        density = len(window) / duration
        z = (density - mean_rate) / 0.9  # ~1 word/s spread across real speech
        win.raw += max(-2.0, min(3.0, z))
        win.factors.append(f"speech density {density:.1f} words/s")

        starts_sentence = i == 0 or seg_texts[i - 1].rstrip().endswith(_SENTENCE_END)
        ends_sentence = text.rstrip().endswith(_SENTENCE_END)
        if starts_sentence and ends_sentence:
            win.raw += 1.5
            win.factors.append("complete sentences")
        elif starts_sentence or ends_sentence:
            win.raw += 0.7

        confidence = sum(w.confidence for w in window) / len(window)
        win.raw += 2.0 * max(0.0, min(1.0, confidence))
        win.raw += 1.5 * max(0.0, 1 - abs(duration - 40) / 50)
        windows.append(win)

    if not windows:
        return []

    # --- per-video z-score calibration to 0..100 ----------------------
    raws = [w.raw for w in windows]
    mean = sum(raws) / len(raws)
    var = sum((r - mean) ** 2 for r in raws) / len(raws)
    std = math.sqrt(var) or 1.0

    found: list[Moment] = []
    for win in windows:
        score = max(0.0, min(100.0, 50 + 16 * (win.raw - mean) / std))
        sentences = _sentences(win.text)
        title = _trim(sentences[0] if sentences else win.text, 80) or "Clip"
        hook = _trim(" ".join(sentences[:2]) if sentences else win.text, 140) or title
        found.append(
            Moment(
                start_sec=win.words[0].start,
                end_sec=win.words[-1].end,
                title=title,
                hook=hook,
                reason="Local score: "
                + ("; ".join(win.factors) if win.factors else "steady segment"),
                score=round(score, 1),
                keywords=win.keywords,
                hashtags=["#" + k.replace("'", "") for k in win.keywords[:3]],
            )
        )
    found.sort(key=lambda m: (-m.score, m.start_sec, m.end_sec))
    return found[:_MAX_CANDIDATES]
