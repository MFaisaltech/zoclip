"""Generation quotes sell exactly 1-6 clips; internal pricing math is wider."""

import pytest
from pydantic import ValidationError

from zoclip.credits.schemas import GenerationQuoteInput, QuoteInput


def test_generation_quote_accepts_one_to_six_clips():
    for count in (1, 2, 3, 4, 5, 6):
        assert GenerationQuoteInput(source_seconds=60, output_count=count).output_count == count


def test_generation_quote_rejects_seven_or_more_clips():
    with pytest.raises(ValidationError):
        GenerationQuoteInput(source_seconds=60, output_count=7)
    with pytest.raises(ValidationError):
        GenerationQuoteInput(source_seconds=60, output_count=0)


def test_internal_quote_math_keeps_its_wider_bound():
    assert QuoteInput(source_seconds=60, output_count=10).output_count == 10
