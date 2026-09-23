import 'package:flutter/material.dart';
import 'core/anthropic_client.dart';
import 'core/secure_store.dart';
import 'features/onboarding/api_key_screen.dart';
import 'package:http/http.dart' as http;

void main() => runApp(const IoApp());

class IoApp extends StatelessWidget {
  const IoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'IO',
      theme: ThemeData(useMaterial3: true, brightness: Brightness.dark,
          colorSchemeSeed: const Color(0xFF9184D9)),
      home: ApiKeyScreen(
        store: SecureStore(),
        client: AnthropicClient(http: http.Client()),
        onDone: () {},   // next screen arrives with the sync-phase plan
      ),
    );
  }
}
