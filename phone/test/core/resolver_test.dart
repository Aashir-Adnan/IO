import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/core/resolver.dart';

Future<Database> _db() async => openIoDatabase(inMemory: true);

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('exact match', () async {
    final db = await _db();
    await db.insert('people', {
      'canonical_name': 'Nafay', 'aliases': '["naf"]', 'sync_id': newSyncId(),
      'created_at': 'x', 'updated_at': 'x',
    });
    final out = await EntityResolver(db).resolve('person', 'nafay', []);
    expect(out.entityId, isNotNull);
    expect(out.isNew, isFalse);
    await db.close();
  });

  test('alias match', () async {
    final db = await _db();
    await db.insert('people', {
      'canonical_name': 'Mother', 'aliases': '["mum","mom"]', 'sync_id': newSyncId(),
      'created_at': 'x', 'updated_at': 'x',
    });
    final out = await EntityResolver(db).resolve('person', 'Mum', []);
    expect(out.entityId, isNotNull);
    await db.close();
  });

  test('fuzzy match', () async {
    final db = await _db();
    await db.insert('places', {
      'name': 'Blue Bottle Coffee', 'aliases': '[]', 'sync_id': newSyncId(),
      'created_at': 'x', 'updated_at': 'x',
    });
    final out = await EntityResolver(db).resolve('place', 'Blue Bottle', []);
    expect(out.entityId, isNotNull);
    await db.close();
  });

  test('new entity', () async {
    final db = await _db();
    final out = await EntityResolver(db).resolve('person', 'Zephyr', []);
    expect(out.isNew, isTrue);
    expect(out.entityId, isNull);
    await db.close();
  });

  test('incoming alias matches stored canonical', () async {
    final db = await _db();
    await db.insert('people', {
      'canonical_name': 'Muhammad Nafay', 'aliases': '[]', 'sync_id': newSyncId(),
      'created_at': 'x', 'updated_at': 'x',
    });
    final out = await EntityResolver(db)
        .resolve('person', 'Nafay Khan', ['Muhammad Nafay']);
    expect(out.entityId, isNotNull);
    expect(out.isNew, isFalse);
    await db.close();
  });

  test('fuzzy matches against a stored alias, not just the canonical name', () async {
    final db = await _db();
    await db.insert('items', {
      'name': 'X-1000', 'aliases': '["Blue Bottle Coffee"]', 'sync_id': newSyncId(),
      'created_at': 'x', 'updated_at': 'x',
    });
    final out = await EntityResolver(db).resolve('item', 'Blue Bottle Coffee Co', []);
    expect(out.entityId, isNotNull);
    expect(out.isNew, isFalse);
    await db.close();
  });

  test('resolve does not full-scan: candidate rows are bounded', () async {
    final db = await _db();
    final batch = db.batch();
    for (var i = 0; i < 60; i++) {
      batch.insert('people', {
        'canonical_name': 'Person Number $i', 'aliases': '[]', 'sync_id': newSyncId(),
        'created_at': 'x', 'updated_at': 'x',
      });
    }
    await batch.commit(noResult: true);
    final r = EntityResolver(db);
    final rows = await r.candidateRows('person', 'Totally Unrelated Name', []);
    expect(rows.length, lessThanOrEqualTo(50));
    await db.close();
  });

  test('lookup returns id or null', () async {
    final db = await _db();
    final id = await db.insert('people', {
      'canonical_name': 'Nafay', 'aliases': '[]', 'sync_id': newSyncId(),
      'created_at': 'x', 'updated_at': 'x',
    });
    final r = EntityResolver(db);
    expect(await r.lookup('person', 'nafay'), id);
    expect(await r.lookup('person', 'Absolutely Nobody'), isNull);
    await db.close();
  });

  test('create inserts a new row and returns its id', () async {
    final db = await _db();
    final id = await EntityResolver(db).create('person', 'Zephyr', []);
    final rows = await db.query('people', where: 'id = ?', whereArgs: [id]);
    expect(rows.single['canonical_name'], 'Zephyr');
    await db.close();
  });
}
