"""Guided form operations on the existing validated, versioned workflow schema."""
from copy import deepcopy
import re
from .config import ConfigError, validate_playbook


def create_flow(current, name, title, prompt):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,49}', name) or name in current['workflows']:
        raise ConfigError('Use a unique workflow ID (letters, numbers, dash)')
    if not 1 <= len(title.strip()) <= 80 or not 1 <= len(prompt.strip()) <= 4000:
        raise ConfigError('Enter a title and prompt within the field limits')
    updated = deepcopy(current)
    updated['workflows'][name] = {'title': title, 'start': 'start', 'states': {
        'start': {'input': 'text', 'field': 'question', 'prompt': prompt, 'next': 'handoff'},
        'handoff': {'type': 'handoff'}, 'complete': {'type': 'complete'}}}
    updated['menu'].append({'label': title, 'action': 'flow:' + name})
    return validate_playbook(updated)


def save_step(current, flow, step, kind, prompt, field, target, values, labels, targets, start=False):
    if flow not in current['workflows'] or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,49}', step):
        raise ConfigError('Choose a workflow and valid step ID')
    if kind not in ('text', 'choice', 'subscription', 'photo', 'question', 'handoff', 'complete', 'knowledge'):
        raise ConfigError('Unsupported step type')
    updated = deepcopy(current)
    if kind in ('handoff', 'complete', 'knowledge'):
        state = {'type': kind}
    else:
        if not prompt.strip():
            raise ConfigError('An input step requires a prompt')
        state = {'input': kind, 'prompt': prompt, 'field': field or step}
        if kind == 'choice':
            if len(values) != len(labels) or len(values) != len(targets):
                raise ConfigError('Each option requires value, label and destination')
            state['options'] = [{'value': v, 'label': label, 'next': destination}
                for v, label, destination in zip(values, labels, targets) if v or label or destination]
            if any(not all(option.values()) for option in state['options']):
                raise ConfigError('Complete all fields of each option')
            if len({o['value'] for o in state['options']}) != len(state['options']):
                raise ConfigError('Option values must be unique')
        else:
            state['next'] = target
    updated['workflows'][flow]['states'][step] = state
    if start:
        updated['workflows'][flow]['start'] = step
    return validate_playbook(updated)
