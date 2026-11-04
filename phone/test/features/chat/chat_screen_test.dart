import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/core/chat_store.dart';
import 'package:io_phone/features/chat/chat_screen.dart';
import 'package:io_phone/features/chat/chat_state.dart';

class FakeChat extends ChangeNotifier implements ChatState {
  @override
  List<ChatMessage> messages = [];
  @override
  bool busy = false;
  final sent = <String>[];
  var newChats = 0;
  @override
  Future<void> send(String text) async => sent.add(text);
  @override
  Future<void> newChat() async => newChats++;
}

Widget host(ChatState s) => MaterialApp(home: ChatScreen(state: s));

void main() {
  testWidgets('shows the conversation, user and assistant lines', (tester) async {
    final s = FakeChat()
      ..messages = [
        const ChatMessage(1, 'user', 'what is on today', null),
        const ChatMessage(2, 'assistant', 'Nothing yet.', 'answer'),
      ];
    await tester.pumpWidget(host(s));
    expect(find.text('what is on today'), findsOneWidget);
    expect(find.text('Nothing yet.'), findsOneWidget);
  });

  testWidgets('an empty chat invites the first message', (tester) async {
    await tester.pumpWidget(host(FakeChat()));
    expect(find.textContaining('Tell me something'), findsOneWidget);
  });

  testWidgets('sending passes the text on and clears the field', (tester) async {
    final s = FakeChat();
    await tester.pumpWidget(host(s));
    await tester.enterText(find.byKey(const Key('chat-input')), 'call mum tomorrow');
    await tester.tap(find.byKey(const Key('chat-send')));
    await tester.pump();
    expect(s.sent, ['call mum tomorrow']);
    expect(tester.widget<TextField>(find.byKey(const Key('chat-input'))).controller!.text, isEmpty);
  });

  testWidgets('a blank field sends nothing', (tester) async {
    final s = FakeChat();
    await tester.pumpWidget(host(s));
    await tester.enterText(find.byKey(const Key('chat-input')), '   ');
    await tester.tap(find.byKey(const Key('chat-send')));
    await tester.pump();
    expect(s.sent, isEmpty);
  });

  testWidgets('while a turn runs it says so and the send button is disabled', (tester) async {
    final s = FakeChat()..busy = true;
    await tester.pumpWidget(host(s));
    expect(find.text('Thinking…'), findsOneWidget);
    expect(tester.widget<IconButton>(find.byKey(const Key('chat-send'))).onPressed, isNull);
  });

  testWidgets('new chat button starts a fresh conversation', (tester) async {
    final s = FakeChat();
    await tester.pumpWidget(host(s));
    await tester.tap(find.byKey(const Key('chat-new')));
    expect(s.newChats, 1);
  });

  testWidgets('rebuilds when the state changes', (tester) async {
    final s = FakeChat();
    await tester.pumpWidget(host(s));
    s.messages = [const ChatMessage(1, 'assistant', 'Saved.', 'ack')];
    s.notifyListeners();
    await tester.pump();
    expect(find.text('Saved.'), findsOneWidget);
  });
}
