from wuwa_assistant.input_monitor import InputMonitor, VK_CODES


def test_keyboard_press_emits_without_blocking():
    states = {VK_CODES["E"]: False}
    events = []
    monitor = InputMonitor({"skill": "E"}, events.append, state_reader=lambda vk: states[vk])
    monitor.poll_once(now=1.0)
    states[VK_CODES["E"]] = True
    monitor.poll_once(now=1.1)
    states[VK_CODES["E"]] = False
    monitor.poll_once(now=1.2)
    assert [event.action for event in events] == ["skill"]


def test_mouse_release_distinguishes_click_and_hold():
    left = VK_CODES["MOUSE_LEFT"]
    states = {left: False}
    events = []
    monitor = InputMonitor(
        {"basic": "MOUSE_LEFT", "heavy": "MOUSE_LEFT"}, events.append,
        heavy_hold_ms=350, state_reader=lambda vk: states[vk],
    )
    states[left] = True
    monitor.poll_once(now=1.0)
    states[left] = False
    monitor.poll_once(now=1.1)
    states[left] = True
    monitor.poll_once(now=2.0)
    states[left] = False
    monitor.poll_once(now=2.5)
    assert [(event.action, event.held_ms) for event in events] == [("basic", 100), ("heavy", 500)]


def test_inactive_monitor_releases_state_without_emitting():
    left = VK_CODES["MOUSE_LEFT"]
    states = {left: True}
    events = []
    monitor = InputMonitor({"basic": "MOUSE_LEFT"}, events.append, state_reader=lambda vk: states[vk])
    monitor.poll_once(now=1.0, active=False)
    assert events == []


def test_both_reset_keys_are_observed_independently():
    states = {VK_CODES["ESC"]: False, VK_CODES["F8"]: False}
    events = []
    monitor = InputMonitor(
        {"reset_primary": "ESC", "reset_secondary": "F8"},
        events.append,
        state_reader=lambda vk: states[vk],
    )
    monitor.poll_once(now=1.0)
    states[VK_CODES["ESC"]] = True
    monitor.poll_once(now=1.1)
    states[VK_CODES["ESC"]] = False
    monitor.poll_once(now=1.2)
    states[VK_CODES["F8"]] = True
    monitor.poll_once(now=1.3)
    assert [event.action for event in events] == ["reset_primary", "reset_secondary"]


def test_overlay_toggle_hotkey_emits_on_key_press():
    states = {VK_CODES["F7"]: False}
    events = []
    monitor = InputMonitor(
        {"toggle_overlay": "F7"}, events.append,
        state_reader=lambda vk: states[vk],
    )
    monitor.poll_once(now=1.0)
    states[VK_CODES["F7"]] = True
    monitor.poll_once(now=1.1)
    monitor.poll_once(now=1.2)
    states[VK_CODES["F7"]] = False
    monitor.poll_once(now=1.3)
    assert [event.action for event in events] == ["toggle_overlay"]


def test_manual_session_keys_are_observed_with_existing_game_bindings():
    states = {VK_CODES["F"]: False, VK_CODES["ESC"]: False}
    events = []
    monitor = InputMonitor(
        {
            "utility": "F", "reset_primary": "ESC",
            "listening_start": "F", "listening_stop": "ESC",
        },
        events.append, state_reader=lambda vk: states[vk],
    )
    monitor.poll_once(now=1.0)
    states[VK_CODES["F"]] = True
    monitor.poll_once(now=1.1)
    states[VK_CODES["F"]] = False
    monitor.poll_once(now=1.2)
    states[VK_CODES["ESC"]] = True
    monitor.poll_once(now=1.3)
    assert [event.action for event in events] == [
        "utility", "listening_start", "reset_primary", "listening_stop",
    ]
