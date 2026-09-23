import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/core/anthropic_client.dart';
import 'package:io_phone/core/secure_store.dart';
import 'package:io_phone/features/onboarding/api_key_screen.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _FakeKv implements KeyValueStore {
  final Map<String, String> data = {};
  @override
  Future<void> write({required String key, required String? value}) async {
    if (value == null) { data.remove(key); } else { data[key] = value; }
  }
  @override
  Future<String?> read({required String key}) async => data[key];
}

Widget _harness(SecureStore store, AnthropicClient client, VoidCallback onDone) =>
    MaterialApp(home: ApiKeyScreen(store: store, client: client, onDone: onDone));

void main() {
  testWidgets('a valid key is saved and onDone fires', (tester) async {
    final store = SecureStore(_FakeKv());
    final client = AnthropicClient(
        http: MockClient((req) async => http.Response('{}', 200)));
    var done = false;
    await tester.pumpWidget(_harness(store, client, () => done = true));

    await tester.enterText(find.byType(TextField), 'sk-ant-good');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(await store.getApiKey(), 'sk-ant-good');
    expect(done, isTrue);
  });

  testWidgets('an invalid key shows an error and saves nothing', (tester) async {
    final store = SecureStore(_FakeKv());
    final client = AnthropicClient(
        http: MockClient((req) async => http.Response('{}', 401)));
    await tester.pumpWidget(_harness(store, client, () {}));

    await tester.enterText(find.byType(TextField), 'sk-ant-bad');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(find.textContaining('key'), findsWidgets);
    expect(await store.getApiKey(), isNull);
  });

  testWidgets('a network error is distinct from a bad key', (tester) async {
    final store = SecureStore(_FakeKv());
    final client = AnthropicClient(
        http: MockClient((req) async => http.Response('{}', 500)));
    await tester.pumpWidget(_harness(store, client, () {}));

    await tester.enterText(find.byType(TextField), 'sk-ant-x');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(find.textContaining('try again'), findsOneWidget);
  });
}
