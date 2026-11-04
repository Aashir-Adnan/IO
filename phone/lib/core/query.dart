/// The query pipeline — a port of io_assistant/query/{compile,retrieve,
/// respond}.py's structured-retrieval path. No semantic branch: the phone has
/// no embedder (see resolver.dart), so retrieval is structured-only, exactly
/// what the desktop falls back to without an embedder.
///
/// ponytail: `compile`/`retrieve` here cover target_type "record" only — the
/// desktop's person/place/occasion direct-query targets aren't ported (real
/// chat usage is overwhelmingly record queries: tasks, notes, events).
/// `ground_plan` (parsing the model's raw plan JSON into a SubQuery) is not
/// here either — it belongs with the chat-loop task that actually calls
/// decide. Upgrade both alongside that task if a query needs them.
library;

import 'dart:convert';
import 'package:sqflite/sqflite.dart';

class TimeWindow {
  final DateTime? start;
  final DateTime? end;
  const TimeWindow({this.start, this.end});
}

class SubQuery {
  final String targetType; // "record" | "person" | "place" | "occasion"
  final List<String>? kindFilter;
  final List<String>? domainFilter;
  final List<String> entities;
  final TimeWindow? timeWindow;
  final List<String>? statusFilter;
  final String aggregation; // "list" | "count"
  const SubQuery({
    this.targetType = 'record', this.kindFilter, this.domainFilter,
    this.entities = const [], this.timeWindow, this.statusFilter,
    this.aggregation = 'list',
  });
}

const _linkTable = {
  'person': ('record_people', 'person_id'),
  'place': ('record_places', 'place_id'),
  'item': ('record_items', 'item_id'),
  'occasion': ('record_occasions', 'occasion_id'),
};

/// (where clause, args) for the kind/domain/status/entity filters shared by
/// the list and count queries. Never touches time — the caller adds that.
(String, List<Object?>) _conds(SubQuery sq, Map<String, List<int>> entityIds) {
  final clauses = <String>[];
  final args = <Object?>[];

  if (sq.kindFilter != null && sq.kindFilter!.isNotEmpty) {
    clauses.add('kind IN (${List.filled(sq.kindFilter!.length, '?').join(',')})');
    args.addAll(sq.kindFilter!);
  }
  if (sq.domainFilter != null && sq.domainFilter!.isNotEmpty) {
    clauses.add('domain IN (${List.filled(sq.domainFilter!.length, '?').join(',')})');
    args.addAll(sq.domainFilter!);
  }
  if (sq.statusFilter != null && sq.statusFilter!.isNotEmpty) {
    clauses.add('status IN (${List.filled(sq.statusFilter!.length, '?').join(',')})');
    args.addAll(sq.statusFilter!);
  }
  for (final entry in _linkTable.entries) {
    final ids = entityIds[entry.key] ?? const <int>[];
    if (ids.isEmpty) continue;
    final (table, col) = entry.value;
    clauses.add('EXISTS (SELECT 1 FROM $table WHERE $table.record_id = records.id '
        'AND $table.$col IN (${List.filled(ids.length, '?').join(',')}))');
    args.addAll(ids);
  }
  return (clauses.join(' AND '), args);
}

const _recency = 'COALESCE(occurred_at, due_at, created_at)';

/// The list/count filter, including time-window and (list only, since the
/// count and list must agree — see compile.py) the same read-time
/// roll-forward: an overdue OPEN task is always in-window, so "what's due" /
/// "anything overdue" surfaces it regardless of the literal window. done/
/// dropped rows still obey the window strictly.
(String, List<Object?>) _whereAndArgs(SubQuery sq, Map<String, List<int>> entityIds, DateTime now) {
  final (baseWhere, args) = _conds(sq, entityIds);
  final clauses = [if (baseWhere.isNotEmpty) baseWhere];

  final openRollforward = sq.statusFilter != null && sq.statusFilter!.contains('open');
  if (sq.timeWindow != null) {
    final window = <String>[];
    final windowArgs = <Object?>[];
    if (sq.timeWindow!.start != null) {
      window.add('$_recency >= ?');
      windowArgs.add(sq.timeWindow!.start!.toIso8601String());
    }
    if (sq.timeWindow!.end != null) {
      window.add('$_recency <= ?');
      windowArgs.add(sq.timeWindow!.end!.toIso8601String());
    }
    if (window.isNotEmpty) {
      if (openRollforward) {
        clauses.add('((${window.join(' AND ')}) OR (status = ? AND due_at <= ?))');
        args.addAll(windowArgs);
        args.addAll(['open', now.toIso8601String()]);
      } else {
        clauses.add(window.join(' AND '));
        args.addAll(windowArgs);
      }
    }
  }
  return (clauses.join(' AND '), args);
}

Future<List<Map<String, Object?>>> retrieve(
    Database db, SubQuery sq, Map<String, List<int>> entityIds, DateTime now) async {
  final (where, args) = _whereAndArgs(sq, entityIds, now);
  final sql = 'SELECT * FROM records${where.isEmpty ? '' : ' WHERE $where'} '
      'ORDER BY $_recency DESC LIMIT 200';
  return db.rawQuery(sql, args);
}

Future<int> retrieveCount(
    Database db, SubQuery sq, Map<String, List<int>> entityIds, DateTime now) async {
  final (where, args) = _whereAndArgs(sq, entityIds, now);
  final sql = 'SELECT COUNT(*) AS n FROM records${where.isEmpty ? '' : ' WHERE $where'}';
  final rows = await db.rawQuery(sql, args);
  return rows.first['n'] as int;
}

// --- respond.py: shaping rows for the phrasing call ------------------------

String? _dueLabelInternal(DateTime due, DateTime now) {
  final days = DateTime.utc(due.year, due.month, due.day)
      .difference(DateTime.utc(now.year, now.month, now.day))
      .inDays;
  if (days == 0) return 'today';
  if (days == 1) return 'tomorrow';
  if (days == -1) return 'yesterday';
  if (days < 0) return '${-days} days ago';
  if (days <= 6) return _weekday(due);
  return '${_weekday(due)} ${due.day} ${_month(due)}';
}

String? dueLabel(DateTime? due, DateTime now) =>
    due == null ? null : _dueLabelInternal(due, now);

const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
String _weekday(DateTime d) => _weekdays[d.weekday - 1];
String _month(DateTime d) => _months[d.month - 1];

String sectionFor(String? status) => status == 'done' ? 'done' : 'to_do';

String _clip(String s, [int n = 600]) => s.length <= n ? s : '${s.substring(0, n - 1).trimRight()}…';

/// A SQLite record row -> the JSON shape the phrasing call reads. Dates and
/// overdue-ness are computed here, in Dart, never handed to the model to
/// work out (rules/llm-boundaries.md).
List<Map<String, Object?>> rowsToJson(List<Map<String, Object?>> rows, DateTime now) {
  final out = <Map<String, Object?>>[];
  for (final row in rows) {
    final occurredAt = row['occurred_at'] as String?;
    final dueAt = row['due_at'] as String?;
    final d = <String, Object?>{
      'type': row['type'] ?? 'record',
      'title': row['title'],
      'when': occurredAt ?? dueAt ?? row['date'] ?? row['created_at'],
    };
    final body = row['body'] as String?;
    if (body != null && body.isNotEmpty) d['detail'] = _clip(body);
    final notes = row['notes'] as String?;
    if (notes != null && notes.isNotEmpty) d['notes'] = _clip(notes);
    for (final attr in ['kind', 'domain', 'status']) {
      if (row[attr] != null) d[attr] = row[attr];
    }
    final status = row['status'] as String?;
    if (d['type'] == 'record' && status != null) d['section'] = sectionFor(status);
    final attributes = row['attributes'];
    if (attributes is String) {
      final decoded = jsonDecode(attributes);
      if (decoded is Map && decoded.isNotEmpty) d['attributes'] = decoded;
    }
    final due = dueAt != null ? DateTime.parse(dueAt) : null;
    d['overdue'] = status == 'open' && due != null && due.isBefore(now);
    d['due_label'] = dueLabel(due, now);
    out.add(d);
  }
  return out;
}
