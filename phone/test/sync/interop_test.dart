// Cross-language conformance with the Python engine
// (tests/test_sync_interop.py): each side consumes the other's committed
// fixture. Regenerate this side's fixture only when the wire format changes on
// purpose:  IO_REGEN_FIXTURES=1 flutter test test/sync/interop_test.dart
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/sync/engine.dart';
import 'package:io_phone/sync/store.dart';

const t0 = '2026-09-01T09:00:00.000Z';
const u = '00000000-0000-4000-8000-000000000001';
const p = '00000000-0000-4000-8000-000000000002';
const pl = '00000000-0000-4000-8000-000000000003';
const r = '00000000-0000-4000-8000-000000000004';
const o = '00000000-0000-4000-8000-000000000005';
const c = '00000000-0000-4000-8000-000000000006';
const msg = '00000000-0000-4000-8000-000000000007';

/// The shared scenario — the Python side seeds exactly the same rows.
Future<void> seed(Database db) async {
  final uid = await db.insert('utterances', {
    'text': 'call Nafay about dinner', 'source': 'text', 'captured_at': t0,
    'sync_id': u, 'updated_at': t0});
  final pid = await db.insert('people', {
    'canonical_name': 'Nafay', 'aliases': '["naf"]', 'notes': 'friend',
    'sync_id': p, 'created_at': t0, 'updated_at': t0});
  final plid = await db.insert('places', {
    'name': 'Arcadian', 'type': 'restaurant', 'aliases': '[]',
    'sync_id': pl, 'created_at': t0, 'updated_at': t0});
  final oid = await db.insert('occasions', {
    'name': 'Eid', 'date': '2026-10-03', 'sync_id': o, 'created_at': t0, 'updated_at': t0});
  final cid = await db.insert('conversations', {
    'title': 'hello', 'started_at': t0, 'last_at': t0, 'sync_id': c, 'updated_at': t0});
  final rid = await db.insert('records', {
    'kind': 'task', 'title': 'call Nafay', 'status': 'open',
    'due_at': '2026-09-09T00:00:00.000Z', 'attributes': '{"meal":"dinner","n":2}',
    'assigned_by_person_id': pid, 'source_utterance_id': uid,
    'sync_id': r, 'created_at': t0, 'updated_at': t0});
  await db.insert('messages', {
    'conversation_id': cid, 'role': 'user', 'text': 'hi ✓', 'source': 'text',
    'sync_id': msg, 'created_at': t0, 'updated_at': t0});
  await db.insert('record_people', {'record_id': rid, 'person_id': pid, 'role': 'with'});
  await db.insert('record_places', {'record_id': rid, 'place_id': plid});
  await db.insert('record_occasions', {'record_id': rid, 'occasion_id': oid});
}

/// What a device must look like after pulling the scenario.
Future<void> checkState(Database db) async {
  final person = (await db.query('people')).single;
  expect([person['sync_id'], person['canonical_name'], person['notes']], [p, 'Nafay', 'friend']);
  expect(jsonDecode(person['aliases'] as String), ['naf']);
  final rec = (await db.query('records')).single;
  expect([rec['sync_id'], rec['kind'], rec['status']], [r, 'task', 'open']);
  expect(jsonDecode(rec['attributes'] as String), {'meal': 'dinner', 'n': 2});
  expect(DateTime.parse(rec['due_at'] as String), DateTime.utc(2026, 9, 9));
  expect(rec['assigned_by_person_id'], person['id']);
  final utt = (await db.query('utterances', where: 'id = ?', whereArgs: [rec['source_utterance_id']])).single;
  expect(utt['sync_id'], u);
  expect((await db.query('places')).single['type'], 'restaurant');
  expect((await db.query('occasions')).single['date'], '2026-10-03');
  expect((await db.query('record_people')).single['role'], 'with');
  expect((await db.query('record_places')).length, 1);
  expect((await db.query('record_occasions')).length, 1);
  final m = (await db.query('messages')).single;
  expect(m['text'], 'hi ✓');
  expect((await db.query('conversations', where: 'id = ?', whereArgs: [m['conversation_id']])).single['title'], 'hello');
}

Directory fixture(String name) => Directory('test/fixtures/sync/$name');

Future<void> copyDir(Directory from, Directory to) async {
  await for (final e in from.list(recursive: true)) {
    if (e is! File) continue;
    final rel = e.path.substring(from.path.length + 1);
    final dest = File('${to.path}/$rel')..createSync(recursive: true);
    dest.writeAsBytesSync(e.readAsBytesSync());
  }
}

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  late Directory tmp;
  setUp(() {
    tmp = Directory.systemTemp.createTempSync('io_interop_');
    addTearDown(() => tmp.deleteSync(recursive: true));
  });

  test('regenerate the Dart fixture', () async {
    final db = await openIoDatabase(path: '${tmp.path}/regen.db');
    addTearDown(db.close);
    await seed(db);
    final out = fixture('dart');
    if (out.existsSync()) out.deleteSync(recursive: true);
    await SyncEngine(db, FolderStore(out), 'DART').push();
    expect(out.existsSync(), isTrue);
  }, skip: Platform.environment['IO_REGEN_FIXTURES'] != '1' ? 'fixture regeneration only' : false);

  test('the Dart engine consumes the Python-written fixture', () async {
    final src = fixture('python');
    expect(src.existsSync(), isTrue,
        reason: 'missing Python fixture: IO_REGEN_FIXTURES=1 uv run pytest tests/test_sync_interop.py -k regen');
    final store = Directory('${tmp.path}/store');
    await copyDir(src, store);
    final db = await openIoDatabase(path: '${tmp.path}/b.db');
    addTearDown(db.close);
    final eng = SyncEngine(db, FolderStore(store), 'DARTB');
    expect(await eng.pull(), greaterThan(0));
    expect(eng.lastError, isNull);
    await checkState(db);
  });

  test('the Dart fixture round-trips through Dart too', () async {
    final src = fixture('dart');
    expect(src.existsSync(), isTrue, reason: 'missing Dart fixture: regenerate it (see the file header)');
    final store = Directory('${tmp.path}/store');
    await copyDir(src, store);
    final db = await openIoDatabase(path: '${tmp.path}/c.db');
    addTearDown(db.close);
    expect(await SyncEngine(db, FolderStore(store), 'DARTC').pull(), greaterThan(0));
    await checkState(db);
  });
}
