/// Entity resolution, lexical only — a port of io_assistant/resolve/
/// resolver.py's exact + fuzzy branches. No vector branch at all: the phone
/// has no embedder (see the phone-app design spec §"No on-device embedder"),
/// so this is not a fallback mode, it *is* the resolver.
library;

import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'db.dart';

class ResolveOutcome {
  final int? entityId;
  final bool isNew;
  final int? candidateId;
  const ResolveOutcome({this.entityId, this.isNew = false, this.candidateId});
}

const _tables = {
  'person': ('people', 'canonical_name'),
  'place': ('places', 'name'),
  'item': ('items', 'name'),
};

class EntityResolver {
  final Database db;
  final int fuzzyThreshold;
  EntityResolver(this.db, {this.fuzzyThreshold = 92});

  (String, String) _spec(String entityType) {
    final t = _tables[entityType];
    if (t == null) throw ArgumentError('unknown entity type: $entityType');
    return t;
  }

  /// A bounded candidate set — exact hits, plus a LIKE-based prefilter capped
  /// at 50 rows, never a full-table scan. Mirrors resolver.py's SQL-narrowed
  /// `_candidate_rows` (there backed by pg_trgm; SQLite has no trigram index,
  /// so this substitutes a substring prefilter on each significant word).
  Future<List<Map<String, Object?>>> candidateRows(
      String entityType, String name, List<String> aliases) async {
    final (table, nameCol) = _spec(entityType);
    final needles = [name, ...aliases];
    final lowered = needles.map((n) => n.toLowerCase()).toList();

    // Exact: the name column, OR a needle sitting in the aliases JSON array
    // (SQLite's LIKE is ASCII case-insensitive, so lower() + LIKE on the
    // quoted JSON string is a cheap stand-in for Postgres's array overlap).
    final exactPlaceholders = List.filled(lowered.length, '?').join(',');
    final aliasHitClauses = lowered.map((_) => "lower(aliases) LIKE '%\"' || ? || '\"%'").join(' OR ');
    final exact = await db.rawQuery(
      'SELECT id, $nameCol AS name, aliases FROM $table '
      'WHERE lower($nameCol) IN ($exactPlaceholders) OR ($aliasHitClauses)',
      [...lowered, ...lowered],
    );

    // Fuzzy prefilter: any significant word of the incoming name appearing in
    // either the name column or the aliases text — mirrors Python's
    // similarity() search over both name and the concatenated alias text.
    final words = name
        .toLowerCase()
        .split(RegExp(r'\s+'))
        .where((w) => w.length >= 3)
        .toList();
    final likeClauses = words
        .map((_) => '(lower($nameCol) LIKE ? OR lower(aliases) LIKE ?)')
        .join(' OR ');
    final likeArgs = words.expand((w) => ['%$w%', '%$w%']).toList();
    final like = likeClauses.isEmpty
        ? <Map<String, Object?>>[]
        : await db.rawQuery(
            'SELECT id, $nameCol AS name, aliases FROM $table WHERE $likeClauses LIMIT 50',
            likeArgs,
          );

    final byId = <int, Map<String, Object?>>{};
    for (final r in [...exact, ...like]) {
      byId[r['id'] as int] = r;
    }
    return byId.values.toList();
  }

  List<String> _aliasesOf(Map<String, Object?> row) =>
      (jsonDecode(row['aliases'] as String) as List).cast<String>();

  Future<ResolveOutcome> resolve(
      String entityType, String name, List<String> aliases) async {
    final rows = await candidateRows(entityType, name, aliases);
    final lowered = name.toLowerCase();
    final incoming = aliases.map((a) => a.toLowerCase()).toSet();

    // 1. exact: incoming name/alias vs stored name/alias, case-insensitive
    for (final row in rows) {
      final cname = row['name'] as String;
      final stored = {cname.toLowerCase(), ..._aliasesOf(row).map((a) => a.toLowerCase())};
      if (stored.contains(lowered) ||
          incoming.contains(cname.toLowerCase()) ||
          stored.intersection(incoming).isNotEmpty) {
        return ResolveOutcome(entityId: row['id'] as int);
      }
    }

    // 2. fuzzy: best token-set ratio over the name AND every stored alias
    int? bestId;
    var bestScore = -1.0;
    for (final row in rows) {
      final cname = row['name'] as String;
      final candidates = [cname, ..._aliasesOf(row)];
      final score = candidates.map((c) => tokenSetRatio(name, c)).reduce((a, b) => a > b ? a : b);
      if (score > bestScore) {
        bestScore = score;
        bestId = row['id'] as int;
      }
    }
    if (bestId != null && bestScore >= fuzzyThreshold) {
      return ResolveOutcome(entityId: bestId);
    }

    // 3. none — no vector branch (the phone has no embedder)
    return const ResolveOutcome(isNew: true);
  }

  /// Read-only resolve for queries: exact -> fuzzy, best id or null. No
  /// create, no gate.
  Future<int?> lookup(String entityType, String name) async {
    final rows = await candidateRows(entityType, name, []);
    final lowered = name.toLowerCase();
    for (final row in rows) {
      final cname = row['name'] as String;
      final stored = {cname.toLowerCase(), ..._aliasesOf(row).map((a) => a.toLowerCase())};
      if (stored.contains(lowered)) return row['id'] as int;
    }
    int? bestId;
    var bestScore = -1.0;
    for (final row in rows) {
      final cname = row['name'] as String;
      final candidates = [cname, ..._aliasesOf(row)];
      final score = candidates.map((c) => tokenSetRatio(name, c)).reduce((a, b) => a > b ? a : b);
      if (score > bestScore) {
        bestScore = score;
        bestId = row['id'] as int;
      }
    }
    if (bestId != null && bestScore >= fuzzyThreshold) return bestId;
    return null;
  }

  Future<int> create(String entityType, String name, List<String> aliases) async {
    final (table, nameCol) = _spec(entityType);
    final now = DateTime.now().toUtc().toIso8601String();
    return db.insert(table, {
      nameCol: name,
      'aliases': jsonEncode(aliases),
      'sync_id': newSyncId(),
      'created_at': now,
      'updated_at': now,
    });
  }
}

// --- fuzzy scoring: token_set_ratio, the same public algorithm rapidfuzz's
// fuzz.token_set_ratio implements (tokenize, intersect, compare the three
// combinations, take the best). ratio() itself is LCS-based, matching
// rapidfuzz's default Indel-distance ratio: 200 * lcs / (lenA + lenB).

double ratio(String a, String b) {
  if (a.isEmpty && b.isEmpty) return 100;
  final lcs = _lcsLength(a, b);
  return 200.0 * lcs / (a.length + b.length);
}

int _lcsLength(String a, String b) {
  final m = a.length, n = b.length;
  var prev = List<int>.filled(n + 1, 0);
  for (var i = 1; i <= m; i++) {
    final cur = List<int>.filled(n + 1, 0);
    for (var j = 1; j <= n; j++) {
      cur[j] = a[i - 1] == b[j - 1] ? prev[j - 1] + 1 : (prev[j] > cur[j - 1] ? prev[j] : cur[j - 1]);
    }
    prev = cur;
  }
  return prev[n];
}

List<String> _tokens(String s) => (s.toLowerCase().split(RegExp(r'\s+'))..removeWhere((t) => t.isEmpty))..sort();

double tokenSetRatio(String a, String b) {
  final ta = _tokens(a).toSet();
  final tb = _tokens(b).toSet();
  final intersection = ta.intersection(tb).toList()..sort();
  final onlyA = ta.difference(tb).toList()..sort();
  final onlyB = tb.difference(ta).toList()..sort();

  final t0 = intersection.join(' ');
  final t1 = [t0, onlyA.join(' ')].where((s) => s.isNotEmpty).join(' ');
  final t2 = [t0, onlyB.join(' ')].where((s) => s.isNotEmpty).join(' ');

  final scores = [ratio(t0, t1), ratio(t0, t2), ratio(t1, t2)];
  return scores.reduce((x, y) => x > y ? x : y);
}
