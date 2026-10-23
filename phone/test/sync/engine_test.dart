import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:uuid/uuid.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/sync/engine.dart';
import 'package:io_phone/sync/store.dart';

final t0 = DateTime.utc(2026, 9, 1, 9, 0); // safely in the past (the engine clamps future stamps)
const min = Duration(minutes: 1);
String iso(DateTime d) => d.toIso8601String();

late Directory tmp;
var _n = 0;

Future<Database> device() async {
  final db = await openIoDatabase(path: '${tmp.path}/dev${_n++}.db');
  addTearDown(db.close);
  return db;
}

SyncEngine engineFor(Database db, String id, FolderStore store,
        {DateTime Function()? clock, int snapshotEvery = 50, int chunk = 1000}) =>
    SyncEngine(db, store, id, clock: clock, snapshotEvery: snapshotEvery, chunk: chunk);

Future<void> converge(List<SyncEngine> es, {int rounds = 3}) async {
  for (var i = 0; i < rounds; i++) {
    for (final e in es) {
      await e.sync();
    }
  }
}

Future<void> seedFriend(Database db, {String name = 'Ali', String? title, DateTime? created}) async {
  final c = iso(created ?? t0);
  final u = await db.insert('utterances', {
    'text': 'met $name', 'source': 'text', 'captured_at': iso(t0),
    'sync_id': newSyncId(), 'updated_at': iso(t0),
  });
  final p = await db.insert('people', {
    'canonical_name': name, 'aliases': '[]', 'sync_id': newSyncId(),
    'created_at': c, 'updated_at': c,
  });
  final r = await db.insert('records', {
    'kind': 'event', 'title': title ?? 'met $name', 'attributes': '{}',
    'source_utterance_id': u, 'sync_id': newSyncId(), 'created_at': c, 'updated_at': c,
  });
  await db.insert('record_people', {'record_id': r, 'person_id': p});
}

Future<List<Map<String, Object?>>> people(Database db) =>
    db.query('people', orderBy: 'id');

List<int> gz(Object o) => gzip.encode(utf8.encode(jsonEncode(o)));

Future<void> writeBatch(Directory root, String dev, int seq, List<Map> items) async {
  final d = Directory('${root.path}/dev-$dev')..createSync(recursive: true);
  File('${d.path}/batch-${seq.toString().padLeft(8, '0')}.json.gz').writeAsBytesSync(
      gz({'v': 1, 'device': dev, 'seq': seq, 'items': items}));
}

Map<String, Object?> personItem(String sid, String name, {DateTime? upd, DateTime? created}) => {
      'k': 'row', 't': 'people', 'sync_id': sid, 'updated_at': (upd ?? t0).toUtc().toIso8601String(),
      'data': {'canonical_name': name, 'aliases': [], 'notes': null,
        'created_at': (created ?? t0).toUtc().toIso8601String()},
    };

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('io_sync_');
    addTearDown(() => tmp.deleteSync(recursive: true));
  });

  group('push', () {
    test('writes one batch for dirty rows and marks them clean', () async {
      final a = await device();
      final store = FolderStore(tmp);
      await seedFriend(a);
      final e = engineFor(a, 'A', store);
      expect(await e.push(), 4);
      expect(await store.list('dev-A/'), ['dev-A/batch-00000001.json.gz']);
      expect(await e.push(), 0); // nothing new, nothing written
      expect((await store.list('dev-A/')).length, 1);
      final p = (await people(a)).single;
      expect(p['synced_at'], p['updated_at']);
      expect((await a.query('record_people')).single['synced_at'], isNotNull);
    });

    test('an edit pushes only that row, a delete pushes a tombstone once', () async {
      final a = await device();
      final store = FolderStore(tmp);
      await seedFriend(a);
      final e = engineFor(a, 'A', store);
      await e.push();
      await a.update('people', {'notes': 'friend', 'updated_at': iso(t0.add(min))});
      expect(await e.push(), 1);
      final rid = (await a.query('records')).single['id'] as int;
      await deleteWithTombstone(a, 'records', rid);
      expect(await e.push(), 1);
      expect(await e.push(), 0);
    });

    test('large pushes are chunked into sequential batches', () async {
      final a = await device();
      final store = FolderStore(tmp);
      await seedFriend(a);
      expect(await engineFor(a, 'A', store, chunk: 2).push(), 4);
      expect((await store.list('dev-A/')).length, 2);
    });
  });

  group('merge', () {
    test('a friend told to one device appears on the other, affiliations intact', () async {
      final a = await device(), b = await device();
      final store = FolderStore(tmp);
      await seedFriend(a, name: 'Ali');
      await engineFor(a, 'A', store).push();
      expect(await engineFor(b, 'B', store).pull(), 4);
      final pb = (await people(b)).single, pa = (await people(a)).single;
      expect(pb['canonical_name'], 'Ali');
      expect(pb['sync_id'], pa['sync_id']);
      final link = (await b.query('record_people')).single;
      expect(link['person_id'], pb['id']);
    });

    for (final newer in ['a', 'b']) {
      test('the newer edit wins ($newer newer)', () async {
        final a = await device(), b = await device();
        final store = FolderStore(tmp);
        final ea = engineFor(a, 'A', store), eb = engineFor(b, 'B', store);
        await seedFriend(a);
        await converge([ea, eb]);
        await a.update('people', {'notes': 'from A', 'updated_at': iso(t0.add(min * (newer == 'a' ? 2 : 1)))});
        await b.update('people', {'notes': 'from B', 'updated_at': iso(t0.add(min * (newer == 'b' ? 2 : 1)))});
        await converge([ea, eb]);
        final want = newer == 'a' ? 'from A' : 'from B';
        expect((await people(a)).single['notes'], want);
        expect((await people(b)).single['notes'], want);
      });
    }

    test('deletes propagate and a replay cannot resurrect', () async {
      final a = await device(), b = await device();
      final store = FolderStore(tmp);
      final ea = engineFor(a, 'A', store), eb = engineFor(b, 'B', store);
      await seedFriend(a);
      await converge([ea, eb]);
      await deleteWithTombstone(a, 'records', (await a.query('records')).single['id'] as int);
      await converge([ea, eb]);
      expect(await b.query('records'), isEmpty);
      expect(await b.query('record_people'), isEmpty);
      expect((await people(b)).length, 1);
      await b.update('sync_state', {'value': jsonEncode({'v': 0})}, where: 'key = ?', whereArgs: ['applied:A']);
      await eb.pull();
      expect(await b.query('records'), isEmpty);
    });

    test('a completed task stays done against a later stale edit', () async {
      final a = await device(), b = await device();
      final store = FolderStore(tmp);
      final ea = engineFor(a, 'A', store), eb = engineFor(b, 'B', store);
      final u = await a.insert('utterances', {
        'text': 't', 'source': 'text', 'captured_at': iso(t0),
        'sync_id': newSyncId(), 'updated_at': iso(t0)});
      await a.insert('records', {
        'kind': 'task', 'title': 'pay rent', 'status': 'open', 'attributes': '{}',
        'source_utterance_id': u, 'sync_id': newSyncId(), 'created_at': iso(t0), 'updated_at': iso(t0)});
      await converge([ea, eb]);
      await b.update('records', {'status': 'done', 'completed_at': iso(t0.add(min)), 'updated_at': iso(t0.add(min))});
      await a.update('records', {'title': 'pay rent (March)', 'updated_at': iso(t0.add(min * 5))});
      await converge([ea, eb]);
      for (final db in [a, b]) {
        final r = (await db.query('records')).single;
        expect((r['status'], r['title']), ('done', 'pay rent (March)'));
      }
    });

    test('independent duplicate friends collapse to one, earliest wins', () async {
      final a = await device(), b = await device();
      final store = FolderStore(tmp);
      final ea = engineFor(a, 'A', store), eb = engineFor(b, 'B', store);
      await seedFriend(a, name: 'Nafay', title: 'lunch with Nafay', created: t0);
      await seedFriend(b, name: 'Nafay', title: 'dinner with Nafay', created: t0.add(min * 60));
      final aSid = (await people(a)).single['sync_id'];
      await converge([ea, eb], rounds: 4);
      for (final db in [a, b]) {
        final p = (await people(db)).single;
        expect(p['sync_id'], aSid);
        final titles = (await db.query('records')).map((r) => r['title']).toList()..sort();
        expect(titles, ['dinner with Nafay', 'lunch with Nafay']);
        expect((await db.query('record_people')).length, 2);
      }
    });

    test('dissimilar names are not merged', () async {
      final a = await device(), b = await device();
      final store = FolderStore(tmp);
      await seedFriend(a, name: 'Hamza');
      await seedFriend(b, name: 'Hunza');
      await converge([engineFor(a, 'A', store), engineFor(b, 'B', store)]);
      for (final db in [a, b]) {
        expect((await people(db)).map((p) => p['canonical_name']).toList()..sort(), ['Hamza', 'Hunza']);
      }
    });

    test('nothing echoes after a full round', () async {
      final a = await device(), b = await device();
      final store = FolderStore(tmp);
      final ea = engineFor(a, 'A', store), eb = engineFor(b, 'B', store);
      await seedFriend(a);
      await converge([ea, eb]);
      expect(await ea.push(), 0);
      expect(await eb.push(), 0);
    });

    test('an unresolved reference waits for its parent', () async {
      final a = await device();
      final o = const Uuid().v4(), p = const Uuid().v4();
      await writeBatch(tmp, 'X', 1, [
        {'k': 'link', 't': 'occasion_people', 'a': o, 'b': p, 'role': null}
      ]);
      await writeBatch(tmp, 'Y', 1, [
        {'k': 'row', 't': 'occasions', 'sync_id': o, 'updated_at': t0.toIso8601String(),
          'data': {'name': 'Eid', 'date': null, 'recurrence_rule': null, 'created_at': t0.toIso8601String()}},
        personItem(p, 'Zed'),
      ]);
      final e = engineFor(a, 'A', FolderStore(tmp));
      await e.pull();
      expect(e.lastError, contains('waiting'));
      expect((await people(a)).length, 1);
      expect(await a.query('occasion_people'), isEmpty);
      await e.pull();
      expect(e.lastError, isNull);
      expect((await a.query('occasion_people')).length, 1);
    });

    test('future timestamps are clamped', () async {
      final a = await device();
      final now = t0.add(min * 10);
      await writeBatch(tmp, 'X', 1, [
        personItem(const Uuid().v4(), 'Marty', upd: now.add(const Duration(days: 1)))
      ]);
      await engineFor(a, 'A', FolderStore(tmp), clock: () => now).pull();
      final upd = DateTime.parse((await people(a)).single['updated_at'] as String);
      expect(upd.isAfter(now.add(min * 6)), isFalse);
    });

    test('a snapshot compacts and bootstraps a brand-new device', () async {
      final a = await device(), c = await device();
      final store = FolderStore(tmp);
      final ea = engineFor(a, 'A', store, snapshotEvery: 2);
      await seedFriend(a, name: 'Ali');
      await ea.push();
      for (final note in ['one', 'two']) {
        await a.update('people', {'notes': note, 'updated_at': iso(DateTime.now().toUtc())});
        await ea.push();
      }
      await ea.sync(); // 3 batches -> snapshot + compact
      expect(await store.list('dev-A/'), ['dev-A/snapshot-00000003.json.gz']);
      await engineFor(c, 'C', store).pull();
      expect((await people(c)).single['notes'], 'two');
      expect((await c.query('records')).length, 1);
      expect((await c.query('record_people')).length, 1);
    });

    test('python-style timestamps (+00:00, microseconds) are normalised on arrival', () async {
      final a = await device();
      await writeBatch(tmp, 'X', 1, [
        {'k': 'row', 't': 'people', 'sync_id': const Uuid().v4(),
          'updated_at': '2026-09-01T09:00:00.123456+00:00',
          'data': {'canonical_name': 'Zed', 'aliases': ['z'], 'notes': null,
            'created_at': '2026-09-01T09:00:00+00:00'}}
      ]);
      await engineFor(a, 'A', FolderStore(tmp)).pull();
      final p = (await people(a)).single;
      expect(p['created_at'], '2026-09-01T09:00:00.000Z');
      expect(p['updated_at'], '2026-09-01T09:00:00.123Z');
      expect(jsonDecode(p['aliases'] as String), ['z']);
    });
  });
}
