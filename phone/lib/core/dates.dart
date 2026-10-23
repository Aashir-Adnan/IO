/// Deterministic resolution of relative time phrases — a line-by-line port of
/// io_assistant/resolve/dates.py. Pure Dart, no model calls (rules/llm-
/// boundaries.md: the model never does date arithmetic).
library;

class DateResult {
  final DateTime? value;
  final bool ok;
  const DateResult(this.value, this.ok);
}

const Map<String, int> _weekdays = {
  'monday': 1, 'mon': 1,
  'tuesday': 2, 'tue': 2, 'tues': 2,
  'wednesday': 3, 'wed': 3,
  'thursday': 4, 'thu': 4, 'thur': 4, 'thurs': 4,
  'friday': 5, 'fri': 5,
  'saturday': 6, 'sat': 6,
  'sunday': 7, 'sun': 7,
};
// DateTime.weekday is 1=Monday..7=Sunday, matching this table already.

final _somedayRe = RegExp(
    r'\b(some\s?day|eventually|some\s?point|no rush|no hurry|whenever|'
    r'at some point|down the line|in the future)\b',
    caseSensitive: false);

bool isSomedayPhrase(String? text) =>
    text != null && _somedayRe.hasMatch(text);

DateTime startOfDay(DateTime d) => DateTime.utc(d.year, d.month, d.day);

final _weekdayToken = '\\b(?:${_weekdays.keys.join('|')})\\b';
final RegExp _dateish = RegExp(
    r'\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|' + _weekdayToken,
    caseSensitive: false);

const Map<int, String> _rruleWeekdayCode = {
  1: 'MO', 2: 'TU', 3: 'WE', 4: 'TH', 5: 'FR', 6: 'SA', 7: 'SU',
};

String _normalize(String phrase) {
  var text = phrase.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');
  if (text.startsWith('on ')) text = text.substring(3).trim();
  if (text.startsWith('for ')) text = text.substring(4).trim();
  return text;
}

const Map<String, String> _units = {
  'day': 'days', 'days': 'days',
  'week': 'weeks', 'weeks': 'weeks',
  'month': 'months', 'months': 'months',
  'year': 'years', 'years': 'years',
};

DateTime _atTime(DateTime base, int hour, [int minute = 0]) =>
    DateTime.utc(base.year, base.month, base.day, hour, minute);

const _dayHour = 12;
DateTime _noon(DateTime d) => _atTime(d, _dayHour);

DateTime _addMonths(DateTime d, int months) {
  final total = d.month - 1 + months;
  // Dart's `%` on int is already non-negative for a positive divisor (unlike
  // `~/`, which truncates toward zero) — this is the floor-division split.
  final r = total % 12;
  final yearOffset = (total - r) ~/ 12;
  final year = d.year + yearOffset;
  final month = r + 1;
  final lastDay = DateTime.utc(year, month + 1, 0).day;
  return DateTime.utc(year, month, d.day > lastDay ? lastDay : d.day,
      d.hour, d.minute, d.second);
}

DateTime _lastWeekday(DateTime now, int target) {
  var delta = (now.weekday - target) % 7;
  if (delta == 0) delta = 7;
  return now.subtract(Duration(days: delta));
}

DateTime _thisWeekday(DateTime now, int target) {
  final weekStart = now.subtract(Duration(days: now.weekday - 1));
  return weekStart.add(Duration(days: target - 1));
}

DateTime _nextWeekday(DateTime now, int target) {
  var delta = (target - now.weekday) % 7;
  if (delta == 0) delta = 7;
  return now.add(Duration(days: delta));
}

DateResult ground(String? phrase, DateTime now) {
  if (phrase == null || phrase.trim().isEmpty) {
    return const DateResult(null, true);
  }

  if (isSomedayPhrase(phrase) && !_dateish.hasMatch(phrase)) {
    return const DateResult(null, true);
  }

  final text = _normalize(phrase);

  switch (text) {
    case 'now': return DateResult(now, true);
    case 'today': return DateResult(_noon(now), true);
    case 'this morning': return DateResult(_atTime(now, 9), true);
    case 'tonight': case 'this evening': return DateResult(_atTime(now, 20), true);
    case 'this afternoon': return DateResult(_atTime(now, 14), true);
    case 'yesterday':
      return DateResult(_noon(now.subtract(const Duration(days: 1))), true);
    case 'tomorrow':
      return DateResult(_noon(now.add(const Duration(days: 1))), true);
    case 'last week':
      return DateResult(_noon(now.subtract(const Duration(days: 7))), true);
    case 'next week':
      return DateResult(_noon(now.add(const Duration(days: 7))), true);
    case 'last month': return DateResult(_noon(_addMonths(now, -1)), true);
    case 'next month': return DateResult(_noon(_addMonths(now, 1)), true);
    case 'last year': return DateResult(_noon(_addMonths(now, -12)), true);
    case 'next year': return DateResult(_noon(_addMonths(now, 12)), true);
  }

  // "2 years now" / "for 2 years now" — an ongoing state that began N units ago
  var m = RegExp(r'^(\d+|a|an) ([a-z]+?)s? now$').firstMatch(text);
  if (m != null && _units.containsKey(m.group(2))) {
    final qty = (m.group(1) == 'a' || m.group(1) == 'an') ? 1 : int.parse(m.group(1)!);
    return DateResult(_noon(_shift(now, _units[m.group(2)]!, -qty)), true);
  }

  int sign = 1;
  m = RegExp(r'^(?:in )?(\d+|a|an) ([a-z]+?)s? ago$').firstMatch(text);
  if (m == null) {
    m = RegExp(r'^(?:in )?(\d+|a|an) ([a-z]+?)s?(?: from now)?$').firstMatch(text);
  } else {
    sign = -1;
  }
  if (m != null && _units.containsKey(m.group(2))) {
    final qtyRaw = m.group(1)!;
    final qty = (qtyRaw == 'a' || qtyRaw == 'an') ? 1 : int.parse(qtyRaw);
    return DateResult(_noon(_shift(now, _units[m.group(2)]!, sign * qty)), true);
  }

  m = RegExp(r'^(last|this|next) ([a-z]+)$').firstMatch(text);
  if (m != null) {
    final qualifier = m.group(1)!, wd = m.group(2)!;
    if (_weekdays.containsKey(wd)) {
      final target = _weekdays[wd]!;
      if (qualifier == 'last') return DateResult(_noon(_lastWeekday(now, target)), true);
      if (qualifier == 'this') return DateResult(_noon(_thisWeekday(now, target)), true);
      return DateResult(_noon(_nextWeekday(now, target)), true);
    }
  }

  if (_weekdays.containsKey(text)) {
    return DateResult(_noon(_nextWeekday(now, _weekdays[text]!)), true);
  }

  // A weekday name embedded in other text ("Tuesday whenever", "Friday, no
  // rush") — dateutil's fuzzy parser picks this up implicitly; a plain
  // word-boundary search on the weekday table does the same for this shape
  // without pulling in general fuzzy parsing.
  final wdMatch = RegExp(_weekdayToken, caseSensitive: false).firstMatch(text);
  if (wdMatch != null) {
    final wd = _weekdays[wdMatch.group(0)!.toLowerCase()];
    if (wd != null) return DateResult(_noon(_nextWeekday(now, wd)), true);
  }

  final grounded = _parseAbsolute(text, now);
  if (grounded != null) return DateResult(grounded, true);

  return const DateResult(null, false);
}

DateTime _shift(DateTime d, String unit, int qty) {
  switch (unit) {
    case 'days': return d.add(Duration(days: qty));
    case 'weeks': return d.add(Duration(days: qty * 7));
    case 'months': return _addMonths(d, qty);
    case 'years': return _addMonths(d, qty * 12);
  }
  throw ArgumentError(unit);
}

const List<String> _monthNames = [
  'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
  'september', 'october', 'november', 'december',
];

/// The absolute/fuzzy fallback. NOT a general natural-language date parser —
/// io_assistant's Python original leans on dateutil.parser(fuzzy=True), which
/// has no Dart equivalent of that scope. This covers exactly the phrase
/// shapes IO's own test suite exercises: ISO YYYY-MM-DD, and "[ordinal] of
/// [month]" / "[month] [ordinal]" with an optional leading relative-phrase
/// prefix ("tomorrow, the 10th of september").
/// ponytail: a real chrono-style fuzzy parser (e.g. a chrono_dart-class
/// package) would widen this; upgrade if a phrase shape outside this list
/// needs to ground.
DateTime? _parseAbsolute(String text, DateTime now) {
  final base = _noon(now);
  final hasYear = RegExp(r'\d{4}').hasMatch(text);

  final iso = RegExp(r'(\d{4})-(\d{2})-(\d{2})').firstMatch(text);
  if (iso != null) {
    return DateTime.utc(int.parse(iso.group(1)!), int.parse(iso.group(2)!),
        int.parse(iso.group(3)!), 12);
  }

  final monthPat = _monthNames.map((m) => m.substring(0, 3)).join('|');

  var m = RegExp(r'(\d{1,2})(?:st|nd|rd|th)?\s+of\s+($monthPat[a-z]*)'
          .replaceFirst(r'$monthPat', monthPat))
      .firstMatch(text);
  m ??= RegExp(r'($monthPat[a-z]*)\s+(\d{1,2})(?:st|nd|rd|th)?'
          .replaceFirst(r'$monthPat', monthPat))
      .firstMatch(text);
  if (m == null) return null;

  final g1 = m.group(1)!, g2 = m.group(2)!;
  final int day;
  final int? month;
  if (RegExp(r'^\d').hasMatch(g1)) {
    day = int.parse(g1);
    month = _monthIndex(g2);
  } else {
    month = _monthIndex(g1);
    day = int.parse(g2);
  }
  if (month == null) return null;
  final yearMatch = RegExp(r'\d{4}').firstMatch(text);
  final year = yearMatch != null ? int.parse(yearMatch.group(0)!) : base.year;

  var dt = DateTime.utc(year, month, day, 12);
  if (!hasYear && dt.isBefore(base.subtract(const Duration(days: 1)))) {
    dt = DateTime.utc(year + 1, month, day, 12);
  }
  if (dt.difference(now).inDays.abs() > 366 * 5) return null;
  return dt;
}

int? _monthIndex(String token) {
  final t = token.toLowerCase();
  for (var i = 0; i < _monthNames.length; i++) {
    if (_monthNames[i] == t || _monthNames[i].substring(0, 3) == t.substring(0, 3.clamp(0, t.length))) {
      return i + 1;
    }
  }
  return null;
}

String? toRrule(String? phrase) {
  if (phrase == null || phrase.trim().isEmpty) return null;
  final text = _normalize(phrase);

  switch (text) {
    case 'every day': case 'daily': case 'each day': return 'FREQ=DAILY';
    case 'every weekday': case 'weekdays': case 'every week day':
      return 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR';
    case 'every week': case 'weekly': return 'FREQ=WEEKLY';
    case 'every month': case 'monthly': return 'FREQ=MONTHLY';
    case 'every year': case 'yearly': case 'annually': return 'FREQ=YEARLY';
  }

  var m = RegExp(r'^every ([a-z]+)$').firstMatch(text);
  if (m != null && _weekdays.containsKey(m.group(1))) {
    return 'FREQ=WEEKLY;BYDAY=${_rruleWeekdayCode[_weekdays[m.group(1)]!]}';
  }

  m = RegExp(r'^([a-z]+)s$').firstMatch(text);
  if (m != null && _weekdays.containsKey(m.group(1))) {
    return 'FREQ=WEEKLY;BYDAY=${_rruleWeekdayCode[_weekdays[m.group(1)]!]}';
  }

  return null;
}
