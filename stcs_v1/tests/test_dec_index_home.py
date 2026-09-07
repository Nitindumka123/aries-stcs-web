from src.core.legacy_decoder import LegacyDecoder
from src.drivers.mount.mount_coordinator import MountCoordinator


def _coordinator_without_hardware():
    coordinator = MountCoordinator.__new__(MountCoordinator)
    coordinator.dec_home_deg = None
    coordinator.dec_offset_counts = 123
    coordinator._dec_index_home_applied = False
    coordinator._save_state = lambda: None
    return coordinator


def test_dec_index_home_zero_displays_default_home():
    coordinator = _coordinator_without_hardware()

    coordinator._apply_dec_index_home()

    assert coordinator.dec_offset_counts == 0
    assert coordinator._dec_index_home_applied is True
    assert LegacyDecoder.decimal_deg_to_dms(coordinator.dec_home_deg) == "+29:49:59.9"
    assert LegacyDecoder.decimal_deg_to_dms(
        coordinator._dec_index_counts_to_degrees(0)
    ) == "+29:49:59.9"


def test_dec_index_home_signed_counts_move_from_default_home():
    coordinator = _coordinator_without_hardware()

    assert LegacyDecoder.decimal_deg_to_dms(
        coordinator._dec_index_counts_to_degrees(1)
    ) == "+29:50:00.8"
    assert LegacyDecoder.decimal_deg_to_dms(
        coordinator._dec_index_counts_to_degrees(-1)
    ) == "+29:49:59.0"


def test_dec_index_home_uses_configured_home_value():
    coordinator = _coordinator_without_hardware()
    coordinator.dec_home_deg = 29.0 + (54.0 / 60.0) + (29.9 / 3600.0)

    coordinator._apply_dec_index_home()

    assert coordinator.dec_offset_counts == 0
    assert coordinator._dec_index_home_applied is True
    assert LegacyDecoder.decimal_deg_to_dms(coordinator.dec_home_deg) == "+29:54:29.9"
    assert LegacyDecoder.decimal_deg_to_dms(
        coordinator._dec_index_counts_to_degrees(0)
    ) == "+29:54:29.9"
    assert LegacyDecoder.decimal_deg_to_dms(
        coordinator._dec_index_counts_to_degrees(1)
    ) == "+29:54:30.8"
