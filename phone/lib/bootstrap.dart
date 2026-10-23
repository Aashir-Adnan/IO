import 'package:http/http.dart' as http;
import 'app.dart';
import 'core/anthropic_client.dart';
import 'core/chat_store.dart';
import 'core/db.dart';
import 'core/llm.dart';
import 'core/orchestrator.dart';
import 'core/secure_store.dart';
import 'features/chat/chat_controller.dart';
import 'features/tasks/tasks_controller.dart';
import 'sync/auth.dart';
import 'sync/drive_store.dart';
import 'sync/sync_manager.dart';

/// The real object graph: on-device SQLite, the keystore, Anthropic over HTTP.
Future<AppServices> bootstrapServices() async {
  final db = await openIoDatabase();
  final secure = SecureStore();
  final client = AnthropicClient(http: http.Client());
  final llm = AnthropicLlm(
    client: client, prompts: AssetPromptSource(), apiKey: secure.getApiKey,
  );
  final auth = GoogleAuthProvider();
  final sync = SyncManager(
    db: db, auth: auth, configured: auth.configured,
    storeFactory: () => GoogleDriveStore(http.Client(), auth.accessToken),
  );
  final chat = ChatController(ChatStore(db), Orchestrator(db, llm), onTurnDone: sync.poke);
  final tasks = TasksController(db, onChanged: sync.poke);
  await chat.load();
  await sync.refresh();
  sync.start();
  return AppServices(
    secureStore: secure, client: client, chat: chat, tasks: tasks, sync: sync,
    dispose: () async {
      sync.dispose();
      await db.close();
    },
  );
}
