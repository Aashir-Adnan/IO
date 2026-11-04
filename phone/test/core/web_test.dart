import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:io_phone/core/home_server.dart';
import 'package:io_phone/core/secure_store.dart';
import 'package:io_phone/core/web.dart';

class FakeKv implements KeyValueStore {
  final data = <String, String>{};
  @override
  Future<void> write({required String key, required String? value}) async {
    if (value == null) { data.remove(key); } else { data[key] = value; }
  }
  @override
  Future<String?> read({required String key}) async => data[key];
}

void main() {
  group('webIntent (the desktop precheck + explicit asks)', () {
    test('news and fact shapes with no first-person reference go to the web', () {
      expect(webIntent("what's the news on Korea")?.kind, 'news');
      expect(webIntent('latest on the election')?.kind, 'news');
      expect(webIntent('breaking headlines')?.kind, 'news');
      expect(webIntent('usd to pkr')?.kind, 'fact');
      expect(webIntent('price of gold today')?.kind, 'fact');
      expect(webIntent('weather in Lahore tomorrow')?.kind, 'fact');
      expect(webIntent('who won the match')?.kind, 'fact');
      expect(webIntent("how's the market")?.kind, 'fact');
    });

    test('anything about the user\'s own life never touches the network', () {
      for (final q in ["what's my mom's favorite food", 'how much did I spend on rent',
        "what's the weather I told you about", 'when is our next meeting', "i'm worried about the news"]) {
        expect(webIntent(q), isNull, reason: q);
      }
    });

    test('ordinary memory questions and statements are not web', () {
      for (final q in ['what tasks do I have', 'remind me to call mum', 'hello', '', '   ']) {
        expect(webIntent(q), isNull, reason: q);
      }
    });

    test('an explicit ask overrides the personal guard and extracts the query', () {
      final a = webIntent('search the web for best espresso machines')!;
      expect((a.kind, a.query, a.explicit), ('fact', 'best espresso machines', true));
      expect(webIntent('google flights to Dubai')!.query, 'flights to Dubai');
      expect(webIntent('look up the capital of Peru')!.query, 'the capital of Peru');
      expect(webIntent('Please search online for my favourite band news')!.explicit, isTrue);
      expect(webIntent('search the web for the latest news on Korea')!.kind, 'news');
    });

    test('"search" inside a normal sentence is not an explicit ask', () {
      expect(webIntent('I need to search my attic for the old photos'), isNull);
      expect(webIntent('remind me to look up the dentist number'), isNull);
    });

    test('an explicit ask with no query is not an ask', () {
      expect(webIntent('search the web'), isNull);
    });

    test('a non-explicit intent keeps the whole text as the query', () {
      expect(webIntent('price of gold today')!.query, 'price of gold today');
    });
  });

  group('HomeServerStore', () {
    test('saves, loads and clears the url and token', () async {
      final s = HomeServerStore(FakeKv());
      expect(await s.load(), isNull);
      await s.save(const HomeServer('http://100.64.0.2:8765/', 'tok'));
      final h = (await s.load())!;
      expect((h.baseUrl, h.token), ('http://100.64.0.2:8765', 'tok')); // trailing slash dropped
      await s.clear();
      expect(await s.load(), isNull);
    });

    test('a url with no scheme gets http:// (Tailscale hosts are plain http)', () async {
      final s = HomeServerStore(FakeKv());
      await s.save(const HomeServer('100.64.0.2:8765', 't'));
      expect((await s.load())!.baseUrl, 'http://100.64.0.2:8765');
    });

    test('an empty url is the same as not configured', () async {
      final s = HomeServerStore(FakeKv());
      await s.save(const HomeServer('  ', 't'));
      expect(await s.load(), isNull);
    });
  });

  group('HomeWebClient', () {
    HomeWebClient client(http.Client c, {HomeServer? home = const HomeServer('http://h:8765', 'tok')}) =>
        HomeWebClient(c, () async => home);

    http.Response ok(Map o) => http.Response.bytes(utf8.encode(jsonEncode(o)), 200,
        headers: {'content-type': 'application/json'});

    test('not configured: reports so and never calls out', () async {
      final c = client(MockClient((r) async => fail('must not call')), home: null);
      expect(await c.isConfigured(), isFalse);
      expect(() => c.answer('q', 'fact'), throwsA(isA<WebUnavailable>()));
    });

    test('sends the bearer token and parses the answer with sources', () async {
      late http.Request seen;
      final c = client(MockClient((r) async {
        seen = r;
        return ok({'text': 'Gold is up — 2,400 USD.', 'kind': 'fact', 'tier': 'c',
          'sources': [{'title': 'Kitco', 'url': 'https://kitco.example'}], 'cached': false});
      }));
      final a = await c.answer('price of gold', 'fact');
      expect(seen.url.toString(), startsWith('http://h:8765/web?'));
      expect(seen.url.queryParameters, {'q': 'price of gold', 'kind': 'fact'});
      expect(seen.headers['authorization'], 'Bearer tok');
      expect(a.text, 'Gold is up — 2,400 USD.'); // UTF-8 survives
      expect(a.sources.single.title, 'Kitco');
    });

    test('a 404 means web answers are off on the desktop', () async {
      final c = client(MockClient((r) async => http.Response('{"detail":"web answers are disabled"}', 404)));
      expect(() => c.answer('q', 'fact'),
          throwsA(isA<WebUnavailable>().having((e) => e.message, 'message', contains('turned off'))));
    });

    test('a 401 means the token is wrong', () async {
      final c = client(MockClient((r) async => http.Response('{}', 401)));
      expect(() => c.answer('q', 'fact'),
          throwsA(isA<WebUnavailable>().having((e) => e.message, 'message', contains('token'))));
    });

    test('a network failure means the desktop is unreachable', () async {
      final c = client(MockClient((r) async => throw http.ClientException('no route')));
      expect(() => c.answer('q', 'fact'),
          throwsA(isA<WebUnavailable>().having((e) => e.message, 'message', contains("couldn't reach"))));
    });

    test('check() tells the user what is wrong', () async {
      http.Client mock(int health, int authed) => MockClient((r) async =>
          http.Response('{}', r.url.path == '/health' ? health : authed));
      expect(await client(mock(200, 200)).check(), contains('Connected'));
      expect(await client(mock(200, 401)).check(), contains('token'));
      expect(await client(MockClient((r) async => throw http.ClientException('x'))).check(),
          contains("couldn't reach"));
      expect(await client(mock(200, 200), home: null).check(), contains('not set'));
    });
  });
}
