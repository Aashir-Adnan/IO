import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/sync/auth.dart';
import 'package:io_phone/sync/store.dart';
import 'package:io_phone/sync/sync_manager.dart';

class FakeAuth implements AuthProvider {
  bool signedIn;
  Object? failWith;
  int signIns = 0;
  FakeAuth({this.signedIn = false});
  @override
  Future<bool> restore() async => signedIn;
  @override
  Future<void> signIn() async {
    signIns++;
    if (failWith != null) throw failWith!;
    signedIn = true;
  }

  @override
  Future<void> signOut() async => signedIn = false;
  @override
  Future<String> accessToken() async => 'tok';
}

late Directory tmp;
var _n = 0;

Future<Database> device() async {
  final db = await openIoDatabase(path: '${tmp.path}/d${_n++}.db');
  addTearDown(db.close);
  return db;
}

SyncManager manager(Database db, AuthProvider auth, SyncStore store,
        {Duration interval = const Duration(hours: 1)}) =>
    SyncManager(db: db, auth: auth, storeFactory: () => store, interval: interval);

Future<void> addTask(Database db, String title) async {
  final now = DateTime.now().toUtc().toIso8601String();
  final u = await db.insert('utterances', {
    'text': title, 'source': 'text', 'captured_at': now, 'sync_id': newSyncId(), 'updated_at': now});
  await db.insert('records', {
    'kind': 'task', 'title': title, 'status': 'open', 'attributes': '{}',
    'source_utterance_id': u, 'sync_id': newSyncId(), 'created_at': now, 'updated_at': now});
}

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('io_mgr_');
    addTearDown(() => tmp.deleteSync(recursive: true));
  });

  test('signed out: sync says so instead of touching the network', () async {
    final db = await device();
    final m = manager(db, FakeAuth(), FolderStore(tmp));
    await m.refresh();
    expect(m.signedIn, isFalse);
    await m.syncNow();
    expect(m.error, contains('sign in'));
    expect(m.lastSyncedAt, isNull);
  });

  test('signing in syncs straight away and notifies', () async {
    final db = await device();
    final m = manager(db, FakeAuth(), FolderStore(tmp));
    var notified = 0;
    m.addListener(() => notified++);
    await m.signIn();
    expect(m.signedIn, isTrue);
    expect(m.lastSyncedAt, isNotNull);
    expect(m.error, isNull);
    expect(m.signingIn, isFalse);
    expect(notified, greaterThan(1));
  });

  test('a failed sign-in is reported, not thrown', () async {
    final db = await device();
    final m = manager(db, FakeAuth()..failWith = StateError('user closed the window'), FolderStore(tmp));
    await m.signIn();
    expect(m.signedIn, isFalse);
    expect(m.error, contains('user closed the window'));
    expect(m.signingIn, isFalse);
  });

  test('a store failure becomes an error on the manager, never an exception', () async {
    final db = await device();
    final m = SyncManager(
        db: db, auth: FakeAuth(signedIn: true),
        storeFactory: () => throw const FileSystemException('disk full'));
    await m.refresh();
    await m.syncNow();
    expect(m.error, contains('disk full'));
    expect(m.syncing, isFalse);
  });

  test('two phones-worth of state converge through the manager', () async {
    final a = await device(), b = await device();
    final store = FolderStore(tmp);
    final ma = manager(a, FakeAuth(signedIn: true), store);
    final mb = manager(b, FakeAuth(signedIn: true), store);
    await ma.refresh();
    await mb.refresh();
    await addTask(a, 'call mum');
    await ma.syncNow();
    await mb.syncNow();
    expect((await b.query('records')).map((r) => r['title']), ['call mum']);
    expect(ma.deviceId, isNot(mb.deviceId));
  });

  test('the device id is stable across restarts', () async {
    final db = await device();
    final one = manager(db, FakeAuth(), FolderStore(tmp));
    await one.refresh();
    final two = manager(db, FakeAuth(), FolderStore(tmp)); // "after a restart"
    await two.refresh();
    expect(two.deviceId, one.deviceId);
    expect(one.deviceId.length, 12);
  });

  test('sign out clears the signed-in state and keeps local memories', () async {
    final db = await device();
    final auth = FakeAuth(signedIn: true);
    final m = manager(db, auth, FolderStore(tmp));
    await m.refresh();
    await addTask(db, 'keep me');
    await m.signOut();
    expect(m.signedIn, isFalse);
    expect((await db.query('records')).length, 1);
  });

  test('poke syncs soon after a local write, only when signed in', () async {
    final a = await device(), b = await device();
    final store = FolderStore(tmp);
    final ma = manager(a, FakeAuth(signedIn: true), store);
    await ma.refresh();
    await addTask(a, 'pushed by poke');
    ma.poke();
    await ma.idle(); // wait for the in-flight sync
    final mb = manager(b, FakeAuth(signedIn: true), store);
    await mb.refresh();
    await mb.syncNow();
    expect((await b.query('records')).length, 1);

    final out = manager(await device(), FakeAuth(), store);
    out.poke(); // signed out: a no-op
    await out.idle();
    expect(out.lastSyncedAt, isNull);
  });

  test('the background timer keeps syncing while started', () async {
    final db = await device();
    final m = manager(db, FakeAuth(signedIn: true), FolderStore(tmp),
        interval: const Duration(milliseconds: 40));
    await m.refresh();
    m.start();
    await Future<void>.delayed(const Duration(milliseconds: 250));
    m.stop();
    expect(m.lastSyncedAt, isNotNull);
  });
}
