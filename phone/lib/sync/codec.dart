/// Row <-> wire-dict codec for memory sync — a port of io_assistant/sync/
/// codec.py. Local integer ids never leave the device: every foreign key is
/// carried as the target row's global `sync_id`, and affiliations are
/// identified by the pair of parent sync_ids. JSON columns travel as real JSON
/// (SQLite stores them as TEXT), and timestamps are normalised to UTC
/// milliseconds on the way in so lexical comparison in SQL stays valid.
library;

import 'dart:convert';
import 'package:sqflite/sqflite.dart';

class SyncTable {
  final String name;
  final List<String> columns; // everything but id/sync_id/synced_at/updated_at
  final Map<String, String> fks; // fk column -> parent table
  final Set<String> nullableFks;
  final Set<String> jsonCols;
  final Set<String> dtCols;
  const SyncTable(this.name, this.columns,
      {this.fks = const {}, this.nullableFks = const {}, this.jsonCols = const {},
      this.dtCols = const {}});
}

const syncTables = <SyncTable>[
  SyncTable('utterances',
      ['text', 'source', 'captured_at', 'transcription_confidence', 'resolved_intent', 'marker'],
      dtCols: {'captured_at'}),
  SyncTable('people', ['canonical_name', 'aliases', 'notes', 'created_at'],
      jsonCols: {'aliases'}, dtCols: {'created_at'}),
  SyncTable('places', ['name', 'type', 'aliases', 'created_at'],
      jsonCols: {'aliases'}, dtCols: {'created_at'}),
  SyncTable('items', ['name', 'category', 'aliases', 'created_at'],
      jsonCols: {'aliases'}, dtCols: {'created_at'}),
  SyncTable('occasions', ['name', 'date', 'recurrence_rule', 'created_at'],
      dtCols: {'created_at'}),
  SyncTable('conversations', ['title', 'started_at', 'last_at'],
      dtCols: {'started_at', 'last_at'}),
  SyncTable(
      'records',
      ['kind', 'domain', 'title', 'body', 'occurred_at', 'due_at', 'status', 'completed_at',
        'recurrence_rule', 'assigned_by_person_id', 'attributes', 'source_utterance_id',
        'created_at'],
      fks: {'assigned_by_person_id': 'people', 'source_utterance_id': 'utterances'},
      nullableFks: {'assigned_by_person_id'},
      jsonCols: {'attributes'},
      dtCols: {'occurred_at', 'due_at', 'completed_at', 'created_at'}),
  SyncTable('collections',
      ['name', 'kind_slug', 'item_noun', 'synonyms', 'field_hint', 'example_record_id', 'created_at'],
      fks: {'example_record_id': 'records'}, nullableFks: {'example_record_id'},
      jsonCols: {'synonyms', 'field_hint'}, dtCols: {'created_at'}),
  SyncTable(
      'messages',
      ['conversation_id', 'role', 'text', 'kind', 'intent', 'source', 'utterance_id',
        'audio_ms', 'created_at'],
      fks: {'conversation_id': 'conversations', 'utterance_id': 'utterances'},
      nullableFks: {'utterance_id'},
      dtCols: {'created_at'}),
];

class SyncLink {
  final String name;
  final String aCol, aTable, bCol, bTable;
  const SyncLink(this.name, this.aCol, this.aTable, this.bCol, this.bTable);
}

const syncLinks = <SyncLink>[
  SyncLink('record_people', 'record_id', 'records', 'person_id', 'people'),
  SyncLink('record_places', 'record_id', 'records', 'place_id', 'places'),
  SyncLink('record_items', 'record_id', 'records', 'item_id', 'items'),
  SyncLink('record_occasions', 'record_id', 'records', 'occasion_id', 'occasions'),
  SyncLink('occasion_people', 'occasion_id', 'occasions', 'person_id', 'people'),
];

final tableByName = {for (final t in syncTables) t.name: t};
final linkByName = {for (final l in syncLinks) l.name: l};

class Unresolved implements Exception {
  final String table, syncId;
  Unresolved(this.table, this.syncId);
  @override
  String toString() => '$table $syncId not found';
}

/// Normalise any ISO timestamp (Python's `+00:00`, Dart's `Z`, any precision)
/// to UTC milliseconds with a `Z`.
String normIso(String s) => DateTime.parse(s).toUtc().toIso8601String().replaceFirstMapped(
    RegExp(r'\.(\d{3})\d*Z$'), (m) => '.${m[1]}Z');

class IdMap {
  final DatabaseExecutor db;
  final _toSync = <String, String>{};
  final _toLocal = <String, int>{};
  IdMap(this.db);

  Future<String> syncOf(String table, int localId) async {
    final k = '$table:$localId';
    final hit = _toSync[k];
    if (hit != null) return hit;
    final rows = await db.query(table, columns: ['sync_id'], where: 'id = ?', whereArgs: [localId]);
    if (rows.isEmpty) throw StateError('$table $localId missing');
    return _toSync[k] = rows.first['sync_id'] as String;
  }

  /// Follows sync_aliases, so a merged-away id resolves to the survivor.
  Future<int> localOf(String table, String syncId) async {
    final k = '$table:$syncId';
    final hit = _toLocal[k];
    if (hit != null) return hit;
    final alias = await db.query('sync_aliases', where: 'alias = ?', whereArgs: [syncId]);
    final target = alias.isEmpty ? syncId : alias.first['canonical'] as String;
    final rows = await db.query(table, columns: ['id'], where: 'sync_id = ?', whereArgs: [target]);
    if (rows.isEmpty) throw Unresolved(table, syncId);
    return _toLocal[k] = rows.first['id'] as int;
  }

  void remember(String table, int localId, String syncId) {
    _toSync['$table:$localId'] = syncId;
    _toLocal['$table:$syncId'] = localId;
  }

  void forget() {
    _toSync.clear();
    _toLocal.clear();
  }
}

Future<Map<String, Object?>> encodeRow(IdMap ids, SyncTable t, Map<String, Object?> row) async {
  final data = <String, Object?>{};
  for (final c in t.columns) {
    var v = row[c];
    if (t.fks.containsKey(c) && v != null) {
      v = await ids.syncOf(t.fks[c]!, v as int);
    } else if (t.jsonCols.contains(c) && v is String) {
      v = jsonDecode(v);
    }
    data[c] = v;
  }
  return {'t': t.name, 'sync_id': row['sync_id'], 'updated_at': row['updated_at'], 'data': data};
}

/// Local column values for a wire payload. Throws [Unresolved] for a foreign
/// key whose parent isn't here (yet).
Future<Map<String, Object?>> decodeRow(IdMap ids, SyncTable t, Map payload) async {
  final data = payload['data'] as Map;
  final out = <String, Object?>{};
  for (final c in t.columns) {
    if (!data.containsKey(c)) continue;
    var v = data[c];
    if (t.fks.containsKey(c) && v != null) {
      v = await ids.localOf(t.fks[c]!, v as String);
    } else if (t.jsonCols.contains(c) && v != null) {
      v = jsonEncode(v);
    } else if (t.dtCols.contains(c) && v != null) {
      v = normIso(v as String);
    }
    out[c] = v;
  }
  return out;
}

Future<Map<String, Object?>> encodeLink(IdMap ids, SyncLink l, Map<String, Object?> row) async => {
      't': l.name,
      'a': await ids.syncOf(l.aTable, row[l.aCol] as int),
      'b': await ids.syncOf(l.bTable, row[l.bCol] as int),
      'role': row['role'],
    };

Future<Map<String, Object?>> decodeLink(IdMap ids, SyncLink l, Map payload) async => {
      l.aCol: await ids.localOf(l.aTable, payload['a'] as String),
      l.bCol: await ids.localOf(l.bTable, payload['b'] as String),
      'role': payload['role'],
    };
