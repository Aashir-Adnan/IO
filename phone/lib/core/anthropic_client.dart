import 'dart:convert';
import 'package:http/http.dart' as http;

class AnthropicApiError implements Exception {
  final int statusCode;
  AnthropicApiError(this.statusCode);
  @override
  String toString() => 'AnthropicApiError($statusCode)';
}

/// The one call onboarding needs: is this key good? A cheap max_tokens:1 turn
/// costs a fraction of a cent and confirms the key works before it's saved.
class AnthropicClient {
  final http.Client _http;
  AnthropicClient({required http.Client http}) : _http = http;

  Future<bool> validateKey(String apiKey) async {
    final resp = await _http.post(
      Uri.parse('https://api.anthropic.com/v1/messages'),
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: jsonEncode({
        'model': 'claude-haiku-4-5',
        'max_tokens': 1,
        'messages': [{'role': 'user', 'content': 'hi'}],
      }),
    );
    if (resp.statusCode == 200) return true;
    if (resp.statusCode == 401 || resp.statusCode == 403) return false;
    throw AnthropicApiError(resp.statusCode);
  }
}
