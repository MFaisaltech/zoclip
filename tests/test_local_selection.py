"""Deterministic local moment selection: no network, no provider calls."""

import pytest

from zoclip.ai import local_selection, selection
from zoclip.ai.schemas import Word
from zoclip.core.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused:unused@localhost/local_selection_test",
        media_root=str(tmp_path),
    )


def make_words(sentences, start=0.0, gap=0.06, word_seconds=0.32, confidence=0.9):
    words = []
    t = start
    for sentence in sentences:
        for tok in sentence.split():
            words.append(
                Word(
                    word=tok.strip(".,!?"),
                    punctuated_word=tok,
                    start=round(t, 3),
                    end=round(t + word_seconds, 3),
                    confidence=confidence,
                )
            )
            t += word_seconds + gap
        t += 0.2
    return words


FILLER = "the team talked about the schedule and the plan for the week ahead."
HOOK = "why did nobody tell you this secret about money and freedom?"


def test_candidates_feed_select_moments(settings):
    sentences = [FILLER] * 30 + [HOOK] + [FILLER] * 30 + [HOOK] + [FILLER] * 30
    words = make_words(sentences)
    found = local_selection.candidates(words, settings, 10)
    assert found, "expected candidates"
    assert all(
        settings.ai_min_clip_seconds <= m.end_sec - m.start_sec <= settings.ai_max_clip_seconds
        for m in found
    )
    chosen = selection.select_moments(found, words, int(words[-1].end) + 1, settings, 3)
    assert 1 <= len(chosen) <= 3
    for a, b in zip(chosen, chosen[1:]):
        assert a.end_sec <= b.start_sec or b.end_sec <= a.start_sec


def test_question_window_outranks_filler(settings):
    words = make_words([FILLER] * 12 + [HOOK])
    found = local_selection.candidates(words, settings, 10)
    assert found
    hook_start = next(w.start for w in words if w.punctuated_word == "why")
    best = found[0]
    assert best.start_sec <= hook_start < best.end_sec


def test_dead_air_scores_below_continuous_speech(settings):
    text = [HOOK] + [FILLER] * 6
    tight = make_words(text * 2)
    sparse_start = tight[-1].end + 1.0
    sparse = make_words(text * 3, start=sparse_start, gap=1.2)  # same words, long pauses
    words = tight + sparse
    found = local_selection.candidates(words, settings, 10)
    tight_best = max(m.score for m in found if m.end_sec <= sparse_start)
    sparse_best = max(m.score for m in found if m.start_sec >= sparse_start)
    assert tight_best > sparse_best


def test_empty_transcript_no_candidates(settings):
    assert local_selection.candidates([], settings, 10) == []
