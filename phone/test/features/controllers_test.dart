import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/chat_store.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/core/extraction.dart';
import 'package:io_phone/core/llm.dart';
import 'package:io_phone/core/orchestrator.dart';
import 'package:io_phone/core/plan.dart';
import 'package:io_phone/features/chat/chat_controller.dart';
import 'package:io_phone/features/tasks/tasks_controller.dart';

final now = DateTime.utc(2026, 9, 8, 12, 0);

class ScriptedLlm implements Llm {
  Plan Function(String text, String? context)? decideFn;
  String? seenContext;
  @override
  Future<Plan> decide(String u, DateTime n, {String? context}) async {
    seenContext = context;
    return decideFn!(u, context);
  }

  @override
  Future<Map<String, Object?>> plan(String q, DateTime n, {String? context}) async =>
      {'subqueries': [{'status_filter': ['open']}]};
  @override
  Future<String> phrase(String q, List<Map<String, Object?>> rows, String s, {String? context}) async =>
      'You have ${rows.length} open.';
  @override
  Future<String> acknowledge(String facts, {String? context}) async => 'Saved.';
}

Plan storeTask(String title) => Plan([
      Step('store', extraction: ExtractionResult(records: [
        ExtractedRecord(kind: 'task', title: title, duePhrase: 'today', confidence: 0.9)
      ]))
    ]);

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('send appends the user line, runs the turn, appends the reply, notifies', () async {
    final db = await openIoDatabase(inMemory: true);
    addTearDown(db.close);
    final llm = ScriptedLlm()..decideFn = (t, c) => storeTask('call mum');
    final c = ChatController(ChatStore(db, clock: () => now), Orchestrator(db, llm, clock: () => now));
    await c.load();
    var notified = 0;
    c.addListener(() => notified++);

    final f = c.send('remind me to call mum');
    expect(c.busy, isTrue);
    await f;
    expect(c.busy, isFalse);
    expect(c.messages.map((m) => (m.role, m.text)),
        [('user', 'remind me to call mum'), ('assistant', 'Saved.')]);
    expect(notified, greaterThanOrEqualTo(3));
  });

  test('blank input and sending while busy are ignored', () async {
    final db = await openIoDatabase(inMemory: true);
    addTearDown(db.close);
    final llm = ScriptedLlm()..decideFn = (t, c) => storeTask('x');
    final c = ChatController(ChatStore(db, clock: () => now), Orchestrator(db, llm, clock: () => now));
    await c.load();
    await c.send('   ');
    expect(c.messages, isEmpty);
    final first = c.send('one');
    await c.send('two'); // busy: dropped
    await first;
    expect(c.messages.where((m) => m.role == 'user').length, 1);
  });

  test('follow-up turns carry the earlier turns as context', () async {
    final db = await openIoDatabase(inMemory: true);
    addTearDown(db.close);
    final llm = ScriptedLlm()..decideFn = (t, c) => storeTask('x');
    final c = ChatController(ChatStore(db, clock: () => now), Orchestrator(db, llm, clock: () => now));
    await c.load();
    await c.send('first');
    await c.send('second');
    expect(llm.seenContext, contains('you: first'));
    expect(llm.seenContext, isNot(contains('you: second'))); // not its own line twice
  });

  test('history survives a reload and newChat starts empty', () async {
    final db = await openIoDatabase(inMemory: true);
    addTearDown(db.close);
    final llm = ScriptedLlm()..decideFn = (t, c) => storeTask('x');
    final store = ChatStore(db, clock: () => now);
    final c = ChatController(store, Orchestrator(db, llm, clock: () => now));
    await c.load();
    await c.send('hello');
    final again = ChatController(store, Orchestrator(db, llm, clock: () => now));
    await again.load();
    expect(again.messages.length, 2);
    await again.newChat();
    expect(again.messages, isEmpty);
  });

  test('tasks controller lists pending tasks and completing removes one', () async {
    final db = await openIoDatabase(inMemory: true);
    addTearDown(db.close);
    final llm = ScriptedLlm()..decideFn = (t, c) => storeTask('pay rent');
    await Orchestrator(db, llm, clock: () => now).handle('pay rent');
    final t = TasksController(db, clock: () => now);
    await t.load();
    expect(t.tasks.single['title'], 'pay rent');
    var notified = 0;
    t.addListener(() => notified++);
    await t.complete(t.tasks.single['id'] as int);
    expect(t.tasks, isEmpty);
    expect(notified, greaterThan(0));
    expect((await db.query('records')).single['status'], 'done');
  });
}
