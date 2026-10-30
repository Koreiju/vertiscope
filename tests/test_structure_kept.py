"""`domvec.analytics.structure_kept` (G-48): headers, fields and formatting
reach the encoder. Non-vacuity: the encoder's own string keeps them; the
planted plain-text string loses them; a chunk with no structure is not asked."""

from domvec import models, tokens
from domvec.analytics.structure_kept import elements, score

PANEL = ("## Bitcoin price today\n\n| Name | Price | 24h % |\n|---|---|---|\n| [Bitcoin](https://x/btc) | $67,000 | 1.2% |\n\n"
         "**Market cap** $1.3T\n\nCryptos : [2.4M](https://x/c)\n")


def test_the_panel_structure_is_found():
    es = elements(PANEL)
    assert "## Bitcoin price today" in es and "| Name | Price | 24h % |" in es
    assert "**Market cap**" in es and "Cryptos :" in es


def test_encoder_keeps_it_and_plain_text_loses_it():
    good = score([PANEL, "just words, no structure"], tokens.for_model)
    bad = score([PANEL], models.plain)
    assert good["chunks_with_structure"] == 1 and good["share"] == 1.0
    assert bad["share"] < 0.5
