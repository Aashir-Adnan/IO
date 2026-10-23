/// SyncStore over the Google Drive appDataFolder (REST, no SDK): a hidden,
/// per-app area that the `drive.appdata` scope can reach — and nothing else
/// in the user's Drive. appData has no directories, so
/// `dev-A/batch-00000001.json.gz` is stored as `dev-A__batch-00000001.json.gz`
/// (the same mapping as io_assistant/sync/gdrive.py).
library;

import 'dart:convert';
import 'package:http/http.dart' as http;
import 'store.dart';

class DriveError implements Exception {
  final int status;
  final String message;
  DriveError(this.status, this.message);
  @override
  String toString() => 'Drive error $status: $message';
}

class GoogleDriveStore implements SyncStore {
  static const _api = 'https://www.googleapis.com/drive/v3/files';
  static const _upload = 'https://www.googleapis.com/upload/drive/v3/files';
  static const _sep = '__';

  final http.Client _http;
  final Future<String> Function() _token;
  final int pageSize;
  final _known = <String, String>{}; // name -> id, for files we just created

  GoogleDriveStore(this._http, this._token, {this.pageSize = 1000});

  static String _name(String path) => path.replaceFirst('/', _sep);
  static String _path(String name) => name.replaceFirst(_sep, '/');

  Future<Map<String, String>> _auth([Map<String, String> extra = const {}]) async =>
      {'authorization': 'Bearer ${await _token()}', ...extra};

  http.Response _check(http.Response r, {Set<int> ok = const {200, 204}}) {
    if (!ok.contains(r.statusCode)) throw DriveError(r.statusCode, utf8.decode(r.bodyBytes, allowMalformed: true));
    return r;
  }

  Future<Map<String, String>> _index() async {
    final out = <String, String>{};
    String? pageToken;
    do {
      final uri = Uri.parse(_api).replace(queryParameters: {
        'spaces': 'appDataFolder',
        'fields': 'nextPageToken, files(id, name)',
        'pageSize': '$pageSize',
        'pageToken': ?pageToken,
      });
      final r = _check(await _http.get(uri, headers: await _auth()));
      final body = jsonDecode(utf8.decode(r.bodyBytes)) as Map;
      for (final f in (body['files'] as List? ?? const [])) {
        out[f['name'] as String] = f['id'] as String;
      }
      pageToken = body['nextPageToken'] as String?;
    } while (pageToken != null);
    return {..._known, ...out};
  }

  Future<String?> _id(String name) async => _known[name] ?? (await _index())[name];

  @override
  Future<void> put(String path, List<int> data) async {
    final name = _name(path);
    final id = await _id(name);
    if (id != null) { // a retried push: overwrite, don't duplicate
      _check(await _http.patch(
        Uri.parse('$_upload/$id').replace(queryParameters: {'uploadType': 'media'}),
        headers: await _auth({'content-type': 'application/gzip'}),
        body: data,
      ));
      return;
    }
    const boundary = 'io_sync_boundary_7f3a9c';
    final meta = jsonEncode({'name': name, 'parents': ['appDataFolder']});
    final body = <int>[
      ...utf8.encode('--$boundary\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n$meta\r\n'
          '--$boundary\r\nContent-Type: application/gzip\r\n\r\n'),
      ...data,
      ...utf8.encode('\r\n--$boundary--'),
    ];
    final r = _check(await _http.post(
      Uri.parse(_upload).replace(queryParameters: {'uploadType': 'multipart', 'fields': 'id'}),
      headers: await _auth({'content-type': 'multipart/related; boundary=$boundary'}),
      body: body,
    ));
    _known[name] = (jsonDecode(utf8.decode(r.bodyBytes)) as Map)['id'] as String;
  }

  @override
  Future<List<int>> get(String path) async {
    final id = await _id(_name(path));
    if (id == null) throw DriveError(404, '$path not found');
    final r = _check(await _http.get(
        Uri.parse('$_api/$id').replace(queryParameters: {'alt': 'media'}),
        headers: await _auth()));
    return r.bodyBytes;
  }

  @override
  Future<List<String>> list(String prefix) async =>
      ((await _index()).keys.map(_path).where((p) => p.startsWith(prefix))).toList()..sort();

  @override
  Future<void> delete(String path) async {
    final name = _name(path);
    final id = await _id(name);
    if (id == null) return;
    final r = await _http.delete(Uri.parse('$_api/$id'), headers: await _auth());
    _check(r, ok: const {200, 204, 404});
    _known.remove(name);
  }
}
