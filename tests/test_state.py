from morpheus_vlt.models.state import MachineState


def test_state_get_set_bump() -> None:
    state = MachineState()

    assert state.get_counter(1) == 0
    state.set_counter(1, 42)
    assert state.get_counter(1) == 42
    state.bump_counter(1, 8)
    assert state.get_counter(1) == 50

    assert state.get_meter("play") == 0
    state.set_meter("play", 123)
    assert state.get_meter("play") == 123
