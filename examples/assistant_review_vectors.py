"""Check portable authored review wires using an installed Matter SDK.

This is schema/identity conformance, not a host/assistant execution receipt.
"""
import json
from pathlib import Path
import sys
from matter.assistant_review import ReviewRequest, ReviewResult


def main(path):
    values = json.loads(Path(path).read_text())
    for case in values['cases']:
        request, result = ReviewRequest(case['request']), ReviewResult(case['result'])
        if request.wake_id != case['expected_wake_id'] or result.value['wake_id'] != request.wake_id:
            raise ValueError('Review identity mismatch: ' + case['name'])
    print(json.dumps({'ok': True, 'vectors': len(values['cases']), 'evidence': values['evidence_kind']}))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'tests/fixtures/assistant-review/vectors.json')
