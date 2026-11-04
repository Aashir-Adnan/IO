import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:sqflite/sqflite.dart';
import '../features/settings/sync_message.dart';
import 'auth.dart';
import 'engine.dart';
import 'store.dart';

/// What the Settings screen needs — SyncManager implements it; widget tests
/// fake it.
abstract class SyncState implements Listenable {
  SyncInfo get info;
  Future<void> signIn();
  Future<void> signOut();
  Future<void> syncNow();
}

/// Owns memory sync for the running app: who is signed in, the engine, the
/// background loop, and the status the UI shows. Never throws out of
/// sync/sign-in; problems land in [error] (same contract as the desktop's
/// io_assistant/sync/manager.py).
class SyncManager extends ChangeNotifier implements SyncState {
  final Database db;
  final AuthProvider auth;
  final SyncStore Function() storeFactory;
  final Duration interval;
  final bool configured;

  SyncManager({
    required this.db, required this.auth, required this.storeFactory,
    this.interval = const Duration(seconds: 60), this.configured = true,
  });

  bool signedIn = false, syncing = false, signingIn = false;
  DateTime? lastSyncedAt;
  String? error;
  String? _deviceId;
  SyncEngine? _engine;
  Future<void>? _inflight;
  Timer? _timer;

  @override
  SyncInfo get info => SyncInfo(
      configured: configured, signedIn: signedIn, syncing: syncing,
      signingIn: signingIn, lastSyncedAt: lastSyncedAt, error: error);

  /// Valid after [refresh].
  String get deviceId => _deviceId!;

  Future<String> _loadDeviceId() async {
    final rows = await db.query('sync_state', where: 'key = ?', whereArgs: ['device_id']);
    if (rows.isNotEmpty) return (jsonDecode(rows.first['value'] as String) as Map)['v'] as String;
    final rnd = Random.secure();
    final id = List.generate(12, (_) => rnd.nextInt(16).toRadixString(16)).join();
    await db.insert('sync_state', {'key': 'device_id', 'value': jsonEncode({'v': id})});
    return id;
  }

  /// Load the device id and silently restore a previous sign-in.
  Future<void> refresh() async {
    _deviceId ??= await _loadDeviceId();
    try {
      signedIn = configured && await auth.restore();
    } catch (_) {
      signedIn = false;
    }
    notifyListeners();
  }

  @override
  Future<void> signIn() async {
    if (signingIn) return;
    signingIn = true;
    error = null;
    notifyListeners();
    try {
      _deviceId ??= await _loadDeviceId();
      await auth.signIn();
      signedIn = true;
    } catch (e) {
      error = '$e';
    } finally {
      signingIn = false;
      notifyListeners();
    }
    if (signedIn) await syncNow();
  }

  @override
  Future<void> signOut() async {
    try {
      await auth.signOut();
    } catch (_) {/* signed out locally regardless */}
    signedIn = false;
    error = null;
    _engine = null;
    notifyListeners();
  }

  @override
  Future<void> syncNow() {
    // one sync at a time: a second caller joins the one in flight
    return _inflight ??= _run().whenComplete(() => _inflight = null);
  }

  Future<void> _run() async {
    if (!signedIn) {
      error = 'Not signed in — sign in with Google in Settings → Account.';
      notifyListeners();
      return;
    }
    syncing = true;
    notifyListeners();
    try {
      _deviceId ??= await _loadDeviceId();
      final engine = _engine ??= SyncEngine(db, storeFactory(), _deviceId!);
      await engine.sync();
      lastSyncedAt = DateTime.now().toUtc();
      error = null;
    } catch (e) {
      error = '$e';
      _engine = null; // rebuild the store next time (a fresh token, a new path)
    } finally {
      syncing = false;
      notifyListeners();
    }
  }

  /// A local write happened: sync soon instead of waiting for the timer.
  void poke() {
    if (signedIn && !syncing) syncNow();
  }

  /// Completes when any in-flight sync has finished.
  Future<void> idle() => _inflight ?? Future.value();

  void start() {
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) {
      if (signedIn && !syncing) syncNow();
    });
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
