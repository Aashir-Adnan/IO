import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/core/secure_store.dart';

class FakeKv implements KeyValueStore {
  final Map<String, String> data = {};
  @override
  Future<void> write({required String key, required String? value}) async {
    if (value == null) { data.remove(key); } else { data[key] = value; }
  }
  @override
  Future<String?> read({required String key}) async => data[key];
}

void main() {
  test('setApiKey then getApiKey round-trips', () async {
    final kv = FakeKv();
    final store = SecureStore(kv);
    await store.setApiKey('sk-ant-xyz');
    expect(await store.getApiKey(), 'sk-ant-xyz');
  });

  test('getApiKey is null before anything is set', () async {
    final store = SecureStore(FakeKv());
    expect(await store.getApiKey(), isNull);
  });

  test('clearApiKey removes it', () async {
    final kv = FakeKv();
    final store = SecureStore(kv);
    await store.setApiKey('sk-ant-xyz');
    await store.clearApiKey();
    expect(await store.getApiKey(), isNull);
  });
}
