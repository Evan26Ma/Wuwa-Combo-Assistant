from wuwa_assistant.animation_guard import AnimationInputGuard
from wuwa_assistant.models import InputEvent


def settings(**overrides):
    config = {
        "enabled": True,
        "basic_lock_ms": 100,
        "liberation_min_ms": 500,
        "liberation_enter_timeout_ms": 1000,
        "liberation_fallback_ms": 3000,
        "liberation_max_ms": 7000,
    }
    config.update(overrides)
    return {"input_guard": config}


def event(action, timestamp):
    return InputEvent(action, timestamp)


def test_basic_guard_ignores_followup_until_short_action_lock_ends():
    guard = AnimationInputGuard(settings())
    guard.record(event("basic", 10.0))
    assert not guard.allows(event("skill", 10.05))
    assert guard.state(10.05).mode == "basic"
    assert guard.allows(event("skill", 10.11))


def test_liberation_without_recent_hud_uses_fixed_fallback():
    guard = AnimationInputGuard(settings())
    guard.record(event("liberation", 20.0))
    assert guard.state(21.0).mode == "liberation_fallback"
    assert not guard.allows(event("basic", 22.9))
    assert guard.allows(event("basic", 23.01))


def test_liberation_hud_disappearance_and_return_controls_unlock():
    guard = AnimationInputGuard(settings())
    visible = {"slot1": 0.90, "slot2": 0.89, "slot3": 0.91}
    hidden = {"slot1": 0.20, "slot2": 0.18, "slot3": 0.22}
    guard.observe_party_hud(visible, 30.0)
    guard.record(event("liberation", 30.1))
    assert guard.state(30.2).mode == "liberation_wait_hud_hide"

    guard.observe_party_hud(hidden, 30.3)
    guard.observe_party_hud(hidden, 30.5)
    assert guard.state(30.5).mode == "liberation_hud_hidden"
    assert not guard.allows(event("skill", 31.0))

    guard.observe_party_hud(visible, 31.1)
    guard.observe_party_hud(visible, 31.4)
    assert guard.allows(event("skill", 31.41))


def test_recent_hud_but_missed_disappearance_falls_back_instead_of_unlocking_early():
    guard = AnimationInputGuard(settings())
    visible = {"slot1": 0.90, "slot2": 0.89, "slot3": 0.91}
    guard.observe_party_hud(visible, 50.0)
    guard.record(event("liberation", 50.1))
    assert not guard.allows(event("skill", 51.2))
    assert guard.state(51.2).mode == "liberation_fallback"
    assert guard.allows(event("skill", 53.11))


def test_reset_is_always_allowed_while_locked():
    guard = AnimationInputGuard(settings())
    guard.record(event("liberation", 40.0))
    assert guard.allows(event("reset_primary", 40.1))
