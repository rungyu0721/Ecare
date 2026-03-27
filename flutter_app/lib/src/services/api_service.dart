import 'package:dio/dio.dart';
import 'package:http_parser/http_parser.dart';
import 'package:mime/mime.dart';

import '../models/audio_models.dart';
import '../config/api_config.dart';
import '../models/chat_models.dart';
import '../models/report_item.dart';

class ApiService {
  ApiService({Dio? dio, String? baseUrl})
      : _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: baseUrl ?? ApiConfig.defaultBaseUrl,
                connectTimeout: const Duration(seconds: 15),
                receiveTimeout: const Duration(seconds: 30),
                headers: <String, String>{
                  'Content-Type': 'application/json',
                },
              ),
            );

  final Dio _dio;

  Future<ChatResponse> sendChat({
    required List<ChatMessage> messages,
    Map<String, dynamic>? audioContext,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/chat',
      data: <String, dynamic>{
        'messages': messages.map((message) => message.toJson()).toList(),
        'audio_context': audioContext,
      },
    );

    final data = response.data;
    if (data == null) {
      throw Exception('Chat response is empty.');
    }

    return ChatResponse.fromJson(data);
  }

  Future<List<ReportItem>> fetchReports() async {
    final response = await _dio.get<List<dynamic>>('/reports');
    final rows = response.data ?? <dynamic>[];
    return rows
        .whereType<Map<String, dynamic>>()
        .map(ReportItem.fromJson)
        .toList();
  }

  Future<ReportItem> createReport({
    required String title,
    required String category,
    required String location,
    required String riskLevel,
    required double riskScore,
    required String description,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/reports',
      data: <String, dynamic>{
        'title': title,
        'category': category,
        'location': location,
        'risk_level': riskLevel,
        'risk_score': riskScore,
        'description': description,
      },
    );

    final data = response.data;
    if (data == null) {
      throw Exception('Create report response is empty.');
    }

    return ReportItem.fromJson(data);
  }

  Future<AudioAnalysis> uploadAudio({
    required String filePath,
    String fileName = 'recording.wav',
  }) async {
    final mimeType = lookupMimeType(filePath) ?? 'audio/wav';
    final mediaType = MediaType.parse(mimeType);

    final formData = FormData.fromMap(
      <String, dynamic>{
        'audio': await MultipartFile.fromFile(
          filePath,
          filename: fileName,
          contentType: mediaType,
        ),
      },
    );

    final response = await _dio.post<Map<String, dynamic>>(
      '/audio',
      data: formData,
      options: Options(
        headers: <String, String>{
          'Content-Type': 'multipart/form-data',
        },
      ),
    );

    final data = response.data;
    if (data == null) {
      throw Exception('Audio response is empty.');
    }

    return AudioAnalysis.fromJson(data);
  }
}
