"""Shared synthetic execution fixtures, using the real packet/executor APIs."""
from copy import deepcopy
from matter.canonical import canonical_bytes
from matter.semantic import Batch, Capabilities, FixtureExecutor, execute_batch
from matter.semantic.families import render_questions
from matter.semantic.packets import PacketProfile, prepare_packet
from matter.storage import pin

AS_OF = {'state': 'known', 'value': '2050-01-01T00:00:00Z', 'precision': 'second'}
DEADLINE = {'state': 'known', 'value': '2050-01-01T00:01:00Z', 'precision': 'second'}


def packet(storage, payloads, adapter, binding, sources, *, as_of=AS_OF, max_packet_bytes=524288, access=None, access_context=None):
    profile = PacketProfile({'namespace': 'synthetic', 'id': 'family-packet', 'version': '1.0',
        'required_roles': ['synthetic:basis'], 'allowed_origins': ['source', 'host', 'derived', 'evaluator'],
        'locator_adapters': [adapter.reference], 'max_sources': 16,
        'max_source_bytes': min(65536, max_packet_bytes), 'max_packet_bytes': max_packet_bytes})
    evidence = []
    for source in sources:
        locator = deepcopy(source['body']['content']['locator'])
        evidence.append({'reference': pin(source), 'roles': ['synthetic:basis'], 'locator': locator,
            'quotation': None, 'validation': adapter.validate(source, locator, checked_at=as_of)})
    with storage.snapshot() as view:
        return prepare_packet(view, profile, payloads=payloads, scope_id=storage.scope_id,
            binding=binding, as_of=as_of, evidence=evidence, coverage={'status': 'complete',
                'snapshot': {'namespace': 'synthetic', 'id': 'explicit-cohort', 'version': '1.0', 'digest': 'a'*64}},
            access=access,access_context=access_context)


def batch(packet, specifications, *, prefix='q', **render_options):
    rendered = render_questions(specifications, packet, prefix=prefix, **render_options)
    return Batch({'schema_version': '1.0', 'id': 'family-batch', 'scope_id': packet.state['scope_id'],
        'run_id': 'synthetic-run', 'stage_id': 'family', 'state': packet.state, 'packet_digest': packet.digest,
        'questions': [q.question.value for q in rendered], 'context': {'provider': 'synthetic',
            'transport': 'fixture', 'requested_model': 'synthetic-recording', 'adapter_version': '1.0',
            'mode': 'offline_fixture', 'deadline': DEADLINE, 'max_request_bytes': 1048576,
            'max_response_bytes': 1048576}}), rendered


def response(batch, outcomes):
    answers = []
    for q in batch.value['questions']:
        answer = {'id': q['id'], 'primitive': q['primitive']}
        outcome = outcomes[q['family']]
        if q['primitive'] == 'choice':
            answer.update(choice=outcome, confidence='0.99',
                probabilities={c['id']: '1' if c['id'] == outcome else '0' for c in q['criteria']})
        else:
            answer['probability'] = outcome
        answers.append(answer)
    return canonical_bytes({'answers': answers, 'resolved_model': 'synthetic-recording'})


def executor(batch, raw):
    capabilities = Capabilities({**{k: batch.value['context'][k] for k in ('provider','transport','adapter_version')},
        'primitives': ['choice', 'score', 'proposition_probability'], 'modes': ['offline_fixture'],
        'max_questions': 128, 'max_request_bytes': 1048576, 'max_response_bytes': 1048576})
    return FixtureExecutor(capabilities, {batch.digest: raw})


def execute(batch, raw):
    return execute_batch(executor(batch, raw), batch, clock=lambda: AS_OF)
