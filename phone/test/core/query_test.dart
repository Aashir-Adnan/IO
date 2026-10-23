import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/core/query.dart';

final now = DateTime.utc(2026, 9, 8, 12, 0);
const empty = <String, List<int>>{};

Future<int> utt(Database db) => db.insert('utterances', {
      'text': 'seed', 'source': 'text', 'captured_at': now.toIso8601String(),
      'sync_id': newSyncId(), 'updated_at': now.toIso8601String(),
    });

Future<int> record(Database db, int uid, {
  required String kind, required String title, String? status,
  DateTime? occurredAt, DateTime? dueAt,
}) {
  final iso = now.toIso8601String();
  return db.insert('records', {
    'kind': kind, 'title': title, 'status': status,
    'occurred_at': occurredAt?.toIso8601String(), 'due_at': dueAt?.toIso8601String(),
    'attributes': '{}', 'source_utterance_id': uid,
    'sync_id': newSyncId(), 'created_at': iso, 'updated_at': iso,
  });
}

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('compile filters kind and window', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await utt(db);
    await record(db, uid, kind: 'event', title: 'dinner',
        occurredAt: now.subtract(const Duration(days: 2)));
    await record(db, uid, kind: 'event', title: 'old dinner',
        occurredAt: now.subtract(const Duration(days: 90)));
    await record(db, uid, kind: 'task', title: 'a task', dueAt: now);
    final sq = SubQuery(targetType: 'record', kindFilter: ['event'],
        timeWindow: TimeWindow(start: now.subtract(const Duration(days: 7)), end: now));
    final rows = await retrieve(db, sq, empty, now);
    expect(rows.map((r) => r['title']).toSet(), {'dinner'});
    await db.close();
  });

  test('an overdue open task is pulled into a today window', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await utt(db);
    final id = await record(db, uid, kind: 'task', title: 'overdue thing', status: 'open',
        dueAt: now.subtract(const Duration(days: 3)));
    final sq = SubQuery(targetType: 'record', statusFilter: ['open'],
        timeWindow: TimeWindow(start: DateTime.utc(2026, 9, 8), end: DateTime.utc(2026, 9, 8, 23, 59)));
    final rows = await retrieve(db, sq, empty, now);
    expect(rows.map((r) => r['id']), contains(id));
    await db.close();
  });

  test('a last-week query does not pull an open overdue task', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await utt(db);
    final t = await record(db, uid, kind: 'task', title: 'pay rent', status: 'open',
        dueAt: now.subtract(const Duration(days: 2)));
    final e = await record(db, uid, kind: 'event', title: 'museum',
        occurredAt: now.subtract(const Duration(days: 9)));
    final sq = SubQuery(targetType: 'record',
        timeWindow: TimeWindow(start: now.subtract(const Duration(days: 14)),
            end: now.subtract(const Duration(days: 7))));
    final rows = await retrieve(db, sq, empty, now);
    final ids = rows.map((r) => r['id']).toSet();
    expect(ids.contains(e), isTrue);
    expect(ids.contains(t), isFalse);
    await db.close();
  });

  test('a done overdue task still obeys the window', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await utt(db);
    final d = await record(db, uid, kind: 'task', title: 'done long ago', status: 'done',
        dueAt: now.subtract(const Duration(days: 30)));
    final sq = SubQuery(targetType: 'record', statusFilter: ['open', 'done'],
        timeWindow: TimeWindow(start: DateTime.utc(2026, 9, 8), end: DateTime.utc(2026, 9, 8, 23, 59)));
    final rows = await retrieve(db, sq, empty, now);
    expect(rows.map((r) => r['id']), isNot(contains(d)));
    await db.close();
  });

  test('entity link exists filters to linked records', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await utt(db);
    final pid = await db.insert('people', {
      'canonical_name': 'Nafay', 'aliases': '[]', 'sync_id': newSyncId(),
      'created_at': now.toIso8601String(), 'updated_at': now.toIso8601String(),
    });
    final r1 = await record(db, uid, kind: 'event', title: 'with nafay', occurredAt: now);
    await record(db, uid, kind: 'event', title: 'alone', occurredAt: now);
    await db.insert('record_people', {'record_id': r1, 'person_id': pid});
    final sq = SubQuery(targetType: 'record', entities: ['Nafay']);
    final rows = await retrieve(db, sq, {'person': [pid], 'place': [], 'item': [], 'occasion': []}, now);
    expect(rows.map((r) => r['title']).toSet(), {'with nafay'});
    await db.close();
  });

  test('count matches the same filters', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await utt(db);
    await record(db, uid, kind: 'watchlist', title: 'film a', status: 'open');
    await record(db, uid, kind: 'watchlist', title: 'film b', status: 'open');
    await record(db, uid, kind: 'watchlist', title: 'film c', status: 'done');
    await record(db, uid, kind: 'task', title: 'unrelated');
    final sq = SubQuery(targetType: 'record', kindFilter: ['watchlist']);
    expect(await retrieveCount(db, sq, empty, now), 3);
    await db.close();
  });

  test('count respects the roll-forward window, matching the list view', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await utt(db);
    final overdue = await record(db, uid, kind: 'task', title: 'overdue thing', status: 'open',
        dueAt: now.subtract(const Duration(days: 3)));
    final inWindow = await record(db, uid, kind: 'task', title: 'today thing', status: 'open', dueAt: now);
    await record(db, uid, kind: 'task', title: 'done long ago', status: 'done',
        dueAt: now.subtract(const Duration(days: 30)));
    await record(db, uid, kind: 'task', title: 'future thing', status: 'open',
        dueAt: now.add(const Duration(days: 10)));
    final sq = SubQuery(targetType: 'record', statusFilter: ['open'],
        timeWindow: TimeWindow(start: DateTime.utc(2026, 9, 8), end: DateTime.utc(2026, 9, 8, 23, 59)));
    final rows = await retrieve(db, sq, empty, now);
    final n = await retrieveCount(db, sq, empty, now);
    expect(n, 2);
    expect(rows.length, 2);
    expect(rows.map((r) => r['id']).toSet(), {overdue, inWindow});
    await db.close();
  });

  // --- rowsToJson / dueLabel --------------------------------------------

  test('rowsToJson carries title, when, body, overdue and due_label', () {
    final rows = [
      {'id': 1, 'type': 'record', 'title': 'pay rent', 'body': null, 'kind': 'task',
        'domain': null, 'status': 'open', 'occurred_at': null,
        'due_at': now.subtract(const Duration(days: 2)).toIso8601String(),
        'attributes': '{}'},
    ];
    final out = rowsToJson(rows, now);
    expect(out[0]['title'], 'pay rent');
    expect(out[0]['overdue'], isTrue);
    expect(out[0]['due_label'], '2 days ago');
    expect(out[0]['section'], 'to_do');
  });

  test('a row with no status is never sectioned', () {
    final rows = [
      {'id': 1, 'type': 'record', 'title': 'went for a walk', 'body': null,
        'kind': 'event', 'domain': null, 'status': null,
        'occurred_at': now.toIso8601String(), 'due_at': null, 'attributes': '{}'},
    ];
    final out = rowsToJson(rows, now);
    expect(out[0].containsKey('section'), isFalse);
    expect(out[0]['overdue'], isFalse);
  });

  test('due label matches the desktop phrasing', () {
    expect(dueLabel(now, now), 'today');
    expect(dueLabel(now.add(const Duration(days: 1)), now), 'tomorrow');
    expect(dueLabel(now.subtract(const Duration(days: 1)), now), 'yesterday');
    expect(dueLabel(now.subtract(const Duration(days: 5)), now), '5 days ago');
    expect(dueLabel(null, now), isNull);
  });
}
