import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/features/tasks/tasks_screen.dart';
import 'package:io_phone/features/tasks/tasks_state.dart';

class FakeTasks extends ChangeNotifier implements TasksState {
  @override
  List<Map<String, Object?>> tasks = [];
  final completed = <int>[];
  var loads = 0;
  @override
  Future<void> load() async => loads++;
  @override
  Future<void> complete(int id) async => completed.add(id);
}

Map<String, Object?> t(int id, String title, String group, String? label) =>
    {'id': id, 'title': title, 'group': group, 'due_label': label};

Widget host(TasksState s) => MaterialApp(home: TasksScreen(state: s));

void main() {
  testWidgets('groups tasks under headings and marks overdue ones', (tester) async {
    final s = FakeTasks()
      ..tasks = [
        t(1, 'Pay rent', 'overdue', '3 days ago'),
        t(2, 'Submit report', 'today', 'Today'),
        t(3, 'Read the lease', 'none', null),
      ];
    await tester.pumpWidget(host(s));
    for (final h in ['Overdue', 'Today', 'Someday']) {
      expect(find.text(h), findsOneWidget);
    }
    expect(find.text('Upcoming'), findsNothing); // empty groups have no heading
    expect(find.text('Pay rent'), findsOneWidget);
    expect(find.text('3 days ago'), findsOneWidget);
  });

  testWidgets('ticking a task completes it', (tester) async {
    final s = FakeTasks()..tasks = [t(7, 'Pay rent', 'today', 'Today')];
    await tester.pumpWidget(host(s));
    await tester.tap(find.byKey(const Key('task-check-7')));
    expect(s.completed, [7]);
  });

  testWidgets('nothing pending shows an empty state', (tester) async {
    await tester.pumpWidget(host(FakeTasks()));
    expect(find.text('Nothing pending'), findsOneWidget);
  });

  testWidgets('loads on open', (tester) async {
    final s = FakeTasks();
    await tester.pumpWidget(host(s));
    expect(s.loads, 1);
  });
}
