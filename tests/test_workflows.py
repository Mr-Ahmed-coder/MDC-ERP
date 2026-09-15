import pytest

from mdc_erp.core.workflows import (
    available_transitions,
    can_transition,
    transition_target,
)


def test_lab_workflow_progression_and_next_action():
    assert transition_target('lab', 'Requested', 'collect', 'lab_tech') == 'Collected'
    assert transition_target('lab', 'Received', 'result', 'lab_tech') == 'Resulted'
    assert available_transitions('lab', 'Resulted', 'lab_tech')[0].next_action == 'Print result'


def test_invalid_workflow_transition_is_rejected():
    assert not can_transition('lab', 'Requested', 'approve', 'lab_tech')
    with pytest.raises(ValueError):
        transition_target('lab', 'Requested', 'approve', 'lab_tech')


def test_workflow_role_restriction_is_enforced():
    assert not can_transition('radiology', 'Imaged', 'report', 'reception')
    with pytest.raises(PermissionError):
        transition_target('radiology', 'Imaged', 'report', 'reception')
