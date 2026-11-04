import 'package:flutter/material.dart';
import '../../core/anthropic_client.dart';
import '../../core/secure_store.dart';

class ApiKeyScreen extends StatefulWidget {
  final SecureStore store;
  final AnthropicClient client;
  final VoidCallback onDone;
  const ApiKeyScreen(
      {super.key, required this.store, required this.client, required this.onDone});

  @override
  State<ApiKeyScreen> createState() => _ApiKeyScreenState();
}

class _ApiKeyScreenState extends State<ApiKeyScreen> {
  final _controller = TextEditingController();
  bool _checking = false;
  String? _error;

  Future<void> _continue() async {
    final key = _controller.text.trim();
    if (key.isEmpty) return;
    setState(() { _checking = true; _error = null; });
    try {
      final ok = await widget.client.validateKey(key);
      if (!ok) {
        setState(() { _checking = false; _error = "That key didn't work."; });
        return;
      }
      await widget.store.setApiKey(key);
      widget.onDone();
    } catch (_) {
      setState(() { _checking = false; _error = "Couldn't reach Anthropic — try again."; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Enter your Anthropic API key',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w500)),
              const SizedBox(height: 16),
              TextField(
                controller: _controller,
                obscureText: true,
                decoration: const InputDecoration(hintText: 'sk-ant-…'),
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!, style: const TextStyle(color: Colors.redAccent)),
              ],
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _checking ? null : _continue,
                child: Text(_checking ? 'Checking…' : 'Continue'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
