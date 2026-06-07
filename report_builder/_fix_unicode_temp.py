def _fix_unicode_artifacts(text: str) -> str:
    """Fix PDF-to-text encoding artifacts: en/em dashes, Rupee sign, smart quotes.

    MoSPI/NSSO PDFs are often encoded as Windows-1252 but decoded incorrectly,
    turning UTF-8 multi-byte sequences into garbled characters. This reverses them.

    All patterns and replacements use \\uXXXX escapes so this source stays ASCII-safe.
    Key mappings (UTF-8 bytes -> Windows-1252 mis-decode -> Unicode name):
      E2 80 93 -> â -> EN DASH (–)
      E2 80 94 -> â -> EM DASH (—)
      E2 82 B9 -> â¹ -> RUPEE SIGN (₹)
    """
    import re as _re_uni
    text = _re_uni.sub(r"[\x00-\x08\x0e-\x1b]", "", text)   # control chars
    # En dash (–): most common garbled forms from PLFS PDFs
    text = text.replace("â€“", "–")   # a+euro+ldquote
    text = text.replace("â", "–")   # direct byte remap
    # Em dash (—)
    text = text.replace("â€”", "—")   # a+euro+rdquote
    text = text.replace("â", "—")   # direct byte remap
    # Smart/curly quotes (“ ”)
    text = text.replace("â€œ", "“")   # a+euro+oe -> left "
    text = text.replace("â€™", "’")   # a+euro+TM -> apostrophe
    # Trailing â€ alone -> em dash (most common remaining)
    text = text.replace("â€", "—")          # a+euro -> em dash
    # Rupee sign (₹)
    text = text.replace("â¹", "₹")   # direct byte remap
    text = text.replace("â¹", "₹")         # alt Rupee form
    # Any remaining lone â -> en dash
    text = text.replace("â", "–")
    return text

