import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:io_phone/sync/drive_store.dart';

/// A just-enough Drive v3 `appDataFolder`: list (paged), multipart create,
/// media update, media download, delete — and it checks auth on every call.
class FakeDrive {
  final files = <String, (String, List<int>)>{}; // id -> (name, bytes)
  final requests = <String>[];
  var n = 0;
  String? lastParents;

  MockClient client({int status = 200}) => MockClient((req) async {
        requests.add('${req.method} ${req.url.path}${req.url.hasQuery ? '?${req.url.query}' : ''}');
        if (req.headers['authorization'] != 'Bearer tok') return http.Response('no', 401);
        final path = req.url.path;
        if (req.method == 'GET' && path == '/drive/v3/files') {
          expect(req.url.queryParameters['spaces'], 'appDataFolder');
          final ids = files.keys.toList()..sort();
          final size = int.parse(req.url.queryParameters['pageSize']!);
          final start = int.parse(req.url.queryParameters['pageToken'] ?? '0');
          final page = ids.skip(start).take(size).toList();
          final next = start + size < ids.length ? '${start + size}' : null;
          return _json({
            'files': [for (final i in page) {'id': i, 'name': files[i]!.$1}],
            if (next != null) 'nextPageToken': next,
          });
        }
        if (req.method == 'POST' && path == '/upload/drive/v3/files') {
          expect(req.url.queryParameters['uploadType'], 'multipart');
          final raw = latin1.decode(req.bodyBytes);
          final boundary = RegExp(r'boundary=(.+)$').firstMatch(req.headers['content-type']!)!.group(1)!;
          final parts = raw.split('--$boundary').where((p) => p.contains('\r\n\r\n')).toList();
          final meta = jsonDecode(parts[0].split('\r\n\r\n')[1].trim()) as Map;
          final body = parts[1].substring(parts[1].indexOf('\r\n\r\n') + 4);
          final media = latin1.encode(body.substring(0, body.length - 2)); // drop trailing CRLF
          lastParents = (meta['parents'] as List).join(',');
          final id = 'id${++n}';
          files[id] = (meta['name'] as String, media);
          return _json({'id': id});
        }
        final m = RegExp(r'^/(?:upload/)?drive/v3/files/(.+)$').firstMatch(path);
        if (m != null) {
          final id = m.group(1)!;
          if (!files.containsKey(id)) return http.Response('{}', 404);
          if (req.method == 'PATCH') {
            files[id] = (files[id]!.$1, req.bodyBytes);
            return _json({'id': id});
          }
          if (req.method == 'GET') {
            expect(req.url.queryParameters['alt'], 'media');
            return http.Response.bytes(files[id]!.$2, 200);
          }
          if (req.method == 'DELETE') {
            files.remove(id);
            return http.Response('', 204);
          }
        }
        return http.Response('unexpected ${req.method} $path', 500);
      });

  http.Response _json(Map o) => http.Response.bytes(utf8.encode(jsonEncode(o)), 200,
      headers: {'content-type': 'application/json'});
}

GoogleDriveStore store(FakeDrive d, {int pageSize = 1000}) =>
    GoogleDriveStore(d.client(), () async => 'tok', pageSize: pageSize);

void main() {
  test('paths are flattened into appData names under the appDataFolder parent', () async {
    final d = FakeDrive();
    await store(d).put('dev-A/batch-00000001.json.gz', [1, 2, 3]);
    expect(d.files.values.single.$1, 'dev-A__batch-00000001.json.gz');
    expect(d.lastParents, 'appDataFolder');
  });

  test('binary content survives the round trip, including bytes that are not UTF-8', () async {
    final d = FakeDrive();
    final s = store(d);
    final bytes = List<int>.generate(256, (i) => i); // every byte value, like gzip output
    await s.put('dev-A/x', bytes);
    expect(await s.get('dev-A/x'), bytes);
  });

  test('list filters by prefix and follows pages', () async {
    final d = FakeDrive();
    final s = store(d, pageSize: 2);
    for (final p in ['dev-A/batch-00000001.json.gz', 'dev-A/batch-00000002.json.gz',
      'dev-B/snapshot-00000005.json.gz', 'other/readme']) {
      await s.put(p, [0]);
    }
    expect(await s.list('dev-'), ['dev-A/batch-00000001.json.gz', 'dev-A/batch-00000002.json.gz',
      'dev-B/snapshot-00000005.json.gz']);
    expect(await s.list('dev-A/'), ['dev-A/batch-00000001.json.gz', 'dev-A/batch-00000002.json.gz']);
  });

  test('putting the same path twice updates in place instead of duplicating', () async {
    final d = FakeDrive();
    final s = store(d);
    await s.put('dev-A/x', [1]);
    await s.put('dev-A/x', [2]);
    expect(d.files.length, 1);
    expect(await s.get('dev-A/x'), [2]);
  });

  test('delete removes the file and ignores one that is already gone', () async {
    final d = FakeDrive();
    final s = store(d);
    await s.put('dev-A/x', [1]);
    await s.delete('dev-A/x');
    await s.delete('dev-A/x');
    expect(await s.list('dev-'), isEmpty);
  });

  test('a missing file raises a clear error', () async {
    expect(() => store(FakeDrive()).get('dev-A/nope'), throwsA(isA<DriveError>()));
  });

  test('every call carries the bearer token; a 401 surfaces as DriveError(401)', () async {
    final d = FakeDrive();
    final s = GoogleDriveStore(d.client(), () async => 'stale');
    await expectLater(s.list('dev-'), throwsA(isA<DriveError>().having((e) => e.status, 'status', 401)));
  });
}
