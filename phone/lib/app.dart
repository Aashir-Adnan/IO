import 'package:flutter/material.dart';
import 'core/anthropic_client.dart';
import 'core/secure_store.dart';
import 'features/chat/chat_screen.dart';
import 'features/chat/chat_state.dart';
import 'features/onboarding/api_key_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/tasks/tasks_screen.dart';
import 'features/tasks/tasks_state.dart';
import 'sync/sync_manager.dart';

/// Everything the screens need, built once at startup (see bootstrap.dart);
/// tests hand in fakes.
class AppServices {
  final SecureStore secureStore;
  final AnthropicClient client;
  final ChatState chat;
  final TasksState tasks;
  final SyncState sync;
  final Future<void> Function() dispose;
  AppServices({
    required this.secureStore, required this.client, required this.chat,
    required this.tasks, required this.sync, required this.dispose,
  });

  Future<bool> hasKey() async => (await secureStore.getApiKey())?.isNotEmpty ?? false;
}

class IoApp extends StatelessWidget {
  final Future<AppServices> Function() bootstrap;
  const IoApp({super.key, required this.bootstrap});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'IO',
      theme: ThemeData(
          useMaterial3: true, brightness: Brightness.dark,
          colorSchemeSeed: const Color(0xFF9184D9)),
      home: _Root(bootstrap: bootstrap),
    );
  }
}

class BootScreen extends StatelessWidget {
  const BootScreen({super.key});
  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: CircularProgressIndicator()));
}

class _Root extends StatefulWidget {
  final Future<AppServices> Function() bootstrap;
  const _Root({required this.bootstrap});
  @override
  State<_Root> createState() => _RootState();
}

class _RootState extends State<_Root> {
  AppServices? _s;
  bool? _hasKey;

  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    final s = await widget.bootstrap();
    final has = await s.hasKey();
    if (mounted) setState(() { _s = s; _hasKey = has; });
  }

  @override
  void dispose() {
    _s?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = _s;
    if (s == null || _hasKey == null) return const BootScreen();
    if (!_hasKey!) {
      return ApiKeyScreen(
        store: s.secureStore, client: s.client,
        onDone: () => setState(() => _hasKey = true),
      );
    }
    return HomeScreen(services: s, onKeyRemoved: () => setState(() => _hasKey = false));
  }
}

class HomeScreen extends StatefulWidget {
  final AppServices services;
  final VoidCallback onKeyRemoved;
  const HomeScreen({super.key, required this.services, required this.onKeyRemoved});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final s = widget.services;
    return Scaffold(
      body: IndexedStack(index: _tab, children: [
        ChatScreen(state: s.chat),
        TasksScreen(state: s.tasks),
        SettingsScreen(store: s.secureStore, sync: s.sync, onKeyRemoved: widget.onKeyRemoved),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) {
          setState(() => _tab = i);
          if (i == 1) s.tasks.load(); // a chat turn may have added or closed one
        },
        destinations: const [
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline), label: 'Chat'),
          NavigationDestination(icon: Icon(Icons.checklist), label: 'Tasks'),
          NavigationDestination(icon: Icon(Icons.settings_outlined), label: 'Settings'),
        ],
      ),
    );
  }
}
