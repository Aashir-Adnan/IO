/// Conversations and messages — the phone's counterpart of
/// io_assistant/conversation/store.py. Rows carry sync identity so chats sync
/// across devices with everything else.
library;

import 'package:sqflite/sqflite.dart';
import 'db.dart';

class ChatMessage {
  final int id;
  final String role; // "user" | "assistant"
  final String text;
  final String? kind; // ack | answer | gate | unknown | error
  const ChatMessage(this.id, this.role, this.text, this.kind);
}

class ChatStore {
  final Database db;
  final DateTime Function() _clock;
  ChatStore(this.db, {DateTime Function()? clock})
      : _clock = clock ?? (() => DateTime.now().toUtc());

  Future<int> newConversation() {
    final iso = _clock().toIso8601String();
    return db.insert('conversations', {
      'started_at': iso, 'last_at': iso, 'sync_id': newSyncId(), 'updated_at': iso,
    });
  }

  /// The most recently active conversation, or a new one.
  Future<int> ensureActive() async {
    final rows = await db.query('conversations',
        columns: ['id'], orderBy: 'last_at DESC, id DESC', limit: 1);
    return rows.isEmpty ? newConversation() : rows.first['id'] as int;
  }

  Future<int> append(int conversationId, String role, String text,
      {String? kind, String? intent}) async {
    final iso = _clock().toIso8601String();
    final id = await db.insert('messages', {
      'conversation_id': conversationId, 'role': role, 'text': text,
      'kind': kind, 'intent': intent, 'source': 'text',
      'sync_id': newSyncId(), 'created_at': iso, 'updated_at': iso,
    });
    await db.rawUpdate(
      'UPDATE conversations SET last_at = ?, updated_at = ?, '
      'title = COALESCE(title, ?) WHERE id = ?',
      [iso, iso, role == 'user' ? _title(text) : null, conversationId],
    );
    return id;
  }

  static String _title(String text) {
    final t = text.trim().replaceAll(RegExp(r'\s+'), ' ');
    return t.length <= 40 ? t : '${t.substring(0, 40)}…';
  }

  Future<List<ChatMessage>> messages(int conversationId) async {
    final rows = await db.query('messages',
        where: 'conversation_id = ?', whereArgs: [conversationId], orderBy: 'id ASC');
    return [
      for (final r in rows)
        ChatMessage(r['id'] as int, r['role'] as String, r['text'] as String, r['kind'] as String?)
    ];
  }

  /// The recent turns as the planner's "Recent conversation" block, formatted
  /// like io_assistant/conversation/context.py (you:/io:, oldest dropped to
  /// fit). Null when there is nothing yet.
  Future<String?> contextFor(int conversationId, {int turns = 12, int maxChars = 1400}) async {
    final rows = await db.query('messages',
        where: 'conversation_id = ?', whereArgs: [conversationId],
        orderBy: 'id DESC', limit: turns);
    final lines = [
      for (final r in rows.reversed)
        "${r['role'] == 'user' ? 'you' : 'io'}: ${(r['text'] as String).trim()}"
    ];
    while (lines.isNotEmpty && lines.join('\n').length > maxChars) {
      lines.removeAt(0);
    }
    return lines.isEmpty ? null : lines.join('\n');
  }
}
