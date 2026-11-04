/// The store pipeline — a port of io_assistant/persist/writer.py. No
/// embeddings anywhere (the phone has no embedder; see resolver.dart).
///
/// ponytail: the collections registry (io_assistant/collections/registry.py —
/// ad-hoc list descriptors like "movies to watch") is not ported. A bare
/// task/chore still defaults to status="open" (the _STATUS_KINDS rule below);
/// what's missing is a *non-task* kind (e.g. "watchlist") auto-defaulting to
/// open via a learned collection. Upgrade: port registry.dart alongside this
/// once the chat loop needs ad-hoc checkable lists.
library;

import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'dates.dart';
import 'db.dart' show newSyncId;
import 'extraction.dart';
import 'resolver.dart';

const _statusKinds = {'task', 'chore'};

class PersistError implements Exception {
  final String message;
  PersistError(this.message);
  @override
  String toString() => message;
}

class PersistResult {
  final int utteranceId;
  final List<int> recordIds;
  final List<(String, String)> newEntities;
  final bool gated;
  final List<String> gateReasons;
  const PersistResult({
    required this.utteranceId, this.recordIds = const [],
    this.newEntities = const [], this.gated = false, this.gateReasons = const [],
  });
}

bool _isSomeday(ExtractedRecord rec) =>
    isSomedayPhrase(rec.whenPhrase) || isSomedayPhrase(rec.duePhrase);

Future<PersistResult> persistStore(
  Database db,
  EntityResolver resolver, {
  required String utteranceText,
  required String source,
  required DateTime capturedAt,
  required ExtractionResult extraction,
  required DateTime now,
  required double confidenceGate,
  bool confirmed = false,
  int? existingUtteranceId,
}) async {
  // 1. Utterance row — always kept, even if the write pass below is gated.
  int utteranceId;
  if (existingUtteranceId != null) {
    final rows = await db.query('utterances', where: 'id = ?', whereArgs: [existingUtteranceId]);
    if (rows.isEmpty) {
      throw PersistError('utterance $existingUtteranceId no longer exists');
    }
    utteranceId = existingUtteranceId;
  } else {
    utteranceId = await db.insert('utterances', {
      'text': utteranceText, 'source': source,
      'captured_at': capturedAt.toIso8601String(),
      'resolved_intent': 'store',
      'sync_id': newSyncId(),
      'updated_at': now.toIso8601String(),
    });
  }

  // 2. Resolve pass (read-only), deduped by (etype, lowered name) so a name
  //    repeated inside one extraction resolves — and later creates — once.
  final outcomes = <String, ResolveOutcome>{};
  final entityNames = <String, String>{};
  final entityAliases = <String, List<String>>{};
  Future<void> collect(String etype, String name, List<String> aliases) async {
    final key = '$etype:${name.toLowerCase()}';
    if (outcomes.containsKey(key)) {
      final list = entityAliases[key]!;
      for (final a in aliases) {
        if (!list.contains(a)) list.add(a);
      }
      return;
    }
    entityNames[key] = name;
    entityAliases[key] = List.of(aliases);
    outcomes[key] = await resolver.resolve(etype, name, aliases);
  }
  for (final p in extraction.people) {
    await collect('person', p.name, p.aliases);
  }
  for (final p in extraction.places) {
    await collect('place', p.name, p.aliases);
  }
  for (final it in extraction.items) {
    await collect('item', it.name, it.aliases);
  }

  // 3. Gate check. (No ambiguity branch: the phone resolver never returns
  //    one — see resolver.dart.)
  final gateReasons = <String>[];
  for (final rec in extraction.records) {
    if (rec.confidence < confidenceGate) {
      gateReasons.add("low confidence (${rec.confidence}) on '${rec.title}'");
    }
    for (final phrase in [rec.whenPhrase, rec.duePhrase]) {
      if (phrase != null && phrase.isNotEmpty && !ground(phrase, now).ok) {
        gateReasons.add("couldn't ground the date '$phrase'");
      }
    }
    if (rec.recurrencePhrase != null &&
        rec.recurrencePhrase!.isNotEmpty &&
        toRrule(rec.recurrencePhrase) == null) {
      gateReasons.add("couldn't read the repeat rule '${rec.recurrencePhrase}'");
    }
  }
  for (final occ in extraction.occasions) {
    if (occ.datePhrase != null && occ.datePhrase!.isNotEmpty && !ground(occ.datePhrase, now).ok) {
      gateReasons.add("couldn't ground the date '${occ.datePhrase}'");
    }
  }

  if (gateReasons.isNotEmpty && !confirmed) {
    return PersistResult(utteranceId: utteranceId, gated: true, gateReasons: gateReasons);
  }

  // 4. Write pass — atomic: a failure rolls back only these rows, leaving the
  //    already-committed utterance row intact.
  try {
    late PersistResult result;
    await db.transaction((txn) async {
      final outerDb = resolver.db;
      resolver.db = txn;
      try {
        result = await _write(txn, resolver, extraction, now, utteranceId, outcomes, entityNames, entityAliases);
      } finally {
        resolver.db = outerDb;
      }
    });
    return result;
  } on PersistError {
    rethrow;
  } catch (e) {
    throw PersistError(e.toString());
  }
}

Future<PersistResult> _write(
  DatabaseExecutor txn,
  EntityResolver resolver,
  ExtractionResult extraction,
  DateTime now,
  int utteranceId,
  Map<String, ResolveOutcome> outcomes,
  Map<String, String> entityNames,
  Map<String, List<String>> entityAliases,
) async {
  final newEntities = <(String, String)>[];
  final entityIds = <String, int>{};

  for (final key in outcomes.keys) {
    final etype = key.split(':').first;
    final outcome = outcomes[key]!;
    final name = entityNames[key]!;
    if (outcome.entityId != null) {
      entityIds[key] = outcome.entityId!;
    } else {
      entityIds[key] = await resolver.create(etype, name, entityAliases[key]!);
      newEntities.add((etype, name));
    }
  }

  Future<int?> ensure(String etype, String rawName) async {
    if (rawName.isEmpty) return null;
    final key = '$etype:${rawName.toLowerCase()}';
    if (entityIds.containsKey(key)) return entityIds[key];
    final outcome = await resolver.resolve(etype, rawName, const []);
    if (outcome.entityId != null) {
      entityIds[key] = outcome.entityId!;
    } else {
      entityIds[key] = await resolver.create(etype, rawName, const []);
      newEntities.add((etype, rawName));
    }
    return entityIds[key];
  }

  // Occasions: dedupe by case-insensitive name.
  final occasionIds = <String, int>{};
  for (final occ in extraction.occasions) {
    final existing = await txn.query('occasions',
        where: 'lower(name) = ?', whereArgs: [occ.name.toLowerCase()]);
    if (existing.isNotEmpty) {
      occasionIds[occ.name.toLowerCase()] = existing.first['id'] as int;
      continue;
    }
    final dr = ground(occ.datePhrase, now);
    final nowIso = now.toIso8601String();
    final id = await txn.insert('occasions', {
      'name': occ.name,
      'date': dr.value?.toIso8601String().substring(0, 10),
      'sync_id': newSyncId(), 'created_at': nowIso, 'updated_at': nowIso,
    });
    occasionIds[occ.name.toLowerCase()] = id;
  }

  final recordIds = <int>[];
  for (final rec in extraction.records) {
    final kind = normalizeKind(rec.kind);
    final checkable = _statusKinds.contains(kind); // registry-based checkable kinds not ported
    final status = (checkable && rec.status == null) ? 'open' : rec.status;

    int? assignedById;
    if (rec.assignedBy != null && rec.assignedBy!.isNotEmpty) {
      assignedById = await ensure('person', rec.assignedBy!);
    }

    var occurred = ground(rec.whenPhrase, now).value;
    var due = ground(rec.duePhrase, now).value;
    if (_statusKinds.contains(kind) &&
        due == null &&
        occurred == null &&
        (rec.recurrencePhrase == null || rec.recurrencePhrase!.isEmpty) &&
        !_isSomeday(rec)) {
      due = startOfDay(now);
    }

    final nowIso = now.toIso8601String();
    final recordId = await txn.insert('records', {
      'kind': kind,
      'domain': normalizeDomain(rec.domain),
      'title': rec.title,
      'body': rec.body,
      'occurred_at': occurred?.toIso8601String(),
      'due_at': due?.toIso8601String(),
      'recurrence_rule': toRrule(rec.recurrencePhrase),
      'status': status,
      'assigned_by_person_id': assignedById,
      'attributes': jsonEncode(rec.attributes),
      'source_utterance_id': utteranceId,
      'sync_id': newSyncId(), 'created_at': nowIso, 'updated_at': nowIso,
    });
    recordIds.add(recordId);

    for (final pname in rec.people) {
      final pid = await ensure('person', pname);
      if (pid != null) await txn.insert('record_people', {'record_id': recordId, 'person_id': pid});
    }
    for (final plname in rec.places) {
      final plid = await ensure('place', plname);
      if (plid != null) await txn.insert('record_places', {'record_id': recordId, 'place_id': plid});
    }
    for (final iname in rec.items) {
      final iid = await ensure('item', iname);
      if (iid != null) await txn.insert('record_items', {'record_id': recordId, 'item_id': iid});
    }
    for (final oname in rec.occasions) {
      final oid = occasionIds[oname.toLowerCase()];
      if (oid != null) {
        await txn.insert('record_occasions', {'record_id': recordId, 'occasion_id': oid});
      }
    }
  }

  return PersistResult(utteranceId: utteranceId, recordIds: recordIds, newEntities: newEntities);
}
