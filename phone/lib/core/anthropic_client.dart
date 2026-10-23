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

  /// One Messages call; returns the concatenated text blocks. `system` is a
  /// String or a list of blocks (to carry cache_control).
  Future<String> complete({
    required String apiKey,
    required String model,
    required Object system,
    required String user,
    required int maxTokens,
  }) async {
    final resp = await _http.post(
      Uri.parse('https://api.anthropic.com/v1/messages'),
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: jsonEncode({
        'model': model,
        'max_tokens': maxTokens,
        'system': system,
        'messages': [{'role': 'user', 'content': user}],
      }),
    );
    if (resp.statusCode != 200) throw AnthropicApiError(resp.statusCode);
    // bodyBytes + utf8: `body` falls back to Latin-1 when the response declares no
    // charset (Anthropic sends bare application/json), which garbles any
    // non-ASCII name or dash in an answer.
    final content = (jsonDecode(utf8.decode(resp.bodyBytes)) as Map)['content'] as List? ?? const [];
    return content
        .whereType<Map>()
        .where((b) => b['type'] == 'text')
        .map((b) => b['text'] as String)
        .join()
        .trim();
  }
}
