/// The phone's local memory store: a SQLite mirror of the synced subset of
/// io_assistant/db/models.py + migration 0010's sync bookkeeping. Local
/// integer ids never leave the device (see sync's codec); `sync_id`/
/// `synced_at`/`updated_at` on every synced table match the Postgres shape
/// exactly, column for column, so the sync wire protocol needs no per-device
/// translation. No `embedding` column anywhere — see the phone-app design
/// spec §"No on-device embedder".
library;

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

const _uuid = Uuid();
String newSyncId() => _uuid.v4();

/// Tables with sync_id/synced_at/updated_at/created_at — an entity or record.
const syncedTables = [
  'utterances', 'people', 'places', 'items', 'occasions',
  'conversations', 'collections', 'records', 'messages',
];

/// Affiliation tables: identified by the pair of parent ids, synced_at only.
const linkTables = [
  'record_people', 'record_places', 'record_items',
  'record_occasions', 'occasion_people',
];

const _createStatements = <String>[
  '''CREATE TABLE utterances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    transcription_confidence REAL,
    resolved_intent TEXT,
    marker TEXT,
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT,
    aliases TEXT NOT NULL DEFAULT '[]',
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    aliases TEXT NOT NULL DEFAULT '[]',
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE occasions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT,
    recurrence_rule TEXT,
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    started_at TEXT NOT NULL,
    last_at TEXT NOT NULL,
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    domain TEXT,
    title TEXT NOT NULL,
    body TEXT,
    occurred_at TEXT,
    due_at TEXT,
    status TEXT,
    completed_at TEXT,
    recurrence_rule TEXT,
    assigned_by_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    attributes TEXT NOT NULL DEFAULT '{}',
    source_utterance_id INTEGER NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind_slug TEXT NOT NULL UNIQUE,
    item_noun TEXT,
    synonyms TEXT NOT NULL DEFAULT '[]',
    field_hint TEXT NOT NULL DEFAULT '{}',
    example_record_id INTEGER REFERENCES records(id) ON DELETE SET NULL,
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT,
    intent TEXT,
    source TEXT NOT NULL DEFAULT 'text',
    utterance_id INTEGER REFERENCES utterances(id) ON DELETE SET NULL,
    audio_ms INTEGER,
    sync_id TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''',
  '''CREATE TABLE record_people (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    role TEXT,
    synced_at TEXT,
    PRIMARY KEY (record_id, person_id)
  )''',
  '''CREATE TABLE record_places (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    role TEXT,
    synced_at TEXT,
    PRIMARY KEY (record_id, place_id)
  )''',
  '''CREATE TABLE record_items (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    role TEXT,
    synced_at TEXT,
    PRIMARY KEY (record_id, item_id)
  )''',
  '''CREATE TABLE record_occasions (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    occasion_id INTEGER NOT NULL REFERENCES occasions(id) ON DELETE CASCADE,
    role TEXT,
    synced_at TEXT,
    PRIMARY KEY (record_id, occasion_id)
  )''',
  '''CREATE TABLE occasion_people (
    occasion_id INTEGER NOT NULL REFERENCES occasions(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    role TEXT,
    synced_at TEXT,
    PRIMARY KEY (occasion_id, person_id)
  )''',
  '''CREATE TABLE sync_tombstones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    sync_id TEXT NOT NULL,
    merged_into TEXT,
    deleted_at TEXT NOT NULL,
    synced_at TEXT,
    UNIQUE (table_name, sync_id)
  )''',
  '''CREATE TABLE sync_aliases (
    alias TEXT PRIMARY KEY,
    canonical TEXT NOT NULL
  )''',
  '''CREATE TABLE sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
  )''',
];

Future<Database> openIoDatabase({String? path, bool inMemory = false}) async {
  final dbPath = inMemory ? inMemoryDatabasePath : (path ?? await _defaultPath());
  return openDatabase(
    dbPath,
    version: 1,
    onConfigure: (db) async => db.execute('PRAGMA foreign_keys = ON'),
    onCreate: (db, version) async {
      for (final stmt in _createStatements) {
        await db.execute(stmt);
      }
    },
  );
}

Future<String> _defaultPath() async {
  final dir = await getDatabasesPath();
  return p.join(dir, 'io.db');
}
