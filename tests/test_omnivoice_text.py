from tts.text_utils import split_synthesis_text


def test_short_text_is_not_split():
    assert split_synthesis_text("Xin chào mọi người.") == ["Xin chào mọi người."]


def test_long_text_is_split_without_losing_words():
    text = (
        "Xin chào mọi người đã đến với buổi livestream. "
        "Nếu bạn đang quan tâm sản phẩm nào, hãy để lại tên sản phẩm và nhu cầu, "
        "mình sẽ tư vấn ngay nhé."
    )

    segments = split_synthesis_text(text, max_chars=70)

    assert len(segments) > 1
    assert all(len(segment) <= 70 for segment in segments)
    assert " ".join(segments) == text
