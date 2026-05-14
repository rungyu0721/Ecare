class ApiConfig {
  // 預設值：本機開發。部署時透過 --dart-define 覆蓋，例如：
  //   flutter run --dart-define=API_BASE_URL=http://192.168.50.x:8000
  //   flutter build apk --dart-define=API_BASE_URL=https://your-server.com
  static const String defaultBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
}
