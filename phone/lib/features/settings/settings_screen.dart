import 'package:flutter/material.dart';
import '../../core/secure_store.dart';
import '../../sync/sync_manager.dart';
import 'sync_message.dart';

class SettingsScreen extends StatelessWidget {
  final SecureStore store;
  final SyncState sync;
  final VoidCallback onKeyRemoved;
  const SettingsScreen(
      {super.key, required this.store, required this.sync, required this.onKeyRemoved});

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
          _SyncSection(sync: sync),
          const Divider(),
          const ListTile(
            leading: Icon(Icons.phone_android),
            title: Text('Your memories live on this device'),
            subtitle: Text('Sync copies them to your own Google Drive, never anywhere else.'),
          ),
        ],
      ),
    );
  }
}

class _SyncSection extends StatelessWidget {
  final SyncState sync;
  const _SyncSection({required this.sync});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return ListenableBuilder(
      listenable: sync,
      builder: (context, _) {
        final m = syncMessage(sync.info, DateTime.now().toUtc());
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Account & sync', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              const Text('Through your Google Drive'),
              const SizedBox(height: 8),
              Row(children: [
                if (m.busy)
                  const Padding(
                    padding: EdgeInsets.only(right: 8),
                    child: SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                  ),
                Expanded(
                  child: Text(m.text,
                      style: TextStyle(color: m.state == 'error' ? cs.error : null)),
                ),
              ]),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                if (m.canSignIn)
                  FilledButton(
                      key: const Key('sync-signin'),
                      onPressed: sync.signIn,
                      child: const Text('Sign in with Google')),
                if (m.canSync)
                  TextButton(
                      key: const Key('sync-now'),
                      onPressed: m.busy ? null : sync.syncNow,
                      child: const Text('Sync now')),
                if (m.canSignOut)
                  TextButton(
                      key: const Key('sync-signout'),
                      onPressed: sync.signOut,
                      child: const Text('Sign out')),
              ]),
            ],
          ),
        );
      },
    );
  }
}
