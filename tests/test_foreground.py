from wuwa_assistant import foreground


def test_assistant_window_is_not_mistaken_for_game(monkeypatch):
    monkeypatch.setattr(foreground, "foreground_window_title", lambda: "鸣潮逐键教练设置")
    assert not foreground.is_game_foreground(["鸣潮", "Wuthering Waves"])


def test_real_game_title_matches(monkeypatch):
    monkeypatch.setattr(foreground, "foreground_window_title", lambda: "鸣潮")
    assert foreground.is_game_foreground(["鸣潮", "Wuthering Waves"])
