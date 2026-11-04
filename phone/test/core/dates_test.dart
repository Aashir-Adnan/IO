import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/core/dates.dart';

final now = DateTime.utc(2026, 9, 7, 15, 0); // a Monday

void main() {
  test('null phrase ok', () {
    final r = ground(null, now);
    expect(r.ok, isTrue);
    expect(r.value, isNull);
  });

  test('empty phrase ok', () {
    final r = ground('   ', now);
    expect(r.ok, isTrue);
    expect(r.value, isNull);
  });

  test('today snaps to noon', () {
    final r = ground('today', now);
    expect(r.ok, isTrue);
    expect(r.value!.toUtc().year, 2026);
    expect((r.value!.hour, r.value!.minute), (12, 0));
  });

  test('now stays exact', () {
    final r = ground('now', now);
    expect(r.ok, isTrue);
    expect(r.value, now);
  });

  test('yesterday', () {
    final r = ground('yesterday', now);
    expect(_ymd(r.value!), (2026, 9, 6));
    expect(r.value!.hour, 12);
  });

  test('tomorrow', () {
    final r = ground('tomorrow', now);
    expect(_ymd(r.value!), (2026, 9, 8));
  });

  test('this morning', () {
    final r = ground('this morning', now);
    expect(_ymd(r.value!), (2026, 9, 7));
    expect((r.value!.hour, r.value!.minute), (9, 0));
  });

  test('tonight', () {
    final r = ground('tonight', now);
    expect((r.value!.hour, r.value!.minute), (20, 0));
  });

  test('this evening', () {
    final r = ground('this evening', now);
    expect(r.value!.hour, 20);
  });

  test('this afternoon', () {
    final r = ground('this afternoon', now);
    expect(r.value!.hour, 14);
  });

  test('in 3 days', () {
    expect(_ymd(ground('in 3 days', now).value!), (2026, 9, 10));
  });

  test('3 days ago', () {
    expect(_ymd(ground('3 days ago', now).value!), (2026, 9, 4));
  });

  test('2 years ago', () {
    expect(_ymd(ground('2 years ago', now).value!), (2024, 9, 7));
  });

  test('for 2 years now', () {
    expect(_ymd(ground('for 2 years now', now).value!), (2024, 9, 7));
  });

  test('3 weeks ago', () {
    expect(_ymd(ground('3 weeks ago', now).value!), (2026, 8, 17));
  });

  test('6 months ago', () {
    expect(_ymd(ground('6 months ago', now).value!), (2026, 3, 7));
  });

  test('in 2 weeks', () {
    expect(_ymd(ground('in 2 weeks', now).value!), (2026, 9, 21));
  });

  test('a year ago', () {
    expect(_ymd(ground('a year ago', now).value!), (2025, 9, 7));
  });

  test('last month', () {
    expect(_ymd(ground('last month', now).value!), (2026, 8, 7));
  });

  test('last year', () {
    expect(_ymd(ground('last year', now).value!), (2025, 9, 7));
  });

  test('last week', () {
    expect(_ymd(ground('last week', now).value!), (2026, 8, 31));
  });

  test('next week', () {
    expect(_ymd(ground('next week', now).value!), (2026, 9, 14));
  });

  test('last friday', () {
    expect(_ymd(ground('last Friday', now).value!), (2026, 9, 4));
  });

  test('last monday (now is Monday -> back 7 days)', () {
    expect(_ymd(ground('last Monday', now).value!), (2026, 8, 31));
  });

  test('this friday', () {
    expect(_ymd(ground('this Friday', now).value!), (2026, 9, 11));
  });

  test('next wednesday', () {
    expect(_ymd(ground('next Wednesday', now).value!), (2026, 9, 9));
  });

  test('bare weekday future', () {
    expect(_ymd(ground('Wednesday', now).value!), (2026, 9, 9));
  });

  test('leading on', () {
    expect(_ymd(ground('on tomorrow', now).value!), (2026, 9, 8));
  });

  test('case insensitive', () {
    expect(_ymd(ground('YESTERDAY', now).value!), (2026, 9, 6));
  });

  test('unparseable not ok', () {
    final r = ground('sometime around the harvest festival', now);
    expect(r.ok, isFalse);
    expect(r.value, isNull);
  });

  test('tz preserved (both UTC)', () {
    final r = ground('in 5 days', now);
    expect(r.value!.isUtc, now.isUtc);
  });

  test('rrule every monday', () => expect(toRrule('every Monday'), 'FREQ=WEEKLY;BYDAY=MO'));
  test('rrule mondays', () => expect(toRrule('mondays'), 'FREQ=WEEKLY;BYDAY=MO'));
  test('rrule every mon', () => expect(toRrule('every mon'), 'FREQ=WEEKLY;BYDAY=MO'));
  test('rrule every weekday',
      () => expect(toRrule('every weekday'), 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'));
  test('rrule daily', () {
    expect(toRrule('daily'), 'FREQ=DAILY');
    expect(toRrule('every day'), 'FREQ=DAILY');
  });
  test('rrule weekly', () => expect(toRrule('weekly'), 'FREQ=WEEKLY'));
  test('rrule monthly', () => expect(toRrule('monthly'), 'FREQ=MONTHLY'));
  test('rrule yearly', () => expect(toRrule('annually'), 'FREQ=YEARLY'));
  test('rrule unknown none', () => expect(toRrule('once in a blue moon'), isNull));
  test('rrule none', () => expect(toRrule(null), isNull));

  // --- absolute / narrowed-fuzzy date grounding ---------------------------

  test('absolute the 10th of september', () {
    expect(_ymd(ground('the 10th of september', now).value!), (2026, 9, 10));
  });

  test('absolute with relative prefix', () {
    final r = ground('tomorrow, the 10th of september', now);
    expect(_ymd(r.value!), (2026, 9, 10));
  });

  test('iso date grounds', () {
    expect(_ymd(ground('2026-12-01', now).value!), (2026, 12, 1));
  });

  test('bare month day in the past rolls to next year', () {
    expect(_ymd(ground('3rd of january', now).value!), (2027, 1, 3));
  });

  test('true garbage still gates', () {
    final r = ground('some time soon-ish maybe', now);
    expect(r.ok, isFalse);
    expect(r.value, isNull);
  });

  test('absolute date equal to today still grounds', () {
    final today = DateTime.utc(2026, 9, 10, 9, 30);
    final r = ground('the 10th of september', today);
    expect(r.ok, isTrue);
    expect(_ymd(r.value!), (2026, 9, 10));
  });

  // --- someday phrasing -----------------------------------------------------

  test('someday phrases ground to dateless not gated', () {
    for (final phrase in ['someday', 'eventually', 'no rush']) {
      final r = ground(phrase, now);
      expect(r.ok, isTrue, reason: phrase);
      expect(r.value, isNull, reason: phrase);
    }
  });

  test('next friday still grounds normally', () {
    expect(_ymd(ground('next friday', now).value!), (2026, 9, 11));
  });

  test('mixed someday and real date still grounds the date', () {
    expect(_ymd(ground('Friday, no rush', now).value!), (2026, 9, 11));
    expect(_ymd(ground('Tuesday whenever', now).value!), (2026, 9, 8));
  });

  test('one day idiom is not swallowed as someday', () {
    final r = ground('one day at a time', now);
    expect(r.ok, isFalse);
    expect(r.value, isNull);
  });

  test('start of day is local midnight', () {
    final d = DateTime.utc(2026, 9, 7, 18, 30, 45);
    expect(startOfDay(d), DateTime.utc(2026, 9, 7, 0, 0));
  });

  test('is someday phrase', () {
    expect(isSomedayPhrase('someday'), isTrue);
    expect(isSomedayPhrase('eventually'), isTrue);
    expect(isSomedayPhrase('no rush'), isTrue);
    expect(isSomedayPhrase(null), isFalse);
    expect(isSomedayPhrase(''), isFalse);
    expect(isSomedayPhrase('next friday'), isFalse);
  });
}

(int, int, int) _ymd(DateTime d) => (d.year, d.month, d.day);
