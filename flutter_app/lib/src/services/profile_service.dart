import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/api_config.dart';
import '../models/user_profile.dart';

class ProfileService {
  static const String storageKey = 'ecare_user_profile';

  ProfileService({Dio? dio})
      : _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: ApiConfig.defaultBaseUrl,
                connectTimeout: const Duration(seconds: 15),
                receiveTimeout: const Duration(seconds: 30),
                headers: const <String, String>{
                  'Content-Type': 'application/json',
                },
              ),
            );

  final Dio _dio;

  Future<UserProfile?> loadProfile() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(storageKey);
    if (raw == null || raw.isEmpty) {
      return null;
    }

    try {
      final json = jsonDecode(raw) as Map<String, dynamic>;
      return UserProfile.fromJson(json);
    } catch (_) {
      return null;
    }
  }

  Future<UserProfile> saveProfile(UserProfile profile) async {
    final payload = profile.toApiJson();
    Response<Map<String, dynamic>> response;

    if (profile.id == null) {
      response = await _dio.post<Map<String, dynamic>>('/users', data: payload);
    } else {
      try {
        response = await _dio.put<Map<String, dynamic>>('/users/${profile.id}', data: payload);
      } on DioException catch (error) {
        if (error.response?.statusCode != 404) {
          rethrow;
        }
        response = await _dio.post<Map<String, dynamic>>('/users', data: payload);
      }
    }

    final data = response.data;
    if (data == null) {
      throw Exception('Profile response is empty.');
    }

    final savedProfile = UserProfile.fromApiJson(data);
    await saveProfileToLocal(savedProfile);
    return savedProfile;
  }

  Future<void> saveProfileToLocal(UserProfile profile) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(storageKey, jsonEncode(profile.toJson()));
  }
}
