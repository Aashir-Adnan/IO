import 'package:flutter/material.dart';

void main() => runApp(const IoApp());

class IoApp extends StatelessWidget {
  const IoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'IO',
      theme: ThemeData(useMaterial3: true, brightness: Brightness.dark,
          colorSchemeSeed: const Color(0xFF9184D9)),
      home: const Placeholder(),   // replaced by onboarding in Task 3
    );
  }
}
