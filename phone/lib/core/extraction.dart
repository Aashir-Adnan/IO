/// What one Anthropic "store" call returns — a port of the shapes in
/// io_assistant/models_domain.py that persist.dart needs (extraction only;
/// the decide/plan step shapes come with the chat-loop task).
library;

class ExtractedPerson {
  final String name;
  final List<String> aliases;
  final double confidence;
  const ExtractedPerson({required this.name, this.aliases = const [], required this.confidence});
}

class ExtractedPlace {
  final String name;
  final List<String> aliases;
  final double confidence;
  const ExtractedPlace({required this.name, this.aliases = const [], required this.confidence});
}

class ExtractedItem {
  final String name;
  final List<String> aliases;
  final double confidence;
  const ExtractedItem({required this.name, this.aliases = const [], required this.confidence});
}

class ExtractedOccasion {
  final String name;
  final String? datePhrase;
  final double confidence;
  const ExtractedOccasion({required this.name, this.datePhrase, required this.confidence});
}

class ExtractedRecord {
  final String kind;
  final String? domain;
  final String title;
  final String? body;
  final String? whenPhrase;
  final String? duePhrase;
  final String? recurrencePhrase;
  final String? status; // "open" | "done" | "dropped" | null
  final String? assignedBy;
  final List<String> people;
  final List<String> places;
  final List<String> items;
  final List<String> occasions;
  final Map<String, Object?> attributes;
  final double confidence;

  const ExtractedRecord({
    required this.kind, this.domain, required this.title, this.body,
    this.whenPhrase, this.duePhrase, this.recurrencePhrase, this.status,
    this.assignedBy, this.people = const [], this.places = const [],
    this.items = const [], this.occasions = const [],
    this.attributes = const {}, required this.confidence,
  });

  ExtractedRecord copyWith({double? confidence}) => ExtractedRecord(
        kind: kind, domain: domain, title: title, body: body,
        whenPhrase: whenPhrase, duePhrase: duePhrase, recurrencePhrase: recurrencePhrase,
        status: status, assignedBy: assignedBy, people: people, places: places,
        items: items, occasions: occasions, attributes: attributes,
        confidence: confidence ?? this.confidence,
      );
}

class ExtractionResult {
  final List<ExtractedPerson> people;
  final List<ExtractedPlace> places;
  final List<ExtractedItem> items;
  final List<ExtractedOccasion> occasions;
  final List<ExtractedRecord> records;
  ExtractionResult({
    this.people = const [], this.places = const [], this.items = const [],
    this.occasions = const [], this.records = const [],
  });
}

const _kindAliases = {
  'todo': 'task', 'to_do': 'task', 'task_reminder': 'task',
  'reminder': 'task', 'reminders': 'task',
  'chores': 'chore',
};

String normalizeKind(String raw) {
  var s = raw.toLowerCase();
  s = s.replaceAll(RegExp(r'[ \-]'), '_');
  s = s.replaceAll(RegExp(r'[^a-z0-9_]'), '');
  s = s.replaceAll(RegExp(r'_+'), '_');
  s = _trim(s, '_');
  if (s.length > 48) s = s.substring(0, 48);
  s = _trim(s, '_');
  s = _kindAliases[s] ?? s;
  return s.isEmpty ? 'note' : s;
}

const _domainValues = {'social', 'job', 'home', 'health', 'finance', 'learning', 'errand', 'other'};

String? normalizeDomain(String? raw) {
  if (raw == null || raw.trim().isEmpty) return null;
  final s = raw.toLowerCase().trim();
  if (s.isEmpty) return null;
  return _domainValues.contains(s) ? s : 'other';
}

String _trim(String s, String char) {
  var start = 0, end = s.length;
  while (start < end && s[start] == char) {
    start++;
  }
  while (end > start && s[end - 1] == char) {
    end--;
  }
  return s.substring(start, end);
}
