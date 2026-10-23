/// Pending tasks and completion — ports of io_assistant/widgets/tasks.py
/// (pending_tasks) and tasks/complete.py (set_record_status). "Today" is the
/// UTC date, like the rest of IO.
library;

import 'package:sqflite/sqflite.dart';
import 'query.dart' show dueLabel;

String _group(DateTime? due, DateTime now) {
  if (due == null) return 'none';
  final d = DateTime.utc(due.year, due.month, due.day);
  final n = DateTime.utc(now.year, now.month, now.day);
  // by date: a bare task due 00:00 today is "today", not overdue
  if (d.isBefore(n)) return 'overdue';
  return d == n ? 'today' : 'upcoming';
}

/// Open tasks/chores: overdue, today, upcoming, then undated.
Future<List<Map<String, Object?>>> pendingTasks(Database db, DateTime now, {int limit = 50}) async {
  final rows = await db.rawQuery(
    "SELECT * FROM records WHERE kind IN ('task','chore') AND status = 'open' "
    'ORDER BY due_at IS NULL, due_at ASC, created_at ASC LIMIT ?',
    [limit],
  );
  return [
    for (final r in rows)
      () {
        final due = r['due_at'] == null ? null : DateTime.parse(r['due_at'] as String);
        final label = dueLabel(due, now);
        return <String, Object?>{
          'id': r['id'], 'title': r['title'], 'kind': r['kind'],
          'due_at': r['due_at'], 'group': _group(due, now),
          'due_label': label == null ? null : label[0].toUpperCase() + label.substring(1),
        };
      }(),
  ];
}

/// The one place a task's status changes. `done` stamps completed_at (once);
/// `open` clears it. updated_at moves so the row is dirty for memory sync.
Future<void> _setStatus(Database db, int id, String status, DateTime now) async {
  final iso = now.toIso8601String();
  await db.rawUpdate(
    status == 'done'
        ? "UPDATE records SET status = 'done', completed_at = COALESCE(completed_at, ?), updated_at = ? WHERE id = ?"
        : "UPDATE records SET status = 'open', completed_at = NULL, updated_at = ? WHERE id = ?",
    status == 'done' ? [iso, iso, id] : [iso, id],
  );
}

Future<void> completeTask(Database db, int id, DateTime now) => _setStatus(db, id, 'done', now);
Future<void> reopenTask(Database db, int id, DateTime now) => _setStatus(db, id, 'open', now);
