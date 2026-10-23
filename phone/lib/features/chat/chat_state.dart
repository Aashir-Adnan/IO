import 'package:flutter/foundation.dart';
import '../../core/chat_store.dart';

/// What ChatScreen needs — ChatController implements it; widget tests fake it.
abstract class ChatState implements Listenable {
  List<ChatMessage> get messages;
  bool get busy;
  Future<void> send(String text);
  Future<void> newChat();
}
