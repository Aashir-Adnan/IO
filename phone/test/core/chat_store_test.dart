import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/chat_store.dart';
import 'package:io_phone/core/db.dart';

final now = DateTime.utc(2026, 9, 22, 10, 0);

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('ensureActive creates one conversation and then reuses it', () async {
    final db = await openIoDatabase(inMemory: true);
    final s = ChatStore(db, clock: () => now);
    final a = await s.ensureActive();
    expect(await s.ensureActive(), a);
    expect((await db.query('conversations')).length, 1);
    await db.close();
  });

  test('append stores messages in order and titles the chat from the first user line', () async {
    final db = await openIoDatabase(inMemory: true);
    final s = ChatStore(db, clock: () => now);
    final c = await s.ensureActive();
    await s.append(c, 'user', 'remind me to call mum tomorrow');
    await s.append(c, 'assistant', 'Got it.', kind: 'ack');
    final msgs = await s.messages(c);
    expect(msgs.map((m) => (m.role, m.text)),
        [('user', 'remind me to call mum tomorrow'), ('assistant', 'Got it.')]);
    expect(msgs.last.kind, 'ack');
    final conv = (await db.query('conversations')).single;
    expect(conv['title'], 'remind me to call mum tomorrow');
    await db.close();
  });

  test('a long first message makes a short title', () async {
    final db = await openIoDatabase(inMemory: true);
    final s = ChatStore(db, clock: () => now);
    final c = await s.ensureActive();
    await s.append(c, 'user', 'x' * 100);
    expect(((await db.query('conversations')).single['title'] as String).length, lessThanOrEqualTo(41));
    await db.close();
  });

  test('messages carry sync identity and last_at moves on append', () async {
    final db = await openIoDatabase(inMemory: true);
    var t = now;
    final s = ChatStore(db, clock: () => t);
    final c = await s.ensureActive();
    t = now.add(const Duration(minutes: 5));
    await s.append(c, 'user', 'hi');
    final row = (await db.query('messages')).single;
    expect((row['sync_id'] as String).length, 36);
    expect(row['synced_at'], isNull);
    expect((await db.query('conversations')).single['last_at'], t.toIso8601String());
    await db.close();
  });

  test('context is the recent turns, formatted like the desktop and capped', () async {
    final db = await openIoDatabase(inMemory: true);
    final s = ChatStore(db, clock: () => now);
    final c = await s.ensureActive();
    expect(await s.contextFor(c), isNull);
    await s.append(c, 'user', 'what is on today');
    await s.append(c, 'assistant', 'Nothing yet.');
    expect(await s.contextFor(c), 'you: what is on today\nio: Nothing yet.');
    for (var i = 0; i < 40; i++) {
      await s.append(c, 'user', 'filler message number $i ${'y' * 60}');
    }
    final ctx = (await s.contextFor(c))!;
    expect(ctx.length, lessThanOrEqualTo(1400));
    expect(ctx, contains('filler message number 39'));
    await db.close();
  });

  test('newConversation starts a fresh chat that becomes the active one', () async {
    final db = await openIoDatabase(inMemory: true);
    var t = now;
    final s = ChatStore(db, clock: () => t);
    final a = await s.ensureActive();
    t = now.add(const Duration(hours: 1));
    final b = await s.newConversation();
    expect(b, isNot(a));
    expect(await s.ensureActive(), b);
    await db.close();
  });
}
