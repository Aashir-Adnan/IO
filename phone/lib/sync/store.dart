import 'dart:io';

/// Where sync files live. Paths are relative, POSIX-style, e.g.
/// `dev-<device>/batch-00000042.json.gz`. Mirrors io_assistant/sync/store.py.
abstract class SyncStore {
  Future<void> put(String path, List<int> data);
  Future<List<int>> get(String path);
  Future<List<String>> list(String prefix);
  Future<void> delete(String path);
}

/// A SyncStore backed by a directory (tests, or any synced folder).
class FolderStore implements SyncStore {
  final Directory root;
  FolderStore(this.root);

  File _f(String path) => File('${root.path}/$path');

  @override
  Future<void> put(String path, List<int> data) async {
    final f = _f(path);
    await f.parent.create(recursive: true);
    final tmp = File('${f.path}.part'); // never expose a half-written file
    await tmp.writeAsBytes(data, flush: true);
    await tmp.rename(f.path);
  }

  @override
  Future<List<int>> get(String path) => _f(path).readAsBytes();

  @override
  Future<List<String>> list(String prefix) async {
    if (!await root.exists()) return [];
    final base = root.path.replaceAll('\\', '/');
    final out = <String>[];
    await for (final e in root.list(recursive: true)) {
      if (e is! File || e.path.endsWith('.part')) continue;
      final rel = e.path.replaceAll('\\', '/').substring(base.length + 1);
      if (rel.startsWith(prefix)) out.add(rel);
    }
    out.sort();
    return out;
  }

  @override
  Future<void> delete(String path) async {
    final f = _f(path);
    if (await f.exists()) await f.delete();
  }
}
