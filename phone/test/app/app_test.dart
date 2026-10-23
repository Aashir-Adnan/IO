import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:io_phone/app.dart';
import 'package:io_phone/core/anthropic_client.dart';
import 'package:io_phone/core/chat_store.dart';
import 'package:io_phone/core/secure_store.dart';
import 'package:io_phone/features/chat/chat_state.dart';
import 'package:io_phone/features/settings/sync_message.dart';
import 'package:io_phone/features/tasks/tasks_state.dart';
import 'package:io_phone/sync/sync_manager.dart';

class FakeKv implements KeyValueStore {
  final data = <String, String>{};
  @override
  Future<void> write({required String key, required String? value}) async {
    if (value == null) { data.remove(key); } else { data[key] = value; }
  }
  @override
  Future<String?> read({required String key}) async => data[key];
}

class FakeChat extends ChangeNotifier implements ChatState {
  @override
  List<ChatMessage> messages = [];
  @override
  bool busy = false;
  @override
  Future<void> send(String text) async {}
  @override
  Future<void> newChat() async {}
}

class FakeTasks extends ChangeNotifier implements TasksState {
  @override
  List<Map<String, Object?>> tasks = [];
  var loads = 0;
  @override
  Future<void> load() async => loads++;
  @override
  Future<void> complete(int id) async {}
}

class FakeSync extends ChangeNotifier implements SyncState {
  @override
  SyncInfo get info => const SyncInfo(
      configured: true, signedIn: false, syncing: false, signingIn: false);
  @override
  Future<void> signIn() async {}
  @override
  Future<void> signOut() async {}
  @override
  Future<void> syncNow() async {}
}

AppServices services({String? key, int validateStatus = 200, FakeTasks? tasks}) {
  final kv = FakeKv();
  if (key != null) kv.data['anthropic_api_key'] = key;
  return AppServices(
    secureStore: SecureStore(kv),
    client: AnthropicClient(http: MockClient((r) async => http.Response('{}', validateStatus))),
    chat: FakeChat(),
    tasks: tasks ?? FakeTasks(),
    sync: FakeSync(),
    dispose: () async {},
  );
}

Widget app(AppServices s) => IoApp(bootstrap: () async => s);

void main() {
  testWidgets('without a stored key the first screen is the API key prompt', (tester) async {
    await tester.pumpWidget(app(services()));
    await tester.pumpAndSettle();
    expect(find.text('Enter your Anthropic API key'), findsOneWidget);
  });

  testWidgets('a valid key moves on to the home screen', (tester) async {
    final s = services();
    await tester.pumpWidget(app(s));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'sk-ant-good');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(await s.secureStore.getApiKey(), 'sk-ant-good');
  });

  testWidgets('with a key it opens straight on chat, with three destinations', (tester) async {
    await tester.pumpWidget(app(services(key: 'sk-ant-x')));
    await tester.pumpAndSettle();
    expect(find.text('Tell me something to remember, or ask what I know.'), findsOneWidget);
    for (final label in ['Chat', 'Tasks', 'Settings']) {
      expect(find.descendant(of: find.byType(NavigationBar), matching: find.text(label)), findsOneWidget);
    }
  });

  testWidgets('opening Tasks refreshes the list (a chat turn may have added one)', (tester) async {
    final tasks = FakeTasks();
    await tester.pumpWidget(app(services(key: 'sk-ant-x', tasks: tasks)));
    await tester.pumpAndSettle();
    final before = tasks.loads;
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Tasks')));
    await tester.pumpAndSettle();
    expect(tasks.loads, greaterThan(before));
    expect(find.text('Nothing pending'), findsOneWidget);
  });

  testWidgets('removing the key from Settings returns to the key prompt', (tester) async {
    final s = services(key: 'sk-ant-x');
    await tester.pumpWidget(app(s));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Settings')));
    await tester.pumpAndSettle();
    expect(find.textContaining('API key saved'), findsOneWidget);
    await tester.tap(find.byKey(const Key('remove-key')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Remove'));   // confirm dialog
    await tester.pumpAndSettle();
    expect(find.text('Enter your Anthropic API key'), findsOneWidget);
    expect(await s.secureStore.getApiKey(), isNull);
  });
}
