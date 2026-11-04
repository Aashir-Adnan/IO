import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:io_phone/core/anthropic_client.dart';

void main() {
  test('a 200 response means the key is valid', () async {
    final client = AnthropicClient(http: MockClient((req) async {
      expect(req.headers['x-api-key'], 'sk-good');
      expect(req.url.path, '/v1/messages');
      return http.Response(jsonEncode({'content': []}), 200);
    }));
    expect(await client.validateKey('sk-good'), isTrue);
  });

  test('a 401 means the key is invalid, not an error', () async {
    final client = AnthropicClient(
        http: MockClient((req) async => http.Response('{}', 401)));
    expect(await client.validateKey('sk-bad'), isFalse);
  });

  test('a 500 rethrows so the UI can say "try again" not "bad key"', () async {
    final client = AnthropicClient(
        http: MockClient((req) async => http.Response('{}', 500)));
    expect(() => client.validateKey('sk-x'), throwsA(isA<AnthropicApiError>()));
  });
}
