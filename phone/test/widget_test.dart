import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/main.dart';

void main() {
  testWidgets('app builds and shows the API key screen first', (tester) async {
    await tester.pumpWidget(const IoApp());
    expect(find.text('Enter your Anthropic API key'), findsOneWidget);
  });
}
