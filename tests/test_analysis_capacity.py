from zoclip.ai.schemas import Word
from zoclip.ai.selection import analysis_data, chunks, prompt
from zoclip.core.config import Settings


def test_two_hour_podcast_fits_bounded_analysis_without_losing_caption_words():
    words = [
        Word(
            word="insight",
            punctuated_word="Insight.",
            start=i / 3,
            end=(i + 0.8) / 3,
            confidence=0.9,
        )
        for i in range(21600)
    ]
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://local/local")
    groups = list(chunks(words, settings))
    assert 1 < len(groups) <= settings.ai_max_chunks
    assert all(len(analysis_data(group).encode()) <= settings.ai_chunk_bytes for group in groups)
    assert {word.start for group in groups for word in group} == {word.start for word in words}
    assert groups[-1][-1] is words[-1]
    assert '"confidence"' not in prompt(groups[0], settings, 3)
    assert '"text":"Insight.' in prompt(groups[0], settings, 3)
    assert words[0].confidence == 0.9  # Full word-level caption data remains intact.
