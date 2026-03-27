import 'package:flutter_test/flutter_test.dart';

import 'package:ecare_flutter/src/app.dart';

void main() {
  testWidgets('app renders E-CARE shell', (WidgetTester tester) async {
    await tester.pumpWidget(const EcareApp());

    expect(find.text('E-CARE'), findsOneWidget);
  });
}
