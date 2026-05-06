"""Tests for TUI screens."""


from deepseek_tui.tui.screens import ChatScreen, ConfigScreen


def test_chat_screen_creation() -> None:
    """Test chat screen can be created."""
    screen = ChatScreen()
    assert screen is not None


def test_config_screen_creation() -> None:
    """Test config screen can be created."""
    screen = ConfigScreen()
    assert screen is not None


def test_chat_screen_bindings() -> None:
    """Test chat screen key bindings."""
    screen = ChatScreen()
    assert len(screen.BINDINGS) > 0
    binding_keys = [b[0] if isinstance(b, tuple) else b.key for b in screen.BINDINGS]
    assert "ctrl+n" in binding_keys
    assert "ctrl+q" in binding_keys


def test_config_screen_bindings() -> None:
    """Test config screen key bindings."""
    screen = ConfigScreen()
    assert len(screen.BINDINGS) > 0
    binding_keys = [b[0] if isinstance(b, tuple) else b.key for b in screen.BINDINGS]
    assert "escape" in binding_keys
