/// The four model calls the chat loop makes — decide, plan, phrase,
/// acknowledge — using the desktop's exact prompt files (vendored under
/// assets/prompts, drift-checked by tests/test_phone_prompts_in_sync.py). The
/// model only routes/extracts/plans/phrases; dates, retrieval and identity
/// stay deterministic Dart (rules/llm-boundaries.md).
library;

import 'dart:convert';
import 'package:flutter/services.dart' show rootBundle;
import 'anthropic_client.dart';
import 'plan.dart';

abstract class PromptSource {
  Future<String> load(String name);
}

class AssetPromptSource implements PromptSource {
  @override
  Future<String> load(String name) => rootBundle.loadString('assets/prompts/$name');
}

class MissingApiKey implements Exception {
  @override
  String toString() => 'No Anthropic API key is stored yet.';
}

/// Python's str.format for our prompts: `{{`/`}}` are literal braces and
/// `{name}` is substituted. Substituted values are never re-scanned, so JSON
/// in them (rows, schema) passes through untouched.
String renderPrompt(String template, Map<String, String> vars) {
  const lb = '\u0001', rb = '\u0002';
  var s = template.replaceAll('{{', lb).replaceAll('}}', rb);
  vars.forEach((k, v) => s = s.replaceAll('{$k}', v));
  return s.replaceAll(lb, '{').replaceAll(rb, '}');
}

String renderContext(String? context) =>
    (context == null || context.isEmpty) ? '' : 'Recent conversation:\n$context\n\n';

abstract class Llm {
  Future<Plan> decide(String utterance, DateTime now, {String? context});
  Future<Map<String, Object?>> plan(String question, DateTime now, {String? context});
  Future<String> phrase(String question, List<Map<String, Object?>> rows, String shape,
      {String? context});
  Future<String> acknowledge(String facts, {String? context});
}

class AnthropicLlm implements Llm {
  final AnthropicClient client;
  final PromptSource prompts;
  final Future<String?> Function() apiKey;
  final String model;
  AnthropicLlm({
    required this.client, required this.prompts, required this.apiKey,
    this.model = 'claude-haiku-4-5',
  });

  Future<String> _complete(Object system, String user, {required int maxTokens}) async {
    final key = await apiKey();
    if (key == null || key.isEmpty) throw MissingApiKey();
    return client.complete(
        apiKey: key, model: model, system: system, user: user, maxTokens: maxTokens);
  }

  @override
  Future<Plan> decide(String utterance, DateTime now, {String? context}) async {
    final schema = await prompts.load('schema.txt');
    // Identical on every call, so it rides in a cached system block.
    final system = [
      {
        'type': 'text',
        'text': "You are IO's turn planner. Output one JSON object and nothing "
            'else.\n\nCapabilities:\n  (none)\n\nEXTRACTION schema:\n$schema',
        'cache_control': {'type': 'ephemeral'},
      }
    ];
    final user = renderPrompt(await prompts.load('decide.txt'), {
      'capabilities': '  (none)', 'schema': '(see system)',
      'context': renderContext(context), 'now': now.toIso8601String(),
      'utterance': utterance,
    });
    return parsePlan(await _complete(system, user, maxTokens: 1200));
  }

  @override
  Future<Map<String, Object?>> plan(String question, DateTime now, {String? context}) async {
    final user = renderPrompt(await prompts.load('plan.txt'), {
      'context': renderContext(context), 'now': now.toIso8601String(),
      'question': question,
    });
    final out = await _complete(
        'You convert a question into a retrieval plan. Output one JSON object and nothing else.',
        user, maxTokens: 512);
    final data = decodeJson(out, 'plan');
    if (data is! Map) throw PlanParseError('plan is not an object');
    return data.cast<String, Object?>();
  }

  @override
  Future<String> phrase(String question, List<Map<String, Object?>> rows, String shape,
      {String? context}) async {
    final user = renderPrompt(await prompts.load('respond.txt'), {
      'context': renderContext(context), 'question': question,
      'rows': jsonEncode(rows), 'shape': shape,
    });
    return _complete('You answer strictly from the provided rows.', user, maxTokens: 800);
  }

  @override
  Future<String> acknowledge(String facts, {String? context}) async {
    final user = renderPrompt(await prompts.load('acknowledge.txt'), {
      'context': renderContext(context), 'facts': facts,
    });
    return _complete('You confirm saved items as a calm personal assistant.', user,
        maxTokens: 120);
  }
}
