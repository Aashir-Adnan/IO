/// Turning the model's JSON into validated, deterministic structures — ports
/// of io_assistant/decide/parse.py and io_assistant/query/plan.py:ground_plan.
/// Tolerant by design: a partly-good response still yields a usable plan; a
/// completely unusable one raises PlanParseError.
library;

import 'dart:convert';
import 'dates.dart';
import 'extraction.dart';
import 'query.dart';

class PlanParseError implements Exception {
  final String message;
  PlanParseError(this.message);
  @override
  String toString() => 'PlanParseError: $message';
}

class Step {
  final String kind; // "store" | "query" | "unknown"
  final ExtractionResult? extraction;
  final String? question;
  const Step(this.kind, {this.extraction, this.question});
}

class Plan {
  final List<Step> steps;
  const Plan(this.steps);
}

String stripFences(String raw) {
  var s = raw.trim();
  for (final p in ['```json', '```']) {
    if (s.startsWith(p)) {
      s = s.substring(p.length);
      break;
    }
  }
  if (s.endsWith('```')) s = s.substring(0, s.length - 3);
  s = s.trim();
  final a = s.indexOf('{'), b = s.lastIndexOf('}');
  if (a >= 0 && b > a) s = s.substring(a, b + 1);
  return s;
}

Object? decodeJson(String raw, String what) {
  try {
    return jsonDecode(stripFences(raw));
  } catch (e) {
    throw PlanParseError('$what: not JSON ($e)');
  }
}

Plan parsePlan(String raw) {
  final data = decodeJson(raw, 'decide');
  if (data is! Map) throw PlanParseError('decide: top level is not an object');
  final rawSteps = data['steps'];
  if (rawSteps is! List || rawSteps.isEmpty) throw PlanParseError('decide: no steps');

  final steps = <Step>[];
  for (final rs in rawSteps) {
    if (rs is! Map) continue;
    final kind = '${rs['kind'] ?? ''}'.toLowerCase();
    switch (kind) {
      case 'store':
        steps.add(Step('store', extraction: parseExtraction(rs['extraction'])));
      case 'query':
        final q = rs['question'];
        steps.add(Step('query', question: q == null || '$q'.isEmpty ? null : '$q'));
      case 'file':
      case 'action':
      case 'unknown':
        // the phone has no files and no capabilities (spec: MVP scope)
        steps.add(const Step('unknown'));
    }
  }
  if (steps.isEmpty) throw PlanParseError('decide: every step was unusable');
  return Plan(steps);
}

// --- extraction ------------------------------------------------------------

String _req(Map m, String k) {
  final v = m[k];
  if (v is! String) throw FormatException('$k missing');
  return v;
}

String? _opt(Map m, String k) {
  final v = m[k];
  return v is String ? v : null;
}

double _conf(Map m) {
  final v = m['confidence'];
  if (v is! num) throw const FormatException('confidence missing');
  return v.toDouble();
}

List<String> _strs(Object? v) =>
    v is List ? v.whereType<String>().toList() : const <String>[];

List<T> _maps<T>(Object? v, T Function(Map) f) =>
    v is List ? v.whereType<Map>().map(f).toList() : <T>[];

ExtractionResult? parseExtraction(Object? raw) {
  if (raw is! Map) return null;
  try {
    return ExtractionResult(
      people: _maps(raw['people'], (m) => ExtractedPerson(
          name: _req(m, 'name'), aliases: _strs(m['aliases']), confidence: _conf(m))),
      places: _maps(raw['places'], (m) => ExtractedPlace(
          name: _req(m, 'name'), aliases: _strs(m['aliases']), confidence: _conf(m))),
      items: _maps(raw['items'], (m) => ExtractedItem(
          name: _req(m, 'name'), aliases: _strs(m['aliases']), confidence: _conf(m))),
      occasions: _maps(raw['occasions'], (m) => ExtractedOccasion(
          name: _req(m, 'name'), datePhrase: _opt(m, 'date_phrase'), confidence: _conf(m))),
      records: _maps(raw['records'], (m) {
        final status = _opt(m, 'status');
        if (status != null && !{'open', 'done', 'dropped'}.contains(status)) {
          throw const FormatException('bad status');
        }
        final attrs = m['attributes'];
        return ExtractedRecord(
          kind: _req(m, 'kind'), domain: _opt(m, 'domain'), title: _req(m, 'title'),
          body: _opt(m, 'body'), whenPhrase: _opt(m, 'when_phrase'),
          duePhrase: _opt(m, 'due_phrase'), recurrencePhrase: _opt(m, 'recurrence_phrase'),
          status: status, assignedBy: _opt(m, 'assigned_by'),
          people: _strs(m['people']), places: _strs(m['places']),
          items: _strs(m['items']), occasions: _strs(m['occasions']),
          attributes: attrs is Map ? attrs.cast<String, Object?>() : const {},
          confidence: _conf(m),
        );
      }),
    );
  } catch (_) {
    return null; // pydantic would reject the whole extraction too
  }
}

// --- query plan --------------------------------------------------------------

class QueryPlan {
  final List<SubQuery> subqueries;
  final String answerShape; // "text" | "markdown" | "diagram"
  const QueryPlan(this.subqueries, this.answerShape);
}

const _statuses = {'open', 'done', 'dropped'};
const _targets = {'record', 'person', 'place', 'occasion'};
const _shapes = {'text', 'markdown', 'diagram'};

List<String> _dedupe(Iterable<String> xs) => xs.toSet().toList();

DateTime? _groundBound(Object? v, DateTime now) {
  if (v == null || v == '') return null;
  if (v is DateTime) return v;
  final r = ground('$v', now);
  return r.ok ? r.value : null;
}

TimeWindow? _groundWindow(Object? raw, DateTime now) {
  if (raw is! Map || raw.isEmpty) return null;
  final start = _groundBound(raw['start'], now);
  var end = _groundBound(raw['end'], now);
  if (start == null && end == null) {
    final text = ['start', 'end'].map((k) => '${raw[k] ?? ''}').join(' ').toLowerCase();
    if (text.contains('past') || text.contains('last') || text.contains('ago')) {
      end = now;
    } else {
      return null;
    }
  }
  return TimeWindow(start: start, end: end);
}

SubQuery _cleanSubquery(Map raw, DateTime now) {
  final kinds = _strs(raw['kind_filter']).map(normalizeKind);
  // For a *filter*, an unrecognized domain must be dropped, not coerced to
  // "other" (that would silently broaden the query to every other-domain row).
  final domains = <String>[];
  for (final x in _strs(raw['domain_filter'])) {
    final d = normalizeDomain(x);
    if (d != null && (d != 'other' || x.trim().toLowerCase() == 'other')) domains.add(d);
  }
  final statuses = _strs(raw['status_filter']).where(_statuses.contains);
  final tt = raw['target_type'];
  final agg = raw['aggregation'];
  final kindList = _dedupe(kinds), domainList = _dedupe(domains), statusList = _dedupe(statuses);
  return SubQuery(
    targetType: _targets.contains(tt) ? tt as String : 'record',
    kindFilter: kindList.isEmpty ? null : kindList,
    domainFilter: domainList.isEmpty ? null : domainList,
    entities: _strs(raw['entities']).where((e) => e.trim().isNotEmpty).toList(),
    timeWindow: _groundWindow(raw['time_window'], now),
    statusFilter: statusList.isEmpty ? null : statusList,
    aggregation: agg == 'count' ? 'count' : 'list', // "latest" degrades to list
  );
}

QueryPlan groundPlan(Object? raw, DateTime now) {
  if (raw is! Map) throw PlanParseError('plan must be a JSON object');
  final subsRaw = raw['subqueries'];
  final subs = subsRaw is List
      ? subsRaw.whereType<Map>().map((s) => _cleanSubquery(s, now)).toList()
      : <SubQuery>[];
  final shape = raw['answer_shape'];
  return QueryPlan(
    subs.isEmpty ? [const SubQuery()] : subs,
    _shapes.contains(shape) ? shape as String : 'text',
  );
}
