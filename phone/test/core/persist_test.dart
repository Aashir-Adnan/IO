import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:io_phone/core/db.dart';
import 'package:io_phone/core/dates.dart';
import 'package:io_phone/core/resolver.dart';
import 'package:io_phone/core/extraction.dart';
import 'package:io_phone/core/persist.dart';

final now = DateTime.utc(2026, 9, 7, 18, 0);

ExtractionResult arcadian() => ExtractionResult(
      people: [
        ExtractedPerson(name: 'Nafay', confidence: 0.95),
        ExtractedPerson(name: 'Eelian', confidence: 0.9),
      ],
      places: [ExtractedPlace(name: 'Arcadian', confidence: 0.9)],
      occasions: [ExtractedOccasion(name: "Nafay and Eelian's birthday", confidence: 0.8)],
      records: [
        ExtractedRecord(
          kind: 'event', domain: 'social', title: 'went out to eat', whenPhrase: 'today',
          people: ['Nafay', 'Eelian'], places: ['Arcadian'],
          occasions: ["Nafay and Eelian's birthday"],
          attributes: {'meal': 'dinner'}, confidence: 0.9,
        ),
      ],
    );

Future<int> countRows(dynamic db, String table, {String? where, List<Object?>? args}) async {
  final rows = await db.query(table, where: where, whereArgs: args);
  return (rows as List).length;
}

void main() {
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  test('persists a record with links', () async {
    final db = await openIoDatabase(inMemory: true);
    final res = EntityResolver(db);
    final out = await persistStore(db, res,
        utteranceText: 'I went out with Nafay to eat at Arcadian', source: 'text',
        capturedAt: now, extraction: arcadian(), now: now, confidenceGate: 0.6);
    expect(out.gated, isFalse);
    expect(out.recordIds.length, 1);
    final rec = (await db.query('records', where: 'id = ?', whereArgs: [out.recordIds[0]])).single;
    expect(rec['kind'], 'event');
    expect((jsonDecode(rec['attributes'] as String))['meal'], 'dinner');
    expect((rec['occurred_at'] as String).startsWith('2026-09-07'), isTrue);
    expect(await countRows(db, 'record_people', where: 'record_id = ?', args: [out.recordIds[0]]), 2);
    expect(await countRows(db, 'record_places', where: 'record_id = ?', args: [out.recordIds[0]]), 1);
    expect(await countRows(db, 'record_occasions', where: 'record_id = ?', args: [out.recordIds[0]]), 1);
    expect(out.newEntities.length, 3);
    await db.close();
  });

  test('arbitrary kind is normalized', () async {
    final db = await openIoDatabase(inMemory: true);
    final ext = ExtractionResult(records: [ExtractedRecord(
        kind: 'Gym Session', domain: 'fitness', title: 'leg day', whenPhrase: 'today', confidence: 0.9)]);
    final out = await persistStore(db, EntityResolver(db),
        utteranceText: 'did leg day', source: 'text', capturedAt: now,
        extraction: ext, now: now, confidenceGate: 0.6);
    final rec = (await db.query('records', where: 'id = ?', whereArgs: [out.recordIds[0]])).single;
    expect(rec['kind'], 'gym_session');
    expect(rec['domain'], 'other');
    await db.close();
  });

  test('low confidence gates and keeps only the utterance', () async {
    final db = await openIoDatabase(inMemory: true);
    final ext = arcadian()..records[0] = arcadian().records[0].copyWith(confidence: 0.3);
    final out = await persistStore(db, EntityResolver(db),
        utteranceText: 'mumble arcadian', source: 'text', capturedAt: now,
        extraction: ext, now: now, confidenceGate: 0.6);
    expect(out.gated, isTrue);
    expect(out.gateReasons.join(' ').toLowerCase(), contains('low confidence'));
    expect(await countRows(db, 'records'), 0);
    expect(await countRows(db, 'utterances', where: 'id = ?', args: [out.utteranceId]), 1);
    await db.close();
  });

  test('confirmed bypasses the gate', () async {
    final db = await openIoDatabase(inMemory: true);
    final ext = arcadian()..records[0] = arcadian().records[0].copyWith(confidence: 0.3);
    final out = await persistStore(db, EntityResolver(db),
        utteranceText: 'x', source: 'text', capturedAt: now,
        extraction: ext, now: now, confidenceGate: 0.6, confirmed: true);
    expect(out.gated, isFalse);
    expect(out.recordIds.length, 1);
    await db.close();
  });

  test('a resolver failure during the write pass rolls back, utterance kept', () async {
    final db = await openIoDatabase(inMemory: true);
    final res = _FailingOnSecondCreate(db);
    final text = 'I went out with Nafay to eat at Arcadian';
    await expectLater(
      persistStore(db, res, utteranceText: text, source: 'text', capturedAt: now,
          extraction: arcadian(), now: now, confidenceGate: 0.6),
      throwsA(isA<PersistError>()),
    );
    expect(await countRows(db, 'records'), 0);
    expect(await countRows(db, 'people'), 0);
    expect(await countRows(db, 'utterances', where: 'text = ?', args: [text]), 1);
    await db.close();
  });

  test('a name repeated in one extraction creates exactly one entity', () async {
    final db = await openIoDatabase(inMemory: true);
    final ext = ExtractionResult(
      people: [
        ExtractedPerson(name: 'Nafay', confidence: 0.9),
        ExtractedPerson(name: 'Nafay', confidence: 0.9),
        ExtractedPerson(name: 'nafay', confidence: 0.9),
      ],
      records: [ExtractedRecord(kind: 'note', domain: 'social', title: 'saw Nafay',
          whenPhrase: 'today', people: ['Nafay'], confidence: 0.9)],
    );
    final out = await persistStore(db, EntityResolver(db),
        utteranceText: 'ran into Nafay', source: 'text', capturedAt: now,
        extraction: ext, now: now, confidenceGate: 0.6);
    expect(out.gated, isFalse);
    expect(await countRows(db, 'people', where: 'canonical_name = ?', args: ['Nafay']), 1);
    expect(await countRows(db, 'people'), 1);
    expect(out.newEntities, [('person', 'Nafay')]);
    await db.close();
  });

  test('a record-only person (not in the top-level list) still links', () async {
    final db = await openIoDatabase(inMemory: true);
    final ext = ExtractionResult(records: [ExtractedRecord(
        kind: 'event', title: 'lunch', whenPhrase: 'today', people: ['Sana'], confidence: 0.9)]);
    final out = await persistStore(db, EntityResolver(db),
        utteranceText: 'lunch with Sana', source: 'text', capturedAt: now,
        extraction: ext, now: now, confidenceGate: 0.6);
    expect(await countRows(db, 'record_people', where: 'record_id = ?', args: [out.recordIds[0]]), 1);
    expect(await countRows(db, 'people', where: 'canonical_name = ?', args: ['Sana']), 1);
    await db.close();
  });

  test('a record-item link persists', () async {
    final db = await openIoDatabase(inMemory: true);
    final ext = ExtractionResult(
      items: [ExtractedItem(name: 'drill', confidence: 0.9)],
      records: [ExtractedRecord(kind: 'task', title: 'return the drill', items: ['drill'], confidence: 0.9)],
    );
    final out = await persistStore(db, EntityResolver(db),
        utteranceText: 'return the drill', source: 'text', capturedAt: now,
        extraction: ext, now: now, confidenceGate: 0.6);
    expect(await countRows(db, 'record_items', where: 'record_id = ?', args: [out.recordIds[0]]), 1);
    await db.close();
  });

  Future<PersistResult> persistOne(dynamic db, ExtractedRecord rec) => persistStore(
      db, EntityResolver(db), utteranceText: 'x', source: 'text', capturedAt: now,
      extraction: ExtractionResult(records: [rec]), now: now, confidenceGate: 0.6);

  test('a bare task defaults to due today', () async {
    final db = await openIoDatabase(inMemory: true);
    final out = await persistOne(db, ExtractedRecord(kind: 'task', title: 'call the dentist', confidence: 0.9));
    expect(out.gated, isFalse);
    final rec = (await db.query('records', where: 'id = ?', whereArgs: [out.recordIds[0]])).single;
    expect(rec['due_at'], startOfDay(now).toIso8601String());
    expect(rec['occurred_at'], isNull);
    expect(rec['status'], 'open');
    await db.close();
  });

  test('a someday task stays dateless', () async {
    final db = await openIoDatabase(inMemory: true);
    final out = await persistOne(db, ExtractedRecord(
        kind: 'task', title: 'learn the cello', whenPhrase: 'someday', confidence: 0.9));
    final rec = (await db.query('records', where: 'id = ?', whereArgs: [out.recordIds[0]])).single;
    expect(rec['due_at'], isNull);
    await db.close();
  });

  test('a non-task kind is never defaulted', () async {
    final db = await openIoDatabase(inMemory: true);
    final out = await persistOne(db, ExtractedRecord(kind: 'gym_session', title: 'leg day', confidence: 0.9));
    final rec = (await db.query('records', where: 'id = ?', whereArgs: [out.recordIds[0]])).single;
    expect(rec['due_at'], isNull);
    expect(rec['occurred_at'], isNull);
    await db.close();
  });

  test('a recurring chore is not defaulted to due today', () async {
    final db = await openIoDatabase(inMemory: true);
    final out = await persistOne(db, ExtractedRecord(
        kind: 'chore', title: 'take out the trash', recurrencePhrase: 'every Monday', confidence: 0.9));
    final rec = (await db.query('records', where: 'id = ?', whereArgs: [out.recordIds[0]])).single;
    expect(rec['due_at'], isNull);
    expect(rec['recurrence_rule'], 'FREQ=WEEKLY;BYDAY=MO');
    await db.close();
  });

  test('a task with an explicit due phrase keeps it', () async {
    final db = await openIoDatabase(inMemory: true);
    final out = await persistOne(db, ExtractedRecord(
        kind: 'task', title: 'file taxes', duePhrase: 'tomorrow', confidence: 0.9));
    final rec = (await db.query('records', where: 'id = ?', whereArgs: [out.recordIds[0]])).single;
    expect(rec['due_at'], isNotNull);
    expect(rec['due_at'], isNot(startOfDay(now).toIso8601String()));
    await db.close();
  });

  test('an unreadable recurrence phrase gates', () async {
    final db = await openIoDatabase(inMemory: true);
    final ext = ExtractionResult(records: [ExtractedRecord(
        kind: 'chore', title: 'water plants',
        recurrencePhrase: 'whenever the soil looks dry', confidence: 0.9)]);
    final out = await persistStore(db, EntityResolver(db),
        utteranceText: 'water the plants when dry', source: 'text', capturedAt: now,
        extraction: ext, now: now, confidenceGate: 0.6);
    expect(out.gated, isTrue);
    expect(out.gateReasons.any((r) => r.contains('repeat rule')), isTrue);
    await db.close();
  });
}

/// A resolver whose second `.create` call throws — proves a write-pass
/// failure rolls back and leaves only the already-committed utterance.
class _FailingOnSecondCreate extends EntityResolver {
  int calls = 0;
  _FailingOnSecondCreate(super.db);

  @override
  Future<int> create(String entityType, String name, List<String> aliases) async {
    calls++;
    if (calls >= 2) throw StateError('boom');
    return super.create(entityType, name, aliases);
  }
}
