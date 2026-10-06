"""Compact-64 release admission; original paid-budget proof and gates preserved."""
import json
from pathlib import Path
from .fallback_qwen_v25 import validate_activation
from .supply_control import file_sha
from .store_qwen_v35 import validate_config


def release_contract(cfg, candidate_binding, output):
    if cfg.get('version') != 35 or cfg.get('teacher') != 'qwen':
        raise ValueError('Explicit independent compact-64 Qwen v35 configuration required')
    validate_activation(Path(cfg['activation_receipt']))
    validate_config(json.loads(Path(cfg['audit_policy']).read_text()), json.loads(Path(cfg['qwen_registry']).read_text()))
    h = file_sha(Path(cfg['qwen_registry']))
    if candidate_binding.get('teacher') != 'qwen' or candidate_binding.get('teacher_registry_sha256') != h:
        raise ValueError('Independent compact-64 candidate binding required')
    for name in ('INPUT_BINDING.json', 'READY_INTERNAL.json', 'RELEASE_INTENT.json'):
        p = Path(output)/name
        if p.exists():
            old = json.loads(p.read_text())
            if old.get('teacher') != 'qwen' or old.get('teacher_registry_sha256') != h:
                raise ValueError('Never reinterpret old teacher outputs')
    return h
