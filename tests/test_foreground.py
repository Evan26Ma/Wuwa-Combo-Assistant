from wuwa_assistant import foreground


def test_assistant_window_is_not_mistaken_for_game(monkeypatch):
    for title in ("鸣潮逐键教练设置", "鸣潮逐键提示", "鸣潮 · 连招教练"):
        monkeypatch.setattr(foreground, "foreground_window_title", lambda value=title: value)
        assert not foreground.is_game_foreground(["鸣潮", "Wuthering Waves"])


def test_real_game_title_matches(monkeypatch):
    monkeypatch.setattr(foreground, "foreground_window_title", lambda: "鸣潮")
    assert foreground.is_game_foreground(["鸣潮", "Wuthering Waves"])
