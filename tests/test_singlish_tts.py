from pipecat_services.singlish_tts import normalize_singlish_for_tts, prepare_text_for_tts


def test_strips_lah_lor_leh():
    assert normalize_singlish_for_tts("Okay lah, I call back lor.") == "Okay, I call back."
    assert normalize_singlish_for_tts("You free leh?") == "You free?"


def test_hor_becomes_right():
    assert normalize_singlish_for_tts("You got time hor?") == "You got time right?"
    assert normalize_singlish_for_tts("Quite straightforward hor.") == "Quite straightforward, yeah."


def test_keeps_ah_and_english():
    assert normalize_singlish_for_tts("Hi from One CoSec, ah. Got a minute?") == (
        "Hi from One CoSec, ah. Got a minute?"
    )
    assert normalize_singlish_for_tts("Can walk you through.") == "Can walk you through."


def test_tag_only_returns_empty():
    assert normalize_singlish_for_tts("[chuckle]") == ""
    assert prepare_text_for_tts("[chuckle]") == ""


def test_skips_tool_leak_parens():
    assert prepare_text_for_tts("(") == ""
    assert prepare_text_for_tts("  )  ") == ""
