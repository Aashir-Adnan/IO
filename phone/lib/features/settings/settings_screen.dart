import 'package:flutter/material.dart';
import '../../core/secure_store.dart';

class SettingsScreen extends StatelessWidget {
  final SecureStore store;
  final VoidCallback onKeyRemoved;
  const SettingsScreen({super.key, required this.store, required this.onKeyRemoved});

  Future<void> _remove(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Remove API key?'),
        content: const Text('IO will stop answering until you enter a key again. '
            'Your memories stay on this device.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Remove')),
        ],
      ),
    );
    if (ok != true) return;
    await store.clearApiKey();
    onKeyRemoved();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        children: [
          const ListTile(
            leading: Icon(Icons.key),
            title: Text('Anthropic API key saved'),
            subtitle: Text('Kept in this phone\'s secure keystore.'),
          ),
          ListTile(
            key: const Key('remove-key'),
            leading: const Icon(Icons.delete_outline),
            title: const Text('Remove key'),
            onTap: () => _remove(context),
          ),
          const Divider(),
          const ListTile(
            leading: Icon(Icons.phone_android),
            title: Text('Your memories live on this device'),
            subtitle: Text('Sync with your desktop arrives in a later update.'),
          ),
        ],
      ),
    );
  }
}
