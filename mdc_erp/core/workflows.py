"""Declarative workflow definitions and transition validation.

Domain blueprints may still perform domain-specific side effects, but every
status change should first pass through this registry. This keeps invalid
transitions and role requirements reviewable in one place.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    action: str
    roles: tuple[str, ...]
    label: str
    next_action: str | None = None


WORKFLOWS = {
    'lab': (
        Transition('Requested', 'Collected', 'collect', ('super_admin', 'lab_tech', 'reception'), 'Collect sample', 'Receive sample'),
        Transition('Collected', 'Received', 'receive', ('super_admin', 'lab_tech'), 'Receive sample', 'Enter result'),
        Transition('Requested', 'Resulted', 'result', ('super_admin', 'lab_tech', 'doctor'), 'Enter result', 'Approve result'),
        Transition('Received', 'Resulted', 'result', ('super_admin', 'lab_tech', 'doctor'), 'Enter result', 'Approve result'),
        Transition('Resulted', 'Approved', 'approve', ('super_admin', 'lab_tech', 'doctor'), 'Approve result', 'Print result'),
    ),
    'radiology': (
        Transition('Requested', 'Imaged', 'image', ('super_admin', 'radiologist', 'lab_tech'), 'Mark imaged', 'Write report'),
        Transition('Requested', 'Reported', 'report', ('super_admin', 'radiologist'), 'Write report', 'Print report'),
        Transition('Imaged', 'Reported', 'report', ('super_admin', 'radiologist'), 'Write report', 'Print report'),
        Transition('Reported', 'Reported', 'report', ('super_admin', 'radiologist'), 'Edit report', 'Print report'),
    ),
    'referral': (
        Transition('Requested', 'Accepted', 'accept', ('super_admin', 'doctor', 'reception'), 'Accept referral', 'Schedule'),
        Transition('Accepted', 'Scheduled', 'schedule', ('super_admin', 'doctor', 'reception'), 'Schedule referral', 'Start'),
        Transition('Scheduled', 'In Progress', 'start', ('super_admin', 'doctor', 'lab_tech', 'radiologist'), 'Start referral', 'Complete'),
        Transition('In Progress', 'Completed', 'complete', ('super_admin', 'doctor', 'lab_tech', 'radiologist'), 'Complete referral', None),
    ),
}


def transition_for(workflow, status, action):
    """Return a transition or raise a user-safe ValueError."""
    for transition in WORKFLOWS.get(workflow, ()):
        if transition.source == status and transition.action == action:
            return transition
    raise ValueError(f'Action {action!r} is not valid from status {status!r}.')


def can_transition(workflow, status, action, role):
    try:
        transition = transition_for(workflow, status, action)
    except ValueError:
        return False
    return role == 'super_admin' or role in transition.roles


def transition_target(workflow, status, action, role):
    transition = transition_for(workflow, status, action)
    if role != 'super_admin' and role not in transition.roles:
        raise PermissionError(f'Role {role!r} cannot perform {transition.label.lower()}.')
    return transition.target


def available_transitions(workflow, status, role):
    return tuple(t for t in WORKFLOWS.get(workflow, ())
                 if t.source == status and (role == 'super_admin' or role in t.roles))
