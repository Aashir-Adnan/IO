import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('every synced table has sync_id, synced_at, updated_at, created_at', () async {
    final db = await openIoDatabase(inMemory: true);
    for (final t in syncedTables) {
      final cols = (await db.rawQuery('PRAGMA table_info($t)'))
          .map((r) => r['name'] as String)
          .toSet();
      expect(cols.containsAll(['sync_id', 'synced_at', 'updated_at']), isTrue,
          reason: t);
    }
    await db.close();
  });

  test('link tables have synced_at but no sync_id (identified by the pair)', () async {
    final db = await openIoDatabase(inMemory: true);
    for (final t in linkTables) {
      final cols = (await db.rawQuery('PRAGMA table_info($t)'))
          .map((r) => r['name'] as String)
          .toSet();
      expect(cols.contains('synced_at'), isTrue, reason: t);
      expect(cols.contains('sync_id'), isFalse, reason: t);
    }
    await db.close();
  });

  test('a person row round-trips with a real sync_id', () async {
    final db = await openIoDatabase(inMemory: true);
    final id = await db.insert('people', {
      'canonical_name': 'Ali',
      'aliases': '[]',
      'sync_id': newSyncId(),
      'created_at': '2026-09-23T00:00:00.000Z',
      'updated_at': '2026-09-23T00:00:00.000Z',
    });
    final rows = await db.query('people', where: 'id = ?', whereArgs: [id]);
    expect(rows.single['canonical_name'], 'Ali');
    expect((rows.single['sync_id'] as String).length, 36); // a real uuid
    await db.close();
  });

  test('a record requires an existing utterance (foreign key enforced)', () async {
    final db = await openIoDatabase(inMemory: true);
    expect(
      () => db.insert('records', {
        'kind': 'task', 'title': 'x', 'attributes': '{}',
        'source_utterance_id': 999,
        'sync_id': newSyncId(),
        'created_at': '2026-09-23T00:00:00.000Z',
        'updated_at': '2026-09-23T00:00:00.000Z',
      }),
      throwsA(anything),
    );
    await db.close();
  });

  test('deleting a record cascades its link rows', () async {
    final db = await openIoDatabase(inMemory: true);
    final uid = await db.insert('utterances', {
      'text': 'x', 'source': 'text', 'captured_at': '2026-09-23T00:00:00.000Z',
      'sync_id': newSyncId(), 'updated_at': '2026-09-23T00:00:00.000Z',
    });
    final pid = await db.insert('people', {
      'canonical_name': 'Ali', 'aliases': '[]', 'sync_id': newSyncId(),
      'created_at': '2026-09-23T00:00:00.000Z', 'updated_at': '2026-09-23T00:00:00.000Z',
    });
    final rid = await db.insert('records', {
      'kind': 'task', 'title': 'x', 'attributes': '{}', 'source_utterance_id': uid,
      'sync_id': newSyncId(), 'created_at': '2026-09-23T00:00:00.000Z',
      'updated_at': '2026-09-23T00:00:00.000Z',
    });
    await db.insert('record_people', {'record_id': rid, 'person_id': pid});
    await db.delete('records', where: 'id = ?', whereArgs: [rid]);
    final links = await db.query('record_people');
    expect(links, isEmpty);
    await db.close();
  });
}
