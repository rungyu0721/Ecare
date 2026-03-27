import 'package:geocoding/geocoding.dart';
import 'package:geolocator/geolocator.dart';
import 'package:dio/dio.dart';

import '../models/location_models.dart';

class LocationService {
  final Dio _dio = Dio(
    BaseOptions(
      connectTimeout: const Duration(seconds: 8),
      receiveTimeout: const Duration(seconds: 8),
      headers: <String, String>{
        'User-Agent': 'EcareFlutter/0.1',
        'Accept': 'application/json',
      },
    ),
  );

  Future<LocationSnapshot> getCurrentLocation() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      throw Exception('Location service is disabled.');
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }

    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      throw Exception('Location permission denied.');
    }

    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
    );

    String? address;
    try {
      final placemarks = await placemarkFromCoordinates(
        position.latitude,
        position.longitude,
      );
      if (placemarks.isNotEmpty) {
        final placemark = placemarks.first;
        final parts = <String?>[
          placemark.administrativeArea,
          placemark.locality ?? placemark.subAdministrativeArea,
          placemark.subLocality,
          placemark.thoroughfare,
          placemark.subThoroughfare,
        ]
            .whereType<String>()
            .map((value) => value.trim())
            .where((value) => value.isNotEmpty)
            .toList();
        if (parts.isNotEmpty) {
          address = parts.join();
        }
      }
    } catch (_) {
      // Try HTTP reverse geocoding below.
    }

    address ??= await _reverseGeocodeFromApi(
      latitude: position.latitude,
      longitude: position.longitude,
    );

    return LocationSnapshot(
      latitude: position.latitude,
      longitude: position.longitude,
      accuracy: position.accuracy,
      address: address,
    );
  }

  Future<String?> _reverseGeocodeFromApi({
    required double latitude,
    required double longitude,
  }) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        'https://nominatim.openstreetmap.org/reverse',
        queryParameters: <String, dynamic>{
          'lat': latitude,
          'lon': longitude,
          'format': 'jsonv2',
          'addressdetails': 1,
          'accept-language': 'zh-TW',
        },
      );

      final data = response.data;
      if (data == null) {
        return null;
      }

      final address = data['address'];
      if (address is Map<String, dynamic>) {
        final parts = <String?>[
          address['state'] as String?,
          address['city'] as String? ??
              address['town'] as String? ??
              address['county'] as String? ??
              address['municipality'] as String?,
          address['suburb'] as String? ??
              address['city_district'] as String? ??
              address['district'] as String? ??
              address['borough'] as String? ??
              address['village'] as String?,
          address['road'] as String?,
          address['house_number'] as String?,
        ]
            .whereType<String>()
            .map((value) => value.trim())
            .where((value) => value.isNotEmpty)
            .toList();

        if (parts.isNotEmpty) {
          return parts.join();
        }
      }

      final displayName = data['display_name'];
      if (displayName is String && displayName.trim().isNotEmpty) {
        return displayName.trim();
      }
    } catch (_) {
      // Keep falling back to coordinates.
    }
    return null;
  }
}
