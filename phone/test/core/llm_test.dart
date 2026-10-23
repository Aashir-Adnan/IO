import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:io_phone/core/anthropic_client.dart';
import 'package:io_phone/core/llm.dart';
import 'package:io_phone/core/plan.dart';

final now = DateTime.utc(2026, 9, 8, 12, 0); // a Tuesday

/// Reads the real assets off disk (tests run from phone/).
class DiskPrompts implements PromptSource {
  @override
  Future<String> load(String name) async =>
      File('assets/prompts/$name').readAsString();
}

String storeJson() => jsonEncode({
      'steps': [
        {
          'kind': 'store',
          'extraction': {
            'people': [{'name': 'Mum', 'aliases': ['mom'], 'confidence': 0.9}],
            'places': [], 'items': [], 'occasions': [],
            'records': [
              {'kind': 'task', 'title': 'call mum', 'due_phrase': 'tomorrow',
                'people': ['Mum'], 'attributes': {}, 'confidence': 0.9}
            ],
          }
        }
      ]
    });

void main() {
  group('renderPrompt', () {
    test('substitutes named placeholders and unescapes doubled braces', () {
      final out = renderPrompt('A {{"k": 1}} {name} {{x}}', {'name': 'Bob'});
      expect(out, 'A {"k": 1} Bob {x}');
    });

    test('a substituted value containing braces is left alone', () {
      final out = renderPrompt('rows: {rows}', {'rows': '[{"a": {"b": 1}}]'});
      expect(out, 'rows: [{"a": {"b": 1}}]');
    });
  });

  group('parsePlan', () {
    test('parses a store step with its extraction', () {
      final plan = parsePlan(storeJson());
      expect(plan.steps.single.kind, 'store');
      final rec = plan.steps.single.extraction!.records.single;
      expect(rec.title, 'call mum');
      expect(rec.duePhrase, 'tomorrow');
      expect(plan.steps.single.extraction!.people.single.aliases, ['mom']);
    });

    test('tolerates code fences and surrounding chatter', () {
      final plan = parsePlan('Sure!\n```json\n{"steps":[{"kind":"query","question":"what is on friday"}]}\n```');
      expect(plan.steps.single.kind, 'query');
      expect(plan.steps.single.question, 'what is on friday');
    });

    test('keeps multiple steps in order', () {
      final plan = parsePlan(jsonEncode({
        'steps': [
          {'kind': 'store', 'extraction': jsonDecode(storeJson())['steps'][0]['extraction']},
          {'kind': 'query', 'question': 'what tasks do I have'},
        ]
      }));
      expect(plan.steps.map((s) => s.kind), ['store', 'query']);
    });

    test('file and action steps degrade to unknown (the phone has neither)', () {
      final plan = parsePlan('{"steps":[{"kind":"file","question":"find x"},{"kind":"action","action":"web"}]}');
      expect(plan.steps.map((s) => s.kind), ['unknown', 'unknown']);
    });

    test('an unusable extraction keeps the store step with null extraction', () {
      final plan = parsePlan('{"steps":[{"kind":"store","extraction":{"records":[{"title":"x"}]}}]}');
      expect(plan.steps.single.kind, 'store');
      expect(plan.steps.single.extraction, isNull);
    });

    test('unknown step kinds are dropped; no usable step raises', () {
      expect(parsePlan('{"steps":[{"kind":"nonsense"},{"kind":"unknown"}]}').steps.length, 1);
      expect(() => parsePlan('{"steps":[{"kind":"nonsense"}]}'), throwsA(isA<PlanParseError>()));
      expect(() => parsePlan('not json'), throwsA(isA<PlanParseError>()));
      expect(() => parsePlan('{"steps":[]}'), throwsA(isA<PlanParseError>()));
    });
  });

  group('groundPlan', () {
    test('grounds a relative time window with the dates module', () {
      final qp = groundPlan({
        'subqueries': [
          {'target_type': 'record', 'time_window': {'start': 'last week', 'end': 'yesterday'}}
        ],
        'answer_shape': 'markdown',
      }, now);
      expect(qp.answerShape, 'markdown');
      final w = qp.subqueries.single.timeWindow!;
      expect((w.start!.year, w.start!.month, w.start!.day), (2026, 9, 1));
      expect((w.end!.year, w.end!.month, w.end!.day), (2026, 9, 7));
    });

    test('drops an unknown domain instead of coercing it to other', () {
      final qp = groundPlan({
        'subqueries': [
          {'target_type': 'record', 'domain_filter': ['astrology', 'job']}
        ]
      }, now);
      expect(qp.subqueries.single.domainFilter, ['job']);
    });

    test('normalizes kinds, keeps only valid statuses, defaults shape', () {
      final qp = groundPlan({
        'subqueries': [
          {'kind_filter': ['To Do', 'event'], 'status_filter': ['open', 'bogus'], 'entities': ['Nafay', ' ']}
        ]
      }, now);
      final sq = qp.subqueries.single;
      expect(sq.kindFilter, ['task', 'event']);
      expect(sq.statusFilter, ['open']);
      expect(sq.entities, ['Nafay']);
      expect(qp.answerShape, 'text');
    });

    test('count aggregation survives; latest degrades to list', () {
      expect(groundPlan({'subqueries': [{'aggregation': 'count'}]}, now).subqueries.single.aggregation, 'count');
      expect(groundPlan({'subqueries': [{'aggregation': 'latest'}]}, now).subqueries.single.aggregation, 'list');
    });

    test('no subqueries becomes one default record subquery; non-object raises', () {
      expect(groundPlan({}, now).subqueries.length, 1);
      expect(() => groundPlan('nope', now), throwsA(isA<PlanParseError>()));
    });

    test('a vague "past" window with no groundable bound ends now', () {
      final qp = groundPlan({
        'subqueries': [{'time_window': {'start': 'the past while', 'end': null}}]
      }, now);
      expect(qp.subqueries.single.timeWindow!.end, now);
    });
  });

  group('AnthropicLlm', () {
    AnthropicLlm llmWith(http.Client c, {String? key = 'sk-test'}) => AnthropicLlm(
          client: AnthropicClient(http: c),
          prompts: DiskPrompts(),
          apiKey: () async => key,
          model: 'claude-haiku-4-5',
        );

    Map<String, dynamic> reply(String text) => {
          'content': [{'type': 'text', 'text': text}]
        };

    // Like the real API: UTF-8 bytes, no charset on the content-type.
    http.Response ok(Map<String, dynamic> body) => http.Response.bytes(
        utf8.encode(jsonEncode(body)), 200,
        headers: {'content-type': 'application/json'});

    test('decide sends the rendered prompt and parses the plan', () async {
      late Map<String, dynamic> sent;
      final llm = llmWith(MockClient((req) async {
        expect(req.headers['x-api-key'], 'sk-test');
        sent = jsonDecode(req.body) as Map<String, dynamic>;
        return ok(reply(storeJson()));
      }));
      final plan = await llm.decide('remind me to call mum tomorrow', now, context: 'user: hi');
      expect(plan.steps.single.kind, 'store');
      final user = sent['messages'][0]['content'] as String;
      expect(user, contains('Message: remind me to call mum tomorrow'));
      expect(user, contains('Recent conversation:\nuser: hi'));
      expect(user, contains('Now: ${now.toIso8601String()}'));
      expect(user, isNot(contains('{{')));
      // the schema rides in the cached system block
      final system = sent['system'] as List;
      expect(system.single['cache_control'], {'type': 'ephemeral'});
      expect(system.single['text'], contains('records: [{"kind"'));
    });

    test('phrase embeds the rows as JSON and returns the text', () async {
      late String user;
      final llm = llmWith(MockClient((req) async {
        user = (jsonDecode(req.body) as Map)['messages'][0]['content'] as String;
        return ok(reply('You have one task.'));
      }));
      final out = await llm.phrase('what tasks?', [{'title': 'call mum', 'overdue': false}], 'text');
      expect(out, 'You have one task.');
      expect(user, contains('"title":"call mum"'));
      expect(user, contains('Question:\nwhat tasks?'));
    });

    test('plan returns the model JSON object', () async {
      final llm = llmWith(MockClient((req) async => http.Response(
          jsonEncode(reply('```json\n{"subqueries":[{"target_type":"record"}]}\n```')), 200)));
      final raw = await llm.plan('what tasks?', now);
      expect(raw['subqueries'], isA<List>());
    });

    test('acknowledge returns one sentence', () async {
      final llm = llmWith(MockClient(
          (req) async => ok(reply('Got it — call mum tomorrow.'))));
      expect(await llm.acknowledge('task: call mum'), 'Got it — call mum tomorrow.');
    });

    test('no stored key raises a clear error before any request', () async {
      final llm = llmWith(MockClient((req) async => fail('must not call')), key: null);
      expect(() => llm.acknowledge('x'), throwsA(isA<MissingApiKey>()));
    });

    test('an API failure surfaces as AnthropicApiError', () async {
      final llm = llmWith(MockClient((req) async => http.Response('{}', 529)));
      expect(() => llm.acknowledge('x'), throwsA(isA<AnthropicApiError>()));
    });
  });
}
