/// Web-backed answers, borrowed from the user's own desktop. The phone answers
/// from its own memory by default and only reaches for the web when the
/// question is clearly about the outside world (the desktop's precheck, ported)
/// or the user explicitly asks it to search. See the phone-app design spec §5.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'home_server.dart';

class WebIntent {
  final String kind; // "news" | "fact"
  final String query;
  final bool explicit;
  const WebIntent(this.kind, this.query, {this.explicit = false});
}

// io_assistant/orchestrator.py: _WEB_NEWS / _WEB_FACT / _WEB_PERSONAL.
final _news = RegExp(
    r"\b(news|headlines?|breaking)\b|what'?s happening|what is happening"
    r"|latest (on|about|from|news)",
    caseSensitive: false);
final _fact = RegExp(
    r"\bprice of\b|\bexchange rate\b|how much (is|are|does|do)\b"
    r"|\b(stock|share) price\b|\bweather (in|for|today|tomorrow|this)\b"
    r"|\bwho won\b|\b(usd|eur|gbp|pkr|inr|btc|eth)\b.{0,20}\bto\b"
    r"|\bcurrent(ly)?\b.{0,30}\b(price|rate|value|cost)\b"
    r"|\bhow'?s the (weather|market|traffic)\b",
    caseSensitive: false);
final _personal = RegExp(r"\b(my|mine|i|i'?m|i'?ve|we|we'?ve|our|us)\b", caseSensitive: false);

// "search the web for X", "google X", "look up X" — only at the start of the
// message, so "I need to search my attic" never counts.
final _explicit = RegExp(
    r"^\s*(?:please\s+|can you\s+|could you\s+)?"
    r"(?:search(?:\s+(?:the\s+)?(?:web|internet|online))?(?:\s+for)?|google|look\s+up|web\s+search(?:\s+for)?)"
    r"\s+(.+?)\s*$",
    caseSensitive: false);
const _filler = {'the web', 'web', 'the internet', 'internet', 'online', 'for'};

/// Whether this message should go to the web, and as what. Null = answer from
/// the user's own memory (the default).
WebIntent? webIntent(String text) {
  final t = text.trim();
  if (t.isEmpty) return null;

  final ex = _explicit.firstMatch(t);
  if (ex != null) {
    final q = ex.group(1)!.trim();
    if (q.isEmpty || _filler.contains(q.toLowerCase())) return null;
    return WebIntent(_news.hasMatch(q) ? 'news' : 'fact', q, explicit: true);
  }
  if (_personal.hasMatch(t)) return null; // about the user's own life
  if (_news.hasMatch(t)) return WebIntent('news', t);
  if (_fact.hasMatch(t)) return WebIntent('fact', t);
  return null;
}

class WebSource {
  final String title, url;
  const WebSource(this.title, this.url);
}

class WebAnswer {
  final String text, kind, tier;
  final List<WebSource> sources;
  final bool cached;
  const WebAnswer(this.text, this.kind, this.tier, this.sources, this.cached);

  /// The answer plus up to three sources, as chat text.
  String render() {
    if (sources.isEmpty) return text;
    final lines = [for (final s in sources.take(3)) '• ${s.title.isEmpty ? s.url : s.title} — ${s.url}'];
    return '$text\n\nSources:\n${lines.join('\n')}';
  }
}

class WebUnavailable implements Exception {
  final String message;
  WebUnavailable(this.message);
  @override
  String toString() => message;
}

abstract class WebClient {
  Future<bool> isConfigured();
  Future<WebAnswer> answer(String query, String kind);
}

const _unreachable = "I couldn't reach your desktop — is it on, and are both devices on the same private network (e.g. Tailscale)?";

class HomeWebClient implements WebClient {
  final http.Client _http;
  final Future<HomeServer?> Function() _home;
  final Duration timeout;
  HomeWebClient(this._http, this._home, {this.timeout = const Duration(seconds: 45)});

  @override
  Future<bool> isConfigured() async => await _home() != null;

  Map<String, String> _auth(HomeServer h) => {'authorization': 'Bearer ${h.token}'};

  @override
  Future<WebAnswer> answer(String query, String kind) async {
    final h = await _home();
    if (h == null) throw WebUnavailable('Set your home server in Settings first.');
    final http.Response r;
    try {
      r = await _http
          .get(Uri.parse('${h.baseUrl}/web').replace(queryParameters: {'q': query, 'kind': kind}),
              headers: _auth(h))
          .timeout(timeout);
    } on http.ClientException {
      throw WebUnavailable(_unreachable);
    } on SocketException {
      throw WebUnavailable(_unreachable);
    } on TimeoutException {
      throw WebUnavailable(_unreachable);
    }
    switch (r.statusCode) {
      case 200:
        final j = jsonDecode(utf8.decode(r.bodyBytes)) as Map;
        return WebAnswer(
          j['text'] as String, '${j['kind']}', '${j['tier']}',
          [for (final s in (j['sources'] as List? ?? const [])) WebSource('${s['title'] ?? ''}', '${s['url'] ?? ''}')],
          j['cached'] == true,
        );
      case 401:
        throw WebUnavailable("Your desktop rejected the token — check it in Settings.");
      case 404:
        throw WebUnavailable('Web answers are turned off on your desktop ([web] enabled = false).');
      case 502:
        throw WebUnavailable("Your desktop couldn't find a web answer for that.");
      default:
        throw WebUnavailable('Your desktop returned an error (HTTP ${r.statusCode}).');
    }
  }

  /// A friendly status for the Settings "Test connection" button.
  Future<String> check() async {
    final h = await _home();
    if (h == null) return 'Home server not set.';
    try {
      final health = await _http.get(Uri.parse('${h.baseUrl}/health')).timeout(const Duration(seconds: 10));
      if (health.statusCode != 200) {
        return "Reached something, but it didn't look like IO (HTTP ${health.statusCode}).";
      }
      final authed = await _http.get(Uri.parse('${h.baseUrl}/alerts'), headers: _auth(h))
          .timeout(const Duration(seconds: 10));
      if (authed.statusCode == 401) return "Reached your desktop, but the token doesn't match.";
      if (authed.statusCode != 200) return 'Reached your desktop, but it returned HTTP ${authed.statusCode}.';
      return 'Connected to your desktop.';
    } on http.ClientException {
      return _unreachable;
    } on SocketException {
      return _unreachable;
    } on TimeoutException {
      return _unreachable;
    }
  }
}
