import 'package:flutter/foundation.dart';
import '../../core/chat_store.dart';
import '../../core/orchestrator.dart';
import 'chat_state.dart';

/// The chat screen's state: the visible messages and whether a turn is in
/// flight. All logic lives in ChatStore/Orchestrator; this only sequences it.
class ChatController extends ChangeNotifier implements ChatState {
  final ChatStore store;
  final Orchestrator orchestrator;

  /// Called after a turn finishes (it may have written memories) — sync pokes here.
  final VoidCallback? onTurnDone;
  ChatController(this.store, this.orchestrator, {this.onTurnDone});

  @override
  List<ChatMessage> messages = [];
  @override
  bool busy = false;
  int? _conversationId;

  Future<void> load() async {
    _conversationId = await store.ensureActive();
    messages = await store.messages(_conversationId!);
    notifyListeners();
  }

  @override
  Future<void> send(String text) async {
    final t = text.trim();
    if (t.isEmpty || busy) return;
    busy = true;
    notifyListeners(); // the spinner shows the instant the user hits send
    final id = _conversationId ??= await store.ensureActive();
    // context is read before this turn's own line is appended
    final context = await store.contextFor(id);
    await store.append(id, 'user', t);
    messages = await store.messages(id);
    notifyListeners();
    try {
      final r = await orchestrator.handle(t, context: context);
      await store.append(id, 'assistant', r.message, kind: r.kind);
    } finally {
      busy = false;
      messages = await store.messages(id);
      notifyListeners();
      onTurnDone?.call();
    }
  }

  @override
  Future<void> newChat() async {
    _conversationId = await store.newConversation();
    messages = [];
    notifyListeners();
  }
}
