"""
Turn raw Whisper output into cleanly formatted text.

Whisper transcribes literally: it auto-punctuates commas/periods from prosody
but writes spoken symbol names ("exclamation point") as words. This module maps
those spoken commands to symbols, then tidies spacing and capitalization.

Deliberately conservative: comma/period are left to Whisper's own
auto-punctuation (remapping them collides with normal words like "the Jurassic
period"). Only symbols Whisper can't infer are mapped, and only as whole-word
matches.
"""
import re


def _replace_commands(text, commands):
    # Longer phrases first so "close parenthesis" wins over "parenthesis".
    for phrase, repl in sorted(commands.items(), key=lambda kv: -len(kv[0])):
        # Whole-word, case-insensitive. Allow an optional trailing period that
        # Whisper may have appended (e.g. "Exclamation point.").
        pattern = r"(?<![\w])" + re.escape(phrase) + r"\.?(?![\w])"
        text = re.sub(pattern, lambda m: repl, text, flags=re.IGNORECASE)
    return text


def _fix_spacing(text):
    text = re.sub(r"[ \t]+([,.!?;:])", r"\1", text)   # no space before punctuation
    text = re.sub(r"\(\s+", "(", text)                 # no space after (
    text = re.sub(r"\s+\)", ")", text)                 # no space before )
    # Trim spaces just inside a balanced quote pair: " hello " -> "hello".
    text = re.sub(r'"[ \t]*(.*?)[ \t]*"', r'"\1"', text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)       # trim spaces around newlines
    text = re.sub(r"[ \t]{2,}", " ", text)             # collapse runs of spaces
    return text


def _fix_caps(text):
    # First letter of the text.
    text = re.sub(r"^(\s*[\"'(]?\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    # First letter after sentence-ending punctuation or a newline.
    text = re.sub(
        r"([.!?]\s+|\n+\s*)([\"'(]?)([a-z])",
        lambda m: m.group(1) + m.group(2) + m.group(3).upper(),
        text,
    )
    return text


def format_text(text, commands=None, smart_formatting=True):
    if not text:
        return text
    if commands:
        text = _replace_commands(text, commands)
    if smart_formatting:
        text = _fix_spacing(text)
        text = _fix_caps(text)
    return text.strip()


if __name__ == "__main__":
    cmds = {
        "new paragraph": "\n\n",
        "new line": "\n",
        "exclamation point": "!",
        "question mark": "?",
        "open paren": "(",
        "close paren": ")",
        "colon": ":",
        "open quote": '"',
        "close quote": '"',
    }
    tests = [
        ("she said open quote hello close quote to me", 'She said "hello" to me'),
        ("that is great Exclamation point.", "That is great!"),
        ("is it ready question mark", "Is it ready?"),
        ("first line new line second line", "First line\nSecond line"),
        ("point one new paragraph point two", "Point one\n\nPoint two"),
        ("the note open paren important close paren here", "The note (important) here"),
        ("during the Jurassic period the earth", "During the Jurassic period the earth"),
    ]
    ok = True
    for raw, expected in tests:
        got = format_text(raw, cmds)
        flag = "OK " if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"{flag} | {raw!r} -> {got!r}")
    print("ALL OK" if ok else "SOME FAILED")
