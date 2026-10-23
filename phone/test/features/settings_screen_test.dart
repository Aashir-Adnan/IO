import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/core/secure_store.dart';
import 'package:io_phone/features/settings/settings_screen.dart';
import 'package:io_phone/features/settings/sync_message.dart';
import 'package:io_phone/sync/sync_manager.dart';

class FakeKv implements KeyValueStore {
  @override
  Future<void> write({required String key, required String? value}) async {}
  @override
  Future<String?> read({required String key}) async => null;
}

class FakeSync extends ChangeNotifier implements SyncState {
  @override
  SyncInfo info;
  final calls = <String>[];
  FakeSync(this.info);
  @override
  Future<void> signIn() async => calls.add('in');
  @override
  Future<void> signOut() async => calls.add('out');
  @override
  Future<void> syncNow() async => calls.add('now');
}

SyncInfo state({bool configured = true, bool signedIn = false, bool syncing = false,
        DateTime? last, String? error}) =>
    SyncInfo(configured: configured, signedIn: signedIn, syncing: syncing,
        signingIn: false, lastSyncedAt: last, error: error);

Widget host(SyncState s) => MaterialApp(
    home: SettingsScreen(store: SecureStore(FakeKv()), sync: s, onKeyRemoved: () {}));

void main() {
  testWidgets('signed out: offers Google sign-in and nothing else', (tester) async {
    final s = FakeSync(state());
    await tester.pumpWidget(host(s));
    expect(find.text('Account & sync'), findsOneWidget);
    expect(find.text('Not signed in.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('sync-signin')));
    expect(s.calls, ['in']);
    expect(find.byKey(const Key('sync-now')), findsNothing);
    expect(find.byKey(const Key('sync-signout')), findsNothing);
  });

  testWidgets('signed in: shows freshness and offers Sync now and Sign out', (tester) async {
    final s = FakeSync(state(signedIn: true, last: DateTime.now().toUtc()));
    await tester.pumpWidget(host(s));
    expect(find.text('Synced just now'), findsOneWidget);
    await tester.tap(find.byKey(const Key('sync-now')));
    await tester.tap(find.byKey(const Key('sync-signout')));
    expect(s.calls, ['now', 'out']);
  });

  testWidgets('a sync problem is shown and the retry button still works', (tester) async {
    final s = FakeSync(state(signedIn: true, error: 'quota exceeded'));
    await tester.pumpWidget(host(s));
    expect(find.text('Sync problem: quota exceeded'), findsOneWidget);
    expect(find.byKey(const Key('sync-now')), findsOneWidget);
  });

  testWidgets('while syncing the Sync now button is disabled', (tester) async {
    final s = FakeSync(state(signedIn: true, syncing: true));
    await tester.pumpWidget(host(s));
    expect(tester.widget<TextButton>(find.byKey(const Key('sync-now'))).onPressed, isNull);
  });

  testWidgets('not configured: explains instead of offering a dead button', (tester) async {
    await tester.pumpWidget(host(FakeSync(state(configured: false))));
    expect(find.textContaining('GOOGLE_SERVER_CLIENT_ID'), findsOneWidget);
    expect(find.byKey(const Key('sync-signin')), findsNothing);
  });

  testWidgets('updates when the sync state changes', (tester) async {
    final s = FakeSync(state());
    await tester.pumpWidget(host(s));
    s.info = state(signedIn: true, last: DateTime.now().toUtc());
    s.notifyListeners();
    await tester.pump();
    expect(find.text('Synced just now'), findsOneWidget);
  });
}
