import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/app.dart';
import 'package:io_phone/main.dart';

void main() {
  testWidgets('the app shows a loader while it boots', (tester) async {
    // a bootstrap that never completes: we only look at the first frame
    await tester.pumpWidget(IoApp(bootstrap: () => Future.any([])));
    expect(find.byType(BootScreen), findsOneWidget);
  });

  test('main.dart exposes the real entry point', () {
    expect(main, isA<Function>());
  });
}
