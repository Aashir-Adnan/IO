import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/features/settings/sync_message.dart';

final now = DateTime.utc(2026, 9, 22, 12);

SyncInfo info({
  bool configured = true, bool signedIn = true, bool syncing = false,
  bool signingIn = false, DateTime? last, String? error,
}) =>
    SyncInfo(configured: configured, signedIn: signedIn, syncing: syncing,
        signingIn: signingIn, lastSyncedAt: last, error: error);

void main() {
  test('not configured explains how to turn it on', () {
    final m = syncMessage(info(configured: false), now);
    expect(m.text, contains('GOOGLE_SERVER_CLIENT_ID'));
    expect(m.state, 'off');
    expect(m.canSignIn || m.canSync || m.canSignOut, isFalse);
  });

  test('signed out offers sign in only', () {
    final m = syncMessage(info(signedIn: false), now);
    expect(m.text, 'Not signed in.');
    expect(m.canSignIn, isTrue);
    expect(m.canSync || m.canSignOut, isFalse);
  });

  test('signing in is busy and offers nothing', () {
    final m = syncMessage(info(signedIn: false, signingIn: true), now);
    expect(m.text, contains('Google'));
    expect(m.busy, isTrue);
    expect(m.canSignIn, isFalse);
  });

  test('syncing is busy', () {
    final m = syncMessage(info(syncing: true), now);
    expect(m.text, 'Syncing…');
    expect(m.state, 'busy');
  });

  test('last synced is relative', () {
    String t(Duration ago) => syncMessage(info(last: now.subtract(ago)), now).text;
    expect(t(const Duration(seconds: 5)), 'Synced just now');
    expect(t(const Duration(seconds: 90)), 'Synced 1 min ago');
    expect(t(const Duration(minutes: 10)), 'Synced 10 min ago');
    expect(t(const Duration(hours: 2)), 'Synced 2 h ago');
    expect(t(const Duration(days: 2, hours: 5)), 'Synced 2 d ago');
    final m = syncMessage(info(last: now.subtract(const Duration(minutes: 3))), now);
    expect(m.state, 'ok');
    expect(m.canSync && m.canSignOut, isTrue);
  });

  test('signed in but never synced', () {
    expect(syncMessage(info(), now).text, 'Signed in. Not synced yet.');
  });

  test('an error is shown and still retryable', () {
    final m = syncMessage(info(error: 'quota exceeded', last: now), now);
    expect(m.text, 'Sync problem: quota exceeded');
    expect(m.state, 'error');
    expect(m.canSync, isTrue);
  });
}
