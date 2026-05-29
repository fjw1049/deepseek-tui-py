from deepseek_tui.config.models import Config


def test_config_loads_memory_smart_defaults() -> None:
    cfg = Config()
    assert cfg.memory.smart.enabled is False
    assert cfg.memory.smart.capture_min_user_chars == 20
    assert cfg.memory.smart.l1_decay_half_life_days == 180
    assert cfg.smart_memory_enabled() is False


def test_smart_memory_enabled_flag() -> None:
    cfg = Config.model_validate({"memory": {"smart": {"enabled": True}}})
    assert cfg.smart_memory_enabled() is True
