import 'package:flutter/material.dart';
import '../../core/chat_store.dart';
import 'chat_state.dart';

class ChatScreen extends StatefulWidget {
  final ChatState state;
  const ChatScreen({super.key, required this.state});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();

  void _send() {
    final text = _input.text.trim();
    if (text.isEmpty || widget.state.busy) return;
    _input.clear();
    widget.state.send(text);
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.state,
      builder: (context, _) {
        final s = widget.state;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
        });
        return Scaffold(
          appBar: AppBar(
            title: const Text('IO'),
            actions: [
              IconButton(
                key: const Key('chat-new'),
                tooltip: 'New chat',
                icon: const Icon(Icons.add_comment_outlined),
                onPressed: s.newChat,
              ),
            ],
          ),
          body: Column(
            children: [
              Expanded(
                child: s.messages.isEmpty && !s.busy
                    ? const Center(
                        child: Padding(
                          padding: EdgeInsets.all(32),
                          child: Text('Tell me something to remember, or ask what I know.',
                              textAlign: TextAlign.center),
                        ),
                      )
                    : ListView(
                        controller: _scroll,
                        padding: const EdgeInsets.all(12),
                        children: [
                          for (final m in s.messages) _Bubble(m),
                          if (s.busy) const _Thinking(),
                        ],
                      ),
              ),
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 4, 4, 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          key: const Key('chat-input'),
                          controller: _input,
                          minLines: 1,
                          maxLines: 5,
                          textInputAction: TextInputAction.send,
                          onSubmitted: (_) => _send(),
                          decoration: const InputDecoration(hintText: 'Ask IO anything'),
                        ),
                      ),
                      IconButton(
                        key: const Key('chat-send'),
                        icon: const Icon(Icons.arrow_upward),
                        onPressed: s.busy ? null : _send,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _Bubble extends StatelessWidget {
  final ChatMessage m;
  const _Bubble(this.m);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final mine = m.role == 'user';
    final problem = m.kind == 'error' || m.kind == 'gate';
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.8),
        decoration: BoxDecoration(
          color: mine
              ? cs.primaryContainer
              : problem ? cs.errorContainer : cs.surfaceContainerHigh,
          borderRadius: BorderRadius.circular(18),
        ),
        child: SelectableText(m.text),
      ),
    );
  }
}

class _Thinking extends StatelessWidget {
  const _Thinking();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.symmetric(vertical: 8, horizontal: 4),
        child: Text('Thinking…', style: TextStyle(fontStyle: FontStyle.italic)),
      );
}
