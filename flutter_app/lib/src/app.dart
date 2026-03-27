import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'screens/chat_screen.dart';

class EcareApp extends StatelessWidget {
  const EcareApp({super.key});

  static const Color background = Color(0xFFF6E2BF);
  static const Color backgroundAlt = Color(0xFFF4D7A7);
  static const Color primary = Color(0xFFC95A4A);
  static const Color primaryDark = Color(0xFFB84B3D);
  static const Color card = Color(0xFFFFF7EA);
  static const Color text = Color(0xFF3A2A1D);
  static const Color muted = Color(0xFF6C584C);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'E-CARE',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: primary,
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: background,
        appBarTheme: const AppBarTheme(
          backgroundColor: primary,
          foregroundColor: Colors.white,
          elevation: 0,
          centerTitle: false,
        ),
        cardColor: card,
        textTheme: const TextTheme(
          bodyMedium: TextStyle(color: text),
          titleMedium: TextStyle(color: text, fontWeight: FontWeight.w700),
        ),
        useMaterial3: true,
      ),
      routes: <String, WidgetBuilder>{
        '/home': (_) => const HomeScreen(),
        '/chat': (_) => const ChatScreen(),
      },
      home: const HomeScreen(),
    );
  }
}
