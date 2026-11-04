import 'package:flutter/foundation.dart';

abstract class TasksState implements Listenable {
  List<Map<String, Object?>> get tasks;
  Future<void> load();
  Future<void> complete(int id);
}
