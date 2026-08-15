from truckerworld_bot.embeds import DANGER_COLOR, error_embed


def test_error_embed_uses_default_title_for_a_single_message() -> None:
    embed = error_embed("The request failed.")

    assert embed.title == "Something went wrong"
    assert embed.description == "The request failed."
    assert embed.color == DANGER_COLOR


def test_error_embed_accepts_a_custom_title_and_message() -> None:
    embed = error_embed("Continue your existing support case", "Open TWMP Support to continue.")

    assert embed.title == "Continue your existing support case"
    assert embed.description == "Open TWMP Support to continue."
    assert embed.color == DANGER_COLOR
