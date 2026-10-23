import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/core/extraction.dart';
import 'package:io_phone/core/llm.dart';
import 'package:io_phone/core/orchestrator.dart';
import 'package:io_phone/core/plan.dart';
import 'package:io_phone/core/web.dart';

final now = DateTime.utc(2026, 9, 8, 12, 0);

class FakeLlm implements Llm {
  Plan Function(String)? onDecide;
  Map<String, Object?> Function(String)? onPlan;
  final calls = <String>[];
  List<Map<String, Object?>>? lastRows;
  String? lastFacts;
  String? lastShape;
  String? lastQuestion;
  String? lastContext;

  @override
  Future<Plan> decide(String utterance, DateTime now, {String? context}) async {
    calls.add('decide');
    lastContext = context;
    return onDecide!(utterance);
  }

  @override
  Future<Map<String, Object?>> plan(String question, DateTime now, {String? context}) async {
    calls.add('plan');
    return onPlan!(question);
  }

  @override
  Future<String> phrase(String question, List<Map<String, Object?>> rows, String shape,
      {String? context}) async {
    calls.add('phrase');
    lastQuestion = question;
    lastRows = rows;
    lastShape = shape;
    return 'PHRASED(${rows.length})';
  }

  @override
  Future<String> acknowledge(String facts, {String? context}) async {
    calls.add('ack');
    lastFacts = facts;
    return 'ACK';
  }
}

Plan storeTask(String title, {double conf = 0.9, String? duePhrase = 'tomorrow', List<String> people = const []}) =>
    Plan([
      Step('store', extraction: ExtractionResult(
        people: [for (final p in people) ExtractedPerson(name: p, confidence: 0.9)],
        records: [ExtractedRecord(kind: 'task', title: title, duePhrase: duePhrase,
            people: people, confidence: conf)],
      ))
    ]);

Plan queryPlan(String q) => Plan([Step('query', question: q)]);

class FakeWeb implements WebClient {
  final bool configured;
  Object? error;
  final asked = <(String, String)>[];
  FakeWeb({this.configured = true, this.error});
  @override
  Future<bool> isConfigured() async => configured;
  @override
  Future<WebAnswer> answer(String query, String kind) async {
    asked.add((query, kind));
    if (error != null) throw error!;
    return WebAnswer('Gold is 2,400.', kind, 'c', const [
      WebSource('A', 'https://a.x'), WebSource('B', 'https://b.x'),
      WebSource('C', 'https://c.x'), WebSource('D', 'https://d.x')], false);
  }
}

Future<(Orchestrator, FakeLlm, dynamic)> setup({WebClient? web}) async {
  final db = await openIoDatabase(inMemory: true);
  final llm = FakeLlm();
  return (Orchestrator(db, llm, clock: () => now, web: web), llm, db);
}

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('a store turn persists the record and acknowledges with the saved facts', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => storeTask('call mum', people: ['Mum']);
    final r = await o.handle('remind me to call mum tomorrow');
    expect(r.kind, 'ack');
    expect(r.message, 'ACK');
    expect(r.recordIds.length, 1);
    expect(llm.lastFacts, contains('task "call mum"'));
    expect(llm.lastFacts, contains('with Mum'));
    final rec = (await db.query('records')).single;
    expect(rec['due_at'], DateTime.utc(2026, 9, 9, 12).toIso8601String());
    expect(rec['status'], 'open');
    await db.close();
  });

  test('a query turn plans, retrieves, and phrases only from the rows', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => storeTask('pay rent', duePhrase: 'yesterday');
    await o.handle('remind me to pay rent');
    llm.onDecide = (_) => queryPlan('what tasks do I have?');
    llm.onPlan = (_) => {
          'subqueries': [{'target_type': 'record', 'status_filter': ['open']}],
          'answer_shape': 'markdown',
        };
    final r = await o.handle('what tasks do I have?');
    expect(r.kind, 'answer');
    expect(r.message, 'PHRASED(1)');
    expect(llm.lastShape, 'markdown');
    expect(llm.lastRows!.single['title'], 'pay rent');
    expect(llm.lastRows!.single['overdue'], isTrue); // computed in Dart, not by the model
    await db.close();
  });

  test('an empty result never calls the phrasing model', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => queryPlan('what did I do on friday?');
    llm.onPlan = (_) => {'subqueries': [{'kind_filter': ['event']}]};
    final r = await o.handle('what did I do on friday?');
    expect(r.message, "I don't have anything on that yet.");
    expect(llm.calls, isNot(contains('phrase')));
    await db.close();
  });

  test('query entities are resolved to ids and filter the records', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => Plan([
          Step('store', extraction: ExtractionResult(
            people: [ExtractedPerson(name: 'Nafay', confidence: 0.9)],
            records: [
              ExtractedRecord(kind: 'event', title: 'lunch with Nafay', whenPhrase: 'today',
                  people: ['Nafay'], confidence: 0.9),
              ExtractedRecord(kind: 'event', title: 'gym', whenPhrase: 'today', confidence: 0.9),
            ],
          ))
        ]);
    await o.handle('x');
    llm.onDecide = (_) => queryPlan('what did I do with nafay');
    llm.onPlan = (_) => {'subqueries': [{'entities': ['nafay']}]};
    await o.handle('what did I do with nafay');
    expect(llm.lastRows!.map((r) => r['title']), ['lunch with Nafay']);
    await db.close();
  });

  test('a count subquery phrases the number even with no list rows', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => storeTask('a');
    await o.handle('a');
    llm.onDecide = (_) => queryPlan('how many tasks?');
    llm.onPlan = (_) => {'subqueries': [{'status_filter': ['open'], 'aggregation': 'count'}]};
    final r = await o.handle('how many tasks?');
    expect(r.message, startsWith('PHRASED'));
    expect(llm.lastQuestion, contains('(there are 1 matching items)'));
    await db.close();
  });

  test('a low-confidence store is gated, then saved when the user says yes', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => storeTask('mumble', conf: 0.3);
    final gated = await o.handle('mumble');
    expect(gated.kind, 'gate');
    expect(gated.message.toLowerCase(), contains('low confidence'));
    expect(await db.query('records'), isEmpty);
    expect((await db.query('utterances')).length, 1); // kept for the replay

    llm.calls.clear();
    final done = await o.handle('yes');
    expect(done.kind, 'ack');
    expect((await db.query('records')).length, 1);
    expect((await db.query('utterances')).length, 1); // reused, not duplicated
    expect(llm.calls, ['ack']); // the replay does not re-ask the planner
    await db.close();
  });

  test('anything but a yes drops the pending gate', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => storeTask('mumble', conf: 0.3);
    await o.handle('mumble');
    llm.onDecide = (_) => const Plan([Step('unknown')]);
    await o.handle('never mind');
    final r = await o.handle('yes');
    expect(r.kind, 'unknown'); // "yes" now goes to the planner as a normal turn
    expect(await db.query('records'), isEmpty);
    await db.close();
  });

  test('an unusable extraction asks the user to rephrase', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => const Plan([Step('store')]);
    final r = await o.handle('blah');
    expect(r.kind, 'unknown');
    expect(r.message, contains('rephrase'));
    await db.close();
  });

  test('an unknown step gets the same reply the desktop gives', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => const Plan([Step('unknown')]);
    final r = await o.handle('hello');
    expect(r.kind, 'unknown');
    expect(r.message, 'I didn\'t catch that - please rephrase and try again.');
    await db.close();
  });

  test('a store and a query in one message produce one merged reply', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => Plan([...storeTask('call mum').steps, ...queryPlan('what is on?').steps]);
    llm.onPlan = (_) => {'subqueries': [{'status_filter': ['open']}]};
    final r = await o.handle('remind me to call mum, and what is on?');
    expect(r.message, 'ACK\n\nPHRASED(1)');
    expect(r.kind, 'answer');
    await db.close();
  });

  test('a failing model call becomes an error reply, not a crash', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => throw MissingApiKey();
    final r = await o.handle('hello');
    expect(r.kind, 'error');
    expect(r.message, contains('API key'));
    await db.close();
  });

  test('conversation context is passed to the planner', () async {
    final (o, llm, db) = await setup();
    llm.onDecide = (_) => const Plan([Step('unknown')]);
    await o.handle('and tomorrow?', context: 'user: what is on today');
    expect(llm.lastContext, 'user: what is on today');
    await db.close();
  });

  group('web answers', () {
    test('a clear world question goes to the home server, skips the model, keeps 3 sources', () async {
      final web = FakeWeb();
      final (o, llm, db) = await setup(web: web);
      final r = await o.handle('price of gold today');
      expect(r.kind, 'answer');
      expect(r.message, startsWith('Gold is 2,400.'));
      expect(r.message, contains('https://c.x'));
      expect(r.message, isNot(contains('https://d.x')));
      expect(llm.calls, isEmpty);
      expect(web.asked.single, ('price of gold today', 'fact'));
      expect((await db.query('utterances')).single['resolved_intent'], 'web');
      await db.close();
    });

    test('personal questions never touch the web', () async {
      final web = FakeWeb();
      final (o, llm, db) = await setup(web: web);
      llm.onDecide = (_) => queryPlan('what did I spend on rent');
      llm.onPlan = (_) => {'subqueries': [{'kind_filter': ['event']}]};
      await o.handle('how much did I spend on rent');
      expect(web.asked, isEmpty);
      await db.close();
    });

    test('an explicit ask with no home server explains how to set one up', () async {
      final (o, llm, db) = await setup(web: FakeWeb(configured: false));
      final r = await o.handle('search the web for espresso machines');
      expect(r.kind, 'error');
      expect(r.message, contains('desktop'));
      expect(llm.calls, isEmpty);
      await db.close();
    });

    test('an implicit web-shaped question with no home server falls through to memory', () async {
      final (o, llm, db) = await setup(web: FakeWeb(configured: false));
      llm.onDecide = (_) => queryPlan('price of gold');
      llm.onPlan = (_) => {'subqueries': [{'kind_filter': ['event']}]};
      final r = await o.handle('price of gold today');
      expect(r.kind, 'answer');
      expect(llm.calls, contains('decide'));
      await db.close();
    });

    test('a web failure is a readable error, not a crash', () async {
      final (o, _, db) = await setup(web: FakeWeb(error: WebUnavailable('desktop is off')));
      final r = await o.handle('usd to pkr');
      expect((r.kind, r.message), ('error', 'desktop is off'));
      await db.close();
    });

    test('an empty memory answer hints at the explicit search, but never auto-searches', () async {
      final web = FakeWeb();
      final (o, llm, db) = await setup(web: web);
      llm.onDecide = (_) => queryPlan('what did I do on friday?');
      llm.onPlan = (_) => {'subqueries': [{'kind_filter': ['event']}]};
      final r = await o.handle('what did I do on friday?');
      expect(r.message, contains('search the web for'));
      expect(web.asked, isEmpty);
      await db.close();
    });
  });
}
