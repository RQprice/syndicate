import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from syndicate.application import WheelApp
from syndicate.wheel_rendering import WheelRenderingMixin


class _RaisedWidget:
    def __init__(self) -> None:
        self.raise_count = 0

    def tkraise(self) -> None:
        self.raise_count += 1


class _ParticipantsPanel:
    def __init__(self) -> None:
        self.flush_count = 0
        self.mass_mode_values: list[bool] = []

    def flush_auto_save(self) -> None:
        self.flush_count += 1

    def set_mass_distribution_mode(self, enabled: bool) -> None:
        self.mass_mode_values.append(enabled)


class _ModeHarness:
    _show_active_mode = WheelApp._show_active_mode
    show_mass_distribution = WheelApp.show_mass_distribution
    show_draw_mode = WheelApp.show_draw_mode

    def __init__(self) -> None:
        self.spinning = False
        self._active_mode = "draw"
        self.draw_panel = _RaisedWidget()
        self.mass_distribution_panel = _RaisedWidget()
        self.participants_panel = _ParticipantsPanel()
        self.focus_count = 0

    def focus_set(self) -> None:
        self.focus_count += 1


class ApplicationModeTests(unittest.TestCase):
    def test_hidden_wheel_does_not_render_or_start_worker(self) -> None:
        app = SimpleNamespace(_active_mode="mass_distribution", _wheel_redraw_deferred=False)
        WheelRenderingMixin._request_wheel_redraw(app)
        self.assertTrue(app._wheel_redraw_deferred)
        WheelRenderingMixin._draw_wheel(app)

    def test_deferred_wheel_redraw_runs_when_returning_to_draw_mode(self) -> None:
        app = _ModeHarness()
        app._wheel_redraw_deferred = True
        app._request_wheel_redraw = Mock()
        app.show_draw_mode()
        app._request_wheel_redraw.assert_called_once()

    def test_mass_distribution_is_an_independent_switchable_view(self) -> None:
        app = _ModeHarness()

        app.show_mass_distribution()

        self.assertEqual(app._active_mode, "mass_distribution")
        self.assertEqual(app.mass_distribution_panel.raise_count, 1)
        self.assertEqual(app.participants_panel.flush_count, 1)
        self.assertEqual(app.participants_panel.mass_mode_values, [True])
        self.assertEqual(app.focus_count, 1)

        app.show_draw_mode()

        self.assertEqual(app._active_mode, "draw")
        self.assertEqual(app.draw_panel.raise_count, 1)
        self.assertEqual(app.participants_panel.mass_mode_values, [True, False])
        self.assertEqual(app.focus_count, 2)

    def test_mode_cannot_change_during_a_spin(self) -> None:
        app = _ModeHarness()
        app.spinning = True

        app.show_mass_distribution()

        self.assertEqual(app._active_mode, "draw")
        self.assertEqual(app.mass_distribution_panel.raise_count, 0)
        self.assertEqual(app.participants_panel.flush_count, 0)


if __name__ == "__main__":
    unittest.main()
