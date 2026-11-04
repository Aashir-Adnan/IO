import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// The subset of FlutterSecureStorage's API SecureStore needs — lets tests
/// inject a fake instead of touching the real platform keystore.
abstract class KeyValueStore {
  Future<void> write({required String key, required String? value});
  Future<String?> read({required String key});
}

class PlatformKeyValueStore implements KeyValueStore {
  final FlutterSecureStorage _fs;
  PlatformKeyValueStore([FlutterSecureStorage? fs])
      : _fs = fs ?? const FlutterSecureStorage();

  @override
  Future<void> write({required String key, required String? value}) =>
      value == null ? _fs.delete(key: key) : _fs.write(key: key, value: value);

  @override
  Future<String?> read({required String key}) => _fs.read(key: key);
}

/// The Anthropic API key, in the OS keystore — never plain storage, never
/// logged. See rules/local-first.md and the phone-app-design spec §"API key
/// on-device".
class SecureStore {
  static const _apiKeyName = 'anthropic_api_key';
  final KeyValueStore _kv;
  SecureStore([KeyValueStore? kv]) : _kv = kv ?? PlatformKeyValueStore();

  Future<void> setApiKey(String key) => _kv.write(key: _apiKeyName, value: key);
  Future<String?> getApiKey() => _kv.read(key: _apiKeyName);
  Future<void> clearApiKey() => _kv.write(key: _apiKeyName, value: null);
}
