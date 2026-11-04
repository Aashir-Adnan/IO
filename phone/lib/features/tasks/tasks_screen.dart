import 'package:flutter/material.dart';
import 'tasks_state.dart';

const _groups = [
  ('overdue', 'Overdue'),
  ('today', 'Today'),
  ('upcoming', 'Upcoming'),
  ('none', 'Someday'),
];

class TasksScreen extends StatefulWidget {
  final TasksState state;
  const TasksScreen({super.key, required this.state});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  @override
  void initState() {
    super.initState();
    widget.state.load();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Tasks')),
      body: ListenableBuilder(
        listenable: widget.state,
        builder: (context, _) {
          final tasks = widget.state.tasks;
          if (tasks.isEmpty) {
            return const Center(child: Text('Nothing pending'));
          }
          return RefreshIndicator(
            onRefresh: widget.state.load,
            child: ListView(
              children: [
                for (final (key, label) in _groups) ...[
                  if (tasks.any((t) => t['group'] == key))
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                      child: Text(label,
                          style: Theme.of(context).textTheme.labelLarge?.copyWith(
                              color: key == 'overdue' ? cs.error : cs.onSurfaceVariant)),
                    ),
                  for (final t in tasks.where((t) => t['group'] == key))
                    ListTile(
                      leading: IconButton(
                        key: Key('task-check-${t['id']}'),
                        icon: const Icon(Icons.radio_button_unchecked),
                        onPressed: () => widget.state.complete(t['id'] as int),
                      ),
                      title: Text('${t['title']}'),
                      // the "Today" heading already says it
                      trailing: (t['due_label'] == null || key == 'today')
                          ? null
                          : Text('${t['due_label']}',
                              style: TextStyle(color: key == 'overdue' ? cs.error : null)),
                    ),
                ],
              ],
            ),
          );
        },
      ),
    );
  }
}
