/// Memory sync engine — a port of io_assistant/sync/engine.py. Push local
/// changes as per-device batch files; pull and merge other devices' files.
/// Store-agnostic. All merge logic is deterministic Dart; the model never
/// decides identity (rules/llm-boundaries.md).
///
/// Files (each device writes only its own, so writes never conflict):
///   `dev-ID/batch-SEQ.json.gz`     rows/links/tombstones changed since its last push
///   `dev-ID/snapshot-SEQ.json.gz`  its full state as of SEQ; older files are deleted
library;

import 'dart:convert';
import 'dart:io';
import 'package:sqflite/sqflite.dart';
import '../core/resolver.dart';
import 'codec.dart';
import 'store.dart';

const futureSkew = Duration(seconds: 300); // timestamps further ahead are clamped

const _entity = {
  'people': ('person', 'canonical_name'),
  'places': ('place', 'name'),
  'items': ('item', 'name'),
};
// link tables referencing an entity: (link table, entity col, other col)
const _refs = {
  'people': [('record_people', 'person_id', 'record_id'), ('occasion_people', 'person_id', 'occasion_id')],
  'places': [('record_places', 'place_id', 'record_id')],
  'items': [('record_items', 'item_id', 'record_id')],
};

/// Delete a synced row and record a tombstone so the delete reaches the other
/// devices (the desktop does this in a before_flush hook; on the phone every
/// delete path calls this instead).
Future<void> deleteWithTombstone(DatabaseExecutor db, String table, int id) async {
  final rows = await db.query(table, columns: ['sync_id'], where: 'id = ?', whereArgs: [id]);
  if (rows.isEmpty) return;
  await db.insert(
    'sync_tombstones',
    {'table_name': table, 'sync_id': rows.first['sync_id'],
      'deleted_at': DateTime.now().toUtc().toIso8601String()},
    conflictAlgorithm: ConflictAlgorithm.ignore,
  );
  await db.delete(table, where: 'id = ?', whereArgs: [id]);
}

class _Out {
  final Map<String, Object?> payload;
  final String sql;
  final List<Object?> args;
  _Out(this.payload, this.sql, this.args);
}

class SyncEngine {
  final Database db;
  final SyncStore store;
  final String device;
  final DateTime Function() _clock;
  final int snapshotEvery; // batches between snapshots (compaction)
  final int chunk; // items per batch file
  final int fuzzyThreshold;
  String? lastError;

  SyncEngine(this.db, this.store, this.device,
      {DateTime Function()? clock, this.snapshotEvery = 50, this.chunk = 1000,
      this.fuzzyThreshold = 92})
      : _clock = clock ?? (() => DateTime.now().toUtc());

  DateTime _now() => _clock().toUtc();
  String _nowIso() => normIso(_now().toIso8601String());

  // -- state ----------------------------------------------------------------
  Future<Object?> _get(DatabaseExecutor x, String key, Object? dflt) async {
    final rows = await x.query('sync_state', where: 'key = ?', whereArgs: [key]);
    return rows.isEmpty ? dflt : (jsonDecode(rows.first['value'] as String) as Map)['v'];
  }

  Future<void> _set(DatabaseExecutor x, String key, Object? value) => x.insert(
      'sync_state', {'key': key, 'value': jsonEncode({'v': value})},
      conflictAlgorithm: ConflictAlgorithm.replace);

  // -- public ---------------------------------------------------------------
  /// push, pull, then push again (a pull can create merge tombstones and dirty
  /// rows other devices need). Returns (pushed, pulled).
  Future<(int, int)> sync() async {
    var pushed = await push();
    final pulled = await pull();
    pushed += await push();
    final seq = await _get(db, 'seq', 0) as int;
    final snap = await _get(db, 'snapshot_seq', 0) as int;
    if (seq - snap >= snapshotEvery) await snapshot();
    return (pushed, pulled);
  }

  // -- push -----------------------------------------------------------------
  Future<List<_Out>> _allItems(DatabaseExecutor x, {required bool onlyDirty}) async {
    final ids = IdMap(x);
    final out = <_Out>[];
    for (final t in syncTables) {
      final rows = await x.query(t.name,
          where: onlyDirty ? 'synced_at IS NULL OR updated_at > synced_at' : null, orderBy: 'id');
      for (final r in rows) {
        out.add(_Out({'k': 'row', ...await encodeRow(ids, t, r)},
            'UPDATE ${t.name} SET synced_at = ? WHERE id = ? AND updated_at = ?',
            [r['updated_at'], r['id'], r['updated_at']]));
      }
    }
    for (final l in syncLinks) {
      final rows = await x.query(l.name, where: onlyDirty ? 'synced_at IS NULL' : null);
      for (final r in rows) {
        out.add(_Out({'k': 'link', ...await encodeLink(ids, l, r)},
            'UPDATE ${l.name} SET synced_at = ? WHERE ${l.aCol} = ? AND ${l.bCol} = ?',
            ['\u0000now', r[l.aCol], r[l.bCol]]));
      }
    }
    final tombs = await x.query('sync_tombstones',
        where: onlyDirty ? 'synced_at IS NULL' : null, orderBy: 'id');
    for (final r in tombs) {
      out.add(_Out(
          {'k': 'tomb', 't': r['table_name'], 'sync_id': r['sync_id'], 'merged_into': r['merged_into']},
          'UPDATE sync_tombstones SET synced_at = ? WHERE id = ?', ['\u0000now', r['id']]));
    }
    return out;
  }

  List<int> _pack(Object o) => gzip.encode(utf8.encode(jsonEncode(o)));

  /// Write everything changed since its last push as batch file(s). Returns
  /// the number of items pushed.
  Future<int> push() async {
    final items = await _allItems(db, onlyDirty: true);
    if (items.isEmpty) return 0;
    var seq = await _get(db, 'seq', 0) as int;
    for (var i = 0; i < items.length; i += chunk) {
      final part = items.sublist(i, i + chunk > items.length ? items.length : i + chunk);
      seq++;
      await store.put('dev-$device/batch-${seq.toString().padLeft(8, '0')}.json.gz',
          _pack({'v': 1, 'device': device, 'seq': seq, 'items': [for (final o in part) o.payload]}));
      final now = _nowIso();
      await db.transaction((txn) async {
        for (final o in part) {
          // a row edited since it was read stays dirty (the updated_at guard)
          await txn.rawUpdate(o.sql, [for (final a in o.args) a == '\u0000now' ? now : a]);
        }
        await _set(txn, 'seq', seq);
      });
    }
    return items.length;
  }

  /// Publish this device's full state and delete its older files. Call after
  /// push() so nothing dirty is left out.
  Future<void> snapshot() async {
    final seq = await _get(db, 'seq', 0) as int;
    if (seq == 0) return;
    final items = await _allItems(db, onlyDirty: false);
    await store.put('dev-$device/snapshot-${seq.toString().padLeft(8, '0')}.json.gz',
        _pack({'v': 1, 'device': device, 'seq': seq, 'items': [for (final o in items) o.payload]}));
    for (final path in await store.list('dev-$device/')) {
      final parts = path.split('/').last.split('.').first.split('-');
      final n = int.parse(parts[1]);
      if (n < seq || (parts[0] == 'batch' && n <= seq)) await store.delete(path);
    }
    await _set(db, 'snapshot_seq', seq);
  }

  // -- pull -----------------------------------------------------------------
  /// Apply other devices' new files. Returns the number of items applied. A
  /// file that references a row not yet seen is retried on the next pull
  /// (`lastError` says what it is waiting for).
  Future<int> pull() async {
    lastError = null;
    final peers = <String, Map<String, Map<int, String>>>{};
    for (final path in await store.list('dev-')) {
      final slash = path.indexOf('/');
      final dev = path.substring(4, slash);
      if (dev == device) continue;
      final parts = path.substring(slash + 1).split('.').first.split('-');
      peers.putIfAbsent(dev, () => {'batch': {}, 'snapshot': {}})[parts[0]]![int.parse(parts[1])] = path;
    }
    var applied = 0;
    for (final dev in peers.keys.toList()..sort()) {
      try {
        applied += await _pullDevice(dev, peers[dev]!);
      } on Unresolved catch (e) {
        lastError = 'waiting for ${e.table} ${e.syncId}';
      }
    }
    return applied;
  }

  Future<int> _pullDevice(String dev, Map<String, Map<int, String>> files) async {
    var last = await _get(db, 'applied:$dev', 0) as int;
    final plan = <(int, String)>[];
    final snaps = files['snapshot']!;
    if (snaps.isNotEmpty && snaps.keys.reduce((a, b) => a > b ? a : b) > last) {
      last = snaps.keys.reduce((a, b) => a > b ? a : b);
      plan.add((last, snaps[last]!));
    }
    final batches = files['batch']!;
    for (final seq in batches.keys.toList()..sort()) {
      if (seq <= last) continue;
      if (seq != last + 1) break; // a gap (eventual consistency): wait for it
      plan.add((seq, batches[seq]!));
      last = seq;
    }
    var n = 0;
    for (final (seq, path) in plan) {
      n += await _applyFile(dev, seq, path);
    }
    return n;
  }

  Future<int> _applyFile(String dev, int seq, String path) async {
    final data = jsonDecode(utf8.decode(gzip.decode(await store.get(path)))) as Map;
    var n = 0;
    await db.transaction((txn) async {
      final ids = IdMap(txn);
      for (final raw in data['items'] as List) {
        final item = raw as Map;
        n += switch (item['k']) {
          'row' => await _applyRow(txn, ids, item),
          'link' => await _applyLink(txn, ids, item),
          'tomb' => await _applyTomb(txn, ids, item),
          _ => 0,
        };
      }
      await _set(txn, 'applied:$dev', seq);
    });
    return n;
  }

  // -- apply helpers --------------------------------------------------------
  Future<bool> _tombstoned(DatabaseExecutor x, String table, String sid) async =>
      (await x.query('sync_tombstones',
              columns: ['id'], where: 'table_name = ? AND sync_id = ?', whereArgs: [table, sid]))
          .isNotEmpty;

  /// decodeRow, tolerating references to rows that were deleted/merged: a
  /// nullable reference becomes NULL, a required one drops the row.
  Future<Map<String, Object?>?> _decode(
      DatabaseExecutor x, IdMap ids, SyncTable t, Map item) async {
    var cur = item;
    for (var i = 0; i < 4; i++) {
      try {
        return await decodeRow(ids, t, cur);
      } on Unresolved catch (e) {
        if (!await _tombstoned(x, e.table, e.syncId)) rethrow;
        final data = Map<String, Object?>.from(cur['data'] as Map);
        var fixed = false;
        for (final fk in t.fks.entries) {
          if (fk.value == e.table && data[fk.key] == e.syncId) {
            if (!t.nullableFks.contains(fk.key)) return null;
            data[fk.key] = null;
            fixed = true;
          }
        }
        if (!fixed) rethrow;
        cur = {...cur, 'data': data};
      }
    }
    return null;
  }

  Future<int> _applyRow(DatabaseExecutor x, IdMap ids, Map item) async {
    final table = item['t'] as String;
    final t = tableByName[table];
    if (t == null) return 0;
    var sid = item['sync_id'] as String;
    final alias = await x.query('sync_aliases', where: 'alias = ?', whereArgs: [sid]);
    if (alias.isNotEmpty) sid = alias.first['canonical'] as String; // merged away: the survivor
    if (await _tombstoned(x, table, sid)) return 0;

    final cap = _now().add(futureSkew);
    var upd = DateTime.parse(item['updated_at'] as String).toUtc();
    if (upd.isAfter(cap)) upd = cap;
    final updIso = normIso(upd.toIso8601String());

    final kwargs = await _decode(x, ids, t, item);
    if (kwargs == null) return 0;
    final found = await x.query(table, where: 'sync_id = ?', whereArgs: [sid]);

    if (found.isEmpty) {
      if (_entity.containsKey(table) && await _collapse(x, ids, table, sid, kwargs)) return 1;
      final id = await x.insert(table, {...kwargs, 'sync_id': sid, 'updated_at': updIso, 'synced_at': updIso});
      ids.remember(table, id, sid);
      return 1;
    }

    final obj = found.first;
    final wasDone = table == 'records' && obj['status'] == 'done';
    final oldCompleted = obj['completed_at'];
    if (upd.isAfter(DateTime.parse(obj['updated_at'] as String))) { // last writer wins
      final values = {...kwargs, 'updated_at': updIso, 'synced_at': updIso};
      if (wasDone && kwargs['status'] != 'done') { // done is sticky
        values['status'] = 'done';
        values['completed_at'] = oldCompleted;
        values['synced_at'] = null;
      }
      await x.update(table, values, where: 'id = ?', whereArgs: [obj['id']]);
      return 1;
    }
    if (table == 'records' && kwargs['status'] == 'done' && !wasDone) {
      await x.update(table, {'status': 'done', 'completed_at': kwargs['completed_at'], 'synced_at': null},
          where: 'id = ?', whereArgs: [obj['id']]); // publish the completion
      return 1;
    }
    return 0;
  }

  Future<int> _applyLink(DatabaseExecutor x, IdMap ids, Map item) async {
    final l = linkByName[item['t']];
    if (l == null) return 0;
    final Map<String, Object?> kw;
    try {
      kw = await decodeLink(ids, l, item);
    } on Unresolved catch (e) {
      if (await _tombstoned(x, e.table, e.syncId)) return 0;
      rethrow;
    }
    final have = await x.query(l.name,
        where: '${l.aCol} = ? AND ${l.bCol} = ?', whereArgs: [kw[l.aCol], kw[l.bCol]]);
    if (have.isNotEmpty) return 0;
    await x.insert(l.name, {...kw, 'synced_at': _nowIso()});
    return 1;
  }

  Future<int> _applyTomb(DatabaseExecutor x, IdMap ids, Map item) async {
    final table = item['t'] as String;
    final sid = item['sync_id'] as String;
    final into = item['merged_into'] as String?;
    if (!tableByName.containsKey(table)) return 0;
    if (await _tombstoned(x, table, sid)) return 0;
    final rows = await x.query(table, where: 'sync_id = ?', whereArgs: [sid]);
    final row = rows.isEmpty ? null : rows.first;
    if (into != null) {
      await x.insert('sync_aliases', {'alias': sid, 'canonical': into},
          conflictAlgorithm: ConflictAlgorithm.ignore);
      if (row != null) {
        final w = await x.query(table, where: 'sync_id = ?', whereArgs: [into]);
        if (w.isEmpty) { // the survivor's row arrives later
          await x.update(table, {'sync_id': into}, where: 'id = ?', whereArgs: [row['id']]);
          ids.forget();
        } else if (w.first['id'] != row['id']) {
          await _repointAndDelete(x, table, row['id'] as int, w.first['id'] as int);
        }
      }
    } else if (row != null) {
      await x.delete(table, where: 'id = ?', whereArgs: [row['id']]);
    }
    await x.insert('sync_tombstones',
        {'table_name': table, 'sync_id': sid, 'merged_into': into,
          'deleted_at': _nowIso(), 'synced_at': _nowIso()}, // already known everywhere
        conflictAlgorithm: ConflictAlgorithm.ignore);
    return 1;
  }

  // -- duplicate entities ---------------------------------------------------
  /// An incoming entity that confidently matches an existing one (exact or
  /// fuzzy, never vector-only) is the same entity: the earlier-created row
  /// keeps its sync_id, the other is merged into it.
  Future<bool> _collapse(DatabaseExecutor x, IdMap ids, String table, String sid,
      Map<String, Object?> kwargs) async {
    final (etype, nameAttr) = _entity[table]!;
    final incomingAliases = (jsonDecode((kwargs['aliases'] as String?) ?? '[]') as List).cast<String>();
    final name = kwargs[nameAttr] as String;
    final out = await EntityResolver(x, fuzzyThreshold: fuzzyThreshold).resolve(etype, name, incomingAliases);
    if (out.isNew || out.entityId == null) return false;

    final local = (await x.query(table, where: 'id = ?', whereArgs: [out.entityId])).first;
    final old = local['sync_id'] as String;
    final remoteCreated = DateTime.parse(kwargs['created_at'] as String);
    final localCreated = DateTime.parse(local['created_at'] as String);
    final remoteWins = remoteCreated.isBefore(localCreated) ||
        (remoteCreated == localCreated && sid.compareTo(old) < 0);

    final localAliases = (jsonDecode(local['aliases'] as String) as List).cast<String>();
    final merged = [...localAliases];
    for (final n in [...incomingAliases, name]) {
      if (n != local[nameAttr] && !merged.contains(n)) merged.add(n);
    }
    if (merged.length != localAliases.length) { // dirty again, so it is published
      await x.update(table, {'aliases': jsonEncode(merged), 'updated_at': _nowIso()},
          where: 'id = ?', whereArgs: [local['id']]);
    }
    final loser = remoteWins ? old : sid;
    final winner = remoteWins ? sid : old;
    if (remoteWins) {
      await x.update(table, {'sync_id': sid}, where: 'id = ?', whereArgs: [local['id']]);
      ids.forget();
    }
    await x.insert('sync_aliases', {'alias': loser, 'canonical': winner},
        conflictAlgorithm: ConflictAlgorithm.ignore);
    await x.insert('sync_tombstones',
        {'table_name': table, 'sync_id': loser, 'merged_into': winner, 'deleted_at': _nowIso()},
        conflictAlgorithm: ConflictAlgorithm.ignore);
    return true;
  }

  Future<void> _repointAndDelete(DatabaseExecutor x, String table, int loserId, int winnerId) async {
    for (final (link, col, other) in _refs[table] ?? const []) {
      await x.rawUpdate(
          'UPDATE $link SET $col = ? WHERE $col = ? AND NOT EXISTS '
          '(SELECT 1 FROM $link x WHERE x.$col = ? AND x.$other = $link.$other)',
          [winnerId, loserId, winnerId]);
    }
    if (table == 'people') {
      await x.rawUpdate('UPDATE records SET assigned_by_person_id = ? WHERE assigned_by_person_id = ?',
          [winnerId, loserId]);
    }
    await x.delete(table, where: 'id = ?', whereArgs: [loserId]);
  }
}
