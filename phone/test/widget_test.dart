import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:io_phone/main.dart';

void main() {
  testWidgets('app builds without throwing', (tester) async {
    await tester.pumpWidget(const IoApp());
    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
