import pytest

from coach.llm.client import ask_structured
from coach.llm.provider import ClaudeCliProvider
from coach.llm.schemas import AdjustmentResponse


@pytest.mark.live
def test_cli_roundtrip():
    out = ask_structured(
        ClaudeCliProvider(),
        'Réponds uniquement avec un objet JSON, sans texte autour.',
        'Renvoie {"analysis": "ok", "changes": []} exactement.',
        AdjustmentResponse,
    )
    assert out.analysis
