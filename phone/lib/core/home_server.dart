/// The user's own desktop IO — reached over their private network (Tailscale
/// or similar) — which the phone borrows for web answers. Both values live in
/// the platform keystore; the token is a credential.
library;

import 'secure_store.dart';

class HomeServer {
  final String baseUrl;
  final String token;
  const HomeServer(this.baseUrl, this.token);
}

class HomeServerStore {
  static const _urlKey = 'home_server_url';
  static const _tokenKey = 'home_server_token';
  final KeyValueStore _kv;
  HomeServerStore([KeyValueStore? kv]) : _kv = kv ?? PlatformKeyValueStore();

  /// "100.64.0.2:8765" -> "http://100.64.0.2:8765" (a private-network host is
  /// plain http); trailing slashes dropped; blank -> empty.
  static String normalizeUrl(String raw) {
    var u = raw.trim();
    if (u.isEmpty) return '';
    if (!RegExp(r'^[a-z][a-z0-9+.-]*://', caseSensitive: false).hasMatch(u)) u = 'http://$u';
    return u.replaceAll(RegExp(r'/+$'), '');
  }

  Future<HomeServer?> load() async {
    final url = await _kv.read(key: _urlKey);
    if (url == null || url.isEmpty) return null;
    return HomeServer(url, await _kv.read(key: _tokenKey) ?? '');
  }

  Future<void> save(HomeServer h) async {
    final url = normalizeUrl(h.baseUrl);
    if (url.isEmpty) return clear();
    await _kv.write(key: _urlKey, value: url);
    await _kv.write(key: _tokenKey, value: h.token.trim());
  }

  Future<void> clear() async {
    await _kv.write(key: _urlKey, value: null);
    await _kv.write(key: _tokenKey, value: null);
  }
}
