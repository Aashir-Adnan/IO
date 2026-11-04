/// One chat turn, end to end — the phone's counterpart of the desktop
/// Orchestrator (io_assistant/orchestrator.py), restricted to the MVP: store,
/// query, unknown. The model decides what the user wants and phrases the
/// answer; everything in between (dates, entity identity, retrieval, gating)
/// is deterministic Dart (rules/llm-boundaries.md).
library;

import 'package:sqflite/sqflite.dart';
import 'anthropic_client.dart';
import 'db.dart' show newSyncId;
import 'extraction.dart';
import 'llm.dart';
import 'persist.dart';
import 'plan.dart';
import 'query.dart';
import 'resolver.dart';
import 'web.dart';

class TurnResult {
  /// "ack" | "answer" | "gate" | "unknown" | "error"
  final String kind;
  final String message;
  final List<int> recordIds;
  const TurnResult(this.kind, this.message, {this.recordIds = const []});
}

class _Pending {
  final ExtractionResult extraction;
  final int utteranceId;
  final String text;
  const _Pending(this.extraction, this.utteranceId, this.text);
}

const _empty = "I don't have anything on that yet.";
const _unknownReply = "I didn't catch that - please rephrase and try again.";
const _topN = 25;
final _affirm = RegExp(
    r'^\s*(yes|yeah|yep|yup|sure|ok|okay|confirm|do it|save it|go ahead)[.! ]*$',
    caseSensitive: false);

class Orchestrator {
  final Database db;
  final Llm llm;
  final DateTime Function() clock;
  final double confidenceGate;
  final WebClient? web; // the user's own desktop, optional (see web.dart)
  _Pending? _pending;

  Orchestrator(this.db, this.llm,
      {DateTime Function()? clock, this.confidenceGate = 0.6, this.web})
      : clock = clock ?? (() => DateTime.now().toUtc());

  Future<TurnResult> handle(String text, {String? context}) async {
    try {
      final pending = _pending;
      _pending = null; // anything but an explicit yes abandons the gate
      if (pending != null && _affirm.hasMatch(text)) {
        return await _replay(pending, context);
      }
      final now = clock();
      final webTurn = await _maybeWeb(text, now);
      if (webTurn != null) return webTurn;
      final plan = await llm.decide(text, now, context: context);
      final results = <TurnResult>[];
      for (final step in plan.steps) {
        results.add(await _dispatch(step, text, now, context));
      }
      return _merge(results);
    } on MissingApiKey {
      return const TurnResult('error', 'Add your Anthropic API key in Settings first.');
    } on AnthropicApiError catch (e) {
      return TurnResult('error', 'Anthropic is unavailable right now (HTTP ${e.statusCode}) — try again.');
    } on PlanParseError {
      return const TurnResult('error', "I couldn't understand the model's reply — try again.");
    } on PersistError catch (e) {
      return TurnResult('error', "I couldn't save that: ${e.message}");
    }
  }

  /// Memory first: the web is only for clearly non-personal news/fact
  /// questions or an explicit "search the web for…". Null = not a web turn.
  Future<TurnResult?> _maybeWeb(String text, DateTime now) async {
    final w = web;
    final intent = webIntent(text);
    if (w == null || intent == null) return null;
    if (!await w.isConfigured()) {
      return intent.explicit
          ? const TurnResult('error',
              'Web search runs through your desktop. Set your home server in Settings first.')
          : null;
    }
    final nowIso = now.toIso8601String();
    await db.insert('utterances', {
      'text': text, 'source': 'text', 'captured_at': nowIso,
      'resolved_intent': 'web', 'sync_id': newSyncId(), 'updated_at': nowIso,
    });
    try {
      return TurnResult('answer', (await w.answer(intent.query, intent.kind)).render());
    } on WebUnavailable catch (e) {
      return TurnResult('error', e.message);
    }
  }

  Future<TurnResult> _dispatch(Step step, String text, DateTime now, String? context) async {
    switch (step.kind) {
      case 'store':
        return _store(step, text, now, context);
      case 'query':
        return _query(step.question ?? text, text, now, context);
      default:
        return const TurnResult('unknown', _unknownReply);
    }
  }

  // --- store ---------------------------------------------------------------

  Future<TurnResult> _store(Step step, String text, DateTime now, String? context) async {
    final ext = step.extraction;
    if (ext == null) {
      return const TurnResult('unknown', "I couldn't make sense of that — could you rephrase?");
    }
    final res = await persistStore(db, EntityResolver(db),
        utteranceText: text, source: 'text', capturedAt: now, extraction: ext,
        now: now, confidenceGate: confidenceGate);
    if (res.gated) {
      _pending = _Pending(ext, res.utteranceId, text);
      return TurnResult('gate',
          "I'm not sure about this: ${res.gateReasons.join('; ')}. Say yes to save it anyway.");
    }
    return _ack(res, context);
  }

  Future<TurnResult> _replay(_Pending p, String? context) async {
    final now = clock();
    final res = await persistStore(db, EntityResolver(db),
        utteranceText: p.text, source: 'text', capturedAt: now, extraction: p.extraction,
        now: now, confidenceGate: confidenceGate, confirmed: true,
        existingUtteranceId: p.utteranceId);
    return _ack(res, context);
  }

  Future<TurnResult> _ack(PersistResult res, String? context) async {
    final facts = await _facts(res.recordIds);
    return TurnResult('ack', await llm.acknowledge(facts, context: context),
        recordIds: res.recordIds);
  }

  /// Plain-text summary of exactly what was written — the only input the
  /// acknowledge prompt gets (io_assistant/extract/acknowledge.py).
  Future<String> _facts(List<int> recordIds) async {
    const links = [
      ('with', 'record_people', 'person_id', 'people', 'canonical_name'),
      ('at', 'record_places', 'place_id', 'places', 'name'),
      ('item', 'record_items', 'item_id', 'items', 'name'),
      ('occasion', 'record_occasions', 'occasion_id', 'occasions', 'name'),
    ];
    final lines = <String>[];
    for (final rid in recordIds) {
      final rec = (await db.query('records', where: 'id = ?', whereArgs: [rid])).firstOrNull;
      if (rec == null) continue;
      final parts = ['${rec['kind']} "${rec['title']}"'];
      for (final (word, link, linkCol, table, nameCol) in links) {
        final names = (await db.rawQuery(
          'SELECT $table.$nameCol AS n FROM $table JOIN $link ON $link.$linkCol = $table.id '
          'WHERE $link.record_id = ?', [rid])).map((r) => r['n'] as String);
        if (names.isNotEmpty) parts.add('$word ${names.join(', ')}');
      }
      final when = (rec['occurred_at'] ?? rec['due_at']) as String?;
      if (when != null) parts.add('when ${when.substring(0, 10)}');
      if (rec['status'] != null) parts.add('status ${rec['status']}');
      lines.add(parts.join('; '));
    }
    return lines.isEmpty ? 'nothing recorded' : lines.join('\n');
  }

  // --- query ---------------------------------------------------------------

  Future<TurnResult> _query(String question, String text, DateTime now, String? context) async {
    final nowIso = now.toIso8601String();
    await db.insert('utterances', {
      'text': text, 'source': 'text', 'captured_at': nowIso,
      'resolved_intent': 'query', 'sync_id': newSyncId(), 'updated_at': nowIso,
    });
    final qp = groundPlan(await llm.plan(question, now, context: context), now);
    final resolver = EntityResolver(db);

    final byId = <int, Map<String, Object?>>{};
    int? count;
    for (final sq in qp.subqueries) {
      final ids = await _resolveEntities(resolver, sq.entities);
      if (sq.aggregation == 'count') {
        count = await retrieveCount(db, sq, ids, now);
      } else {
        for (final row in await retrieve(db, sq, ids, now)) {
          byId.putIfAbsent(row['id'] as int, () => row);
        }
      }
    }
    final rows = byId.values.take(_topN).toList();

    if (count == null && rows.isEmpty) {
      final hint = (await web?.isConfigured() ?? false)
          ? '$_empty If you meant the wider world, say "search the web for …".'
          : _empty;
      return TurnResult('answer', hint);
    }
    final q = count == null ? question : '$question (there are $count matching items)';
    final text0 = await llm.phrase(q, rowsToJson(rows, now), qp.answerShape, context: context);
    return TurnResult('answer', text0,
        recordIds: [for (final r in rows) r['id'] as int]);
  }

  /// Names -> matched entity ids by type. Read-only: unmatched names add
  /// nothing (io_assistant/query/entities.py).
  Future<Map<String, List<int>>> _resolveEntities(EntityResolver r, List<String> names) async {
    final out = <String, List<int>>{'person': [], 'place': [], 'item': [], 'occasion': []};
    for (final name in names) {
      for (final etype in ['person', 'place', 'item']) {
        final id = await r.lookup(etype, name);
        if (id != null && !out[etype]!.contains(id)) out[etype]!.add(id);
      }
      final occ = await db.query('occasions',
          columns: ['id'], where: 'lower(name) = ?', whereArgs: [name.toLowerCase()], limit: 1);
      if (occ.isNotEmpty && !out['occasion']!.contains(occ.first['id'])) {
        out['occasion']!.add(occ.first['id'] as int);
      }
    }
    return out;
  }

  // --- merge ---------------------------------------------------------------

  /// A gate wins (the user must answer it first); otherwise concatenate.
  TurnResult _merge(List<TurnResult> results) {
    if (results.length == 1) return results.single;
    for (final r in results) {
      if (r.kind == 'gate') return r;
    }
    final real = results.where((r) => r.kind != 'unknown').toList();
    if (real.isEmpty) return results.first;
    final kinds = real.map((r) => r.kind).toSet();
    return TurnResult(
      kinds.contains('answer') ? 'answer' : 'ack',
      real.map((r) => r.message).join('\n\n'),
      recordIds: [for (final r in real) ...r.recordIds],
    );
  }
}
