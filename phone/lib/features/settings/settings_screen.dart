import 'package:flutter/material.dart';
import '../../core/home_server.dart';
import '../../core/secure_store.dart';
import '../../sync/sync_manager.dart';
import 'sync_message.dart';

class SettingsScreen extends StatelessWidget {
  final SecureStore store;
  final SyncState sync;
  final VoidCallback onKeyRemoved;

  /// The optional desktop that answers web questions; hidden when null.
  final HomeServerStore? home;
  final Future<String> Function()? homeCheck;
  const SettingsScreen(
      {super.key, required this.store, required this.sync, required this.onKeyRemoved,
      this.home, this.homeCheck});

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
          if (home != null) ...[
            _HomeSection(home: home!, check: homeCheck),
            const Divider(),
          ],
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

class _HomeSection extends StatefulWidget {
  final HomeServerStore home;
  final Future<String> Function()? check;
  const _HomeSection({required this.home, this.check});
  @override
  State<_HomeSection> createState() => _HomeSectionState();
}

class _HomeSectionState extends State<_HomeSection> {
  final _url = TextEditingController();
  final _token = TextEditingController();
  String? _status;

  @override
  void initState() {
    super.initState();
    widget.home.load().then((h) {
      if (!mounted || h == null) return;
      _url.text = h.baseUrl;
      _token.text = h.token;
    });
  }

  @override
  void dispose() {
    _url.dispose();
    _token.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    await widget.home.save(HomeServer(_url.text, _token.text));
    final h = await widget.home.load();
    if (!mounted) return;
    setState(() {
      _url.text = h?.baseUrl ?? '';
      _status = h == null ? 'Cleared.' : 'Saved.';
    });
  }

  Future<void> _clear() async {
    await widget.home.clear();
    if (!mounted) return;
    setState(() {
      _url.clear();
      _token.clear();
      _status = 'Cleared.';
    });
  }

  Future<void> _test() async {
    await _save();
    if (!mounted) return;
    setState(() => _status = 'Testing...');
    final r = await (widget.check?.call() ?? Future.value('Not available.'));
    if (mounted) setState(() => _status = r);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Home server (optional)', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          const Text('Your own desktop IO, over Tailscale. Used only for news and facts '
              'about the outside world, or when you say "search the web for ...".'),
          const SizedBox(height: 8),
          TextField(
              key: const Key('home-url'),
              controller: _url,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(labelText: 'Address, e.g. 100.64.0.2:8765')),
          TextField(
              key: const Key('home-token'),
              controller: _token,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Token (service.remote_token)')),
          const SizedBox(height: 8),
          Wrap(spacing: 8, children: [
            FilledButton(key: const Key('home-save'), onPressed: _save, child: const Text('Save')),
            TextButton(key: const Key('home-test'), onPressed: _test, child: const Text('Test')),
            TextButton(key: const Key('home-clear'), onPressed: _clear, child: const Text('Clear')),
          ]),
          if (_status != null)
            Padding(padding: const EdgeInsets.only(top: 8), child: Text(_status!)),
        ],
      ),
    );
  }
}
