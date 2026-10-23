import 'package:flutter/foundation.dart';
import 'package:sqflite/sqflite.dart';
import '../../core/tasks.dart';
import 'tasks_state.dart';

class TasksController extends ChangeNotifier implements TasksState {
  final Database db;
  final DateTime Function() _clock;
  final VoidCallback? onChanged; // a completion is a write: sync pokes here
  TasksController(this.db, {DateTime Function()? clock, this.onChanged})
      : _clock = clock ?? (() => DateTime.now().toUtc());

  @override
  List<Map<String, Object?>> tasks = [];

  @override
  Future<void> load() async {
    tasks = await pendingTasks(db, _clock());
    notifyListeners();
  }

  @override
  Future<void> complete(int id) async {
    await completeTask(db, id, _clock());
    await load();
    onChanged?.call();
  }
}
