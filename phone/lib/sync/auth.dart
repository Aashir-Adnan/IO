import 'package:google_sign_in/google_sign_in.dart';

/// Who is signed in to the user's Google account, and a token for Drive.
abstract class AuthProvider {
  /// Silently restore a previous sign-in. True if Drive access is available.
  Future<bool> restore();

  /// Interactive sign-in + consent for the Drive appdata scope.
  Future<void> signIn();
  Future<void> signOut();

  /// A current OAuth access token for the Drive appdata scope.
  Future<String> accessToken();
}

/// Only the app's own hidden Drive folder — IO can never see the rest of the
/// user's Drive (rules/local-first.md, case 8).
const driveAppDataScope = 'https://www.googleapis.com/auth/drive.appdata';

/// Google sign-in through the `google_sign_in` plugin (Credential Manager on
/// Android). Needs a Google Cloud OAuth setup — see .claude/knowledge/
/// phone-app.md — and the *web* client id passed at build time:
///   flutter build apk --dart-define=GOOGLE_SERVER_CLIENT_ID=...apps.googleusercontent.com
class GoogleAuthProvider implements AuthProvider {
  final String serverClientId;
  GoogleAuthProvider({this.serverClientId = const String.fromEnvironment('GOOGLE_SERVER_CLIENT_ID')});

  bool get configured => serverClientId.isNotEmpty;
  bool _initialised = false;

  Future<void> _init() async {
    if (_initialised) return;
    await GoogleSignIn.instance.initialize(serverClientId: serverClientId);
    _initialised = true;
  }

  @override
  Future<bool> restore() async {
    if (!configured) return false;
    await _init();
    final account = await GoogleSignIn.instance.attemptLightweightAuthentication();
    if (account == null) return false;
    return await account.authorizationClient.authorizationForScopes([driveAppDataScope]) != null;
  }

  @override
  Future<void> signIn() async {
    if (!configured) throw StateError('Sync is not configured in this build.');
    await _init();
    final account = await GoogleSignIn.instance.authenticate(scopeHint: [driveAppDataScope]);
    await account.authorizationClient.authorizeScopes([driveAppDataScope]);
  }

  @override
  Future<void> signOut() => GoogleSignIn.instance.signOut();

  @override
  Future<String> accessToken() async {
    final authz = await GoogleSignIn.instance.authorizationClient
        .authorizationForScopes([driveAppDataScope]);
    if (authz == null) throw StateError('Google access has expired — sign in again.');
    return authz.accessToken;
  }
}
