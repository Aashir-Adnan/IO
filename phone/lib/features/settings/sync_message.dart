/// What Settings → Account says — a port of frontend/sync.js (syncMessage),
/// pure so it can be tested.
library;

class SyncInfo {
  final bool configured, signedIn, syncing, signingIn;
  final DateTime? lastSyncedAt;
  final String? error;
  const SyncInfo({
    required this.configured, required this.signedIn, required this.syncing,
    required this.signingIn, this.lastSyncedAt, this.error,
  });
}

class SyncMsg {
  final String text;
  final String state; // off | busy | ok | error
  final bool canSignIn, canSync, canSignOut, busy;
  const SyncMsg(this.text, this.state,
      {this.canSignIn = false, this.canSync = false, this.canSignOut = false, this.busy = false});
}

String _ago(Duration d) {
  final secs = d.inSeconds;
  if (secs < 30) return 'just now';
  final m = secs ~/ 60;
  if (m < 60) return '${m < 1 ? 1 : m} min ago';
  final h = secs ~/ 3600;
  if (h < 48) return '$h h ago';
  return '${secs ~/ 86400} d ago';
}

SyncMsg syncMessage(SyncInfo s, DateTime now) {
  if (!s.configured) {
    return const SyncMsg('Sync is off. Build the app with GOOGLE_SERVER_CLIENT_ID to turn it on.', 'off');
  }
  if (s.signingIn) {
    return const SyncMsg('Waiting for Google sign-in…', 'busy', busy: true);
  }
  if (!s.signedIn) return const SyncMsg('Not signed in.', 'off', canSignIn: true);
  if (s.syncing) {
    return const SyncMsg('Syncing…', 'busy', canSync: true, canSignOut: true, busy: true);
  }
  if (s.error != null) {
    return SyncMsg('Sync problem: ${s.error}', 'error', canSync: true, canSignOut: true);
  }
  final last = s.lastSyncedAt;
  return SyncMsg(
    last == null ? 'Signed in. Not synced yet.' : 'Synced ${_ago(now.difference(last))}',
    last == null ? 'off' : 'ok',
    canSync: true, canSignOut: true,
  );
}
