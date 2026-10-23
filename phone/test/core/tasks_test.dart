import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite/sqflite.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/core/tasks.dart';

final now = DateTime.utc(2026, 9, 22, 15, 30);
const day = Duration(days: 1);

Future<int> utt(Database db) => db.insert('utterances', {
      'text': 's', 'source': 'text', 'captured_at': now.toIso8601String(),
      'sync_id': newSyncId(), 'updated_at': now.toIso8601String(),
    });

Future<int> rec(Database db, int uid, String title,
    {DateTime? due, String kind = 'task', String? status = 'open'}) {
  final iso = now.toIso8601String();
  return db.insert('records', {
    'kind': kind, 'title': title, 'status': status, 'due_at': due?.toIso8601String(),
    'attributes': '{}', 'source_utterance_id': uid,
    'sync_id': newSyncId(), 'created_at': iso, 'updated_at': iso,
  });
}

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('pending tasks are ordered and grouped like the desktop widget', () async {
    final db = await openIoDatabase(inMemory: true);
    final u = await utt(db);
    await rec(db, u, 'someday');
    await rec(db, u, 'next week', due: now.add(day * 5));
    await rec(db, u, 'today', due: DateTime.utc(2026, 9, 22)); // bare task: due 00:00 today
    await rec(db, u, 'overdue', due: now.subtract(day * 3));
    await rec(db, u, 'tomorrow chore', due: now.add(day), kind: 'chore');
    await rec(db, u, 'finished', due: now.subtract(day), status: 'done');
    await rec(db, u, 'a note', due: now, kind: 'note', status: null);
    final out = await pendingTasks(db, now);
    expect(out.map((t) => t['title']),
        ['overdue', 'today', 'tomorrow chore', 'next week', 'someday']);
    expect(out.map((t) => t['group']),
        ['overdue', 'today', 'upcoming', 'upcoming', 'none']);
    expect(out[0]['due_label'], '3 days ago');
    expect(out[1]['due_label'], 'Today');
    expect(out.last['due_label'], isNull);
    await db.close();
  });

  test('a task due at 00:00 today is today, not overdue', () async {
    final db = await openIoDatabase(inMemory: true);
    final u = await utt(db);
    await rec(db, u, 'bare', due: DateTime.utc(2026, 9, 22));
    expect((await pendingTasks(db, now)).single['group'], 'today');
    await db.close();
  });

  test('the limit is respected', () async {
    final db = await openIoDatabase(inMemory: true);
    final u = await utt(db);
    for (var i = 0; i < 5; i++) {
      await rec(db, u, 't$i', due: now.add(day * i));
    }
    expect((await pendingTasks(db, now, limit: 3)).length, 3);
    await db.close();
  });

  test('completing stamps completed_at once and bumps updated_at for sync', () async {
    final db = await openIoDatabase(inMemory: true);
    final u = await utt(db);
    final id = await rec(db, u, 'pay rent', due: now);
    await completeTask(db, id, now);
    final r = (await db.query('records', where: 'id = ?', whereArgs: [id])).single;
    expect(r['status'], 'done');
    expect(r['completed_at'], now.toIso8601String());
    expect(r['updated_at'], now.toIso8601String());
    expect(await pendingTasks(db, now), isEmpty);

    final later = now.add(const Duration(hours: 2));
    await completeTask(db, id, later); // already done: completed_at stays
    final r2 = (await db.query('records', where: 'id = ?', whereArgs: [id])).single;
    expect(r2['completed_at'], now.toIso8601String());
    await db.close();
  });

  test('reopening clears completed_at', () async {
    final db = await openIoDatabase(inMemory: true);
    final u = await utt(db);
    final id = await rec(db, u, 'pay rent');
    await completeTask(db, id, now);
    await reopenTask(db, id, now);
    final r = (await db.query('records', where: 'id = ?', whereArgs: [id])).single;
    expect(r['status'], 'open');
    expect(r['completed_at'], isNull);
    await db.close();
  });
}
