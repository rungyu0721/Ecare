import 'package:dio/dio.dart';
import 'package:geocoding/geocoding.dart';
import 'package:geolocator/geolocator.dart';

import '../models/location_models.dart';

class LocationService {
  static const int _maxPositionSamples = 4;
  static const double _targetAccuracyMeters = 30;
  static const Duration _samplePause = Duration(milliseconds: 700);

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

    final position = await _resolveBestPosition();

    _ResolvedAddress? placemarkAddress;
    try {
      final placemarks = await placemarkFromCoordinates(
        position.latitude,
        position.longitude,
      );
      if (placemarks.isNotEmpty) {
        placemarkAddress = _buildAddressFromPlacemark(placemarks.first);
      }
    } catch (_) {
      // Try HTTP reverse geocoding below.
    }

    final apiAddress = await _reverseGeocodeFromApi(
      latitude: position.latitude,
      longitude: position.longitude,
    );
    final resolvedAddress = _pickBestAddress(
      primary: placemarkAddress,
      secondary: apiAddress,
    );

    return LocationSnapshot(
      latitude: position.latitude,
      longitude: position.longitude,
      accuracy: position.accuracy,
      address: resolvedAddress?.displayLabel,
    );
  }

  Future<Position> _resolveBestPosition() async {
    Position best = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.best),
    );

    if (best.accuracy <= _targetAccuracyMeters) {
      return best;
    }

    for (var sampleIndex = 1;
        sampleIndex < _maxPositionSamples;
        sampleIndex++) {
      await Future<void>.delayed(_samplePause);

      try {
        final candidate = await Geolocator.getCurrentPosition(
          locationSettings:
              const LocationSettings(accuracy: LocationAccuracy.best),
        );
        if (candidate.accuracy < best.accuracy) {
          best = candidate;
        }
        if (best.accuracy <= _targetAccuracyMeters) {
          break;
        }
      } catch (_) {
        break;
      }
    }

    return best;
  }

  Future<_ResolvedAddress?> _reverseGeocodeFromApi({
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
        final countyOrCity = _firstNonEmpty(<String?>[
          _valueIfCountyOrCity(address['county'] as String?),
          _valueIfCountyOrCity(address['city'] as String?),
          _valueIfCountyOrCity(address['state_district'] as String?),
          _valueIfCountyOrCity(address['state'] as String?),
          _valueIfCountyOrCity(address['municipality'] as String?),
          address['county'] as String?,
          address['city'] as String?,
          address['state_district'] as String?,
          address['state'] as String?,
          address['municipality'] as String?,
        ]);
        final districtOrTown = _firstNonEmpty(<String?>[
          address['town'] as String?,
          address['city_district'] as String?,
          address['district'] as String?,
          address['municipality'] as String?,
        ]);
        final villageOrArea = _firstNonEmpty(<String?>[
          address['hamlet'] as String?,
          address['village'] as String?,
          address['suburb'] as String?,
          address['borough'] as String?,
          address['quarter'] as String?,
          address['neighbourhood'] as String?,
        ]);
        final rawRoad = _firstNonEmpty(<String?>[
          address['road'] as String?,
          address['pedestrian'] as String?,
          address['footway'] as String?,
        ]);
        // 省道編號（如 "187丙"、"1甲"）不是有用的街道名稱，排除
        final road = _looksLikeHighwayCode(rawRoad) ? null : rawRoad;
        final houseNumber = _firstNonEmpty(<String?>[
          address['house_number'] as String?,
        ]);

        final resolved = _ResolvedAddress(
          countyOrCity: countyOrCity,
          districtOrTown: districtOrTown,
          villageOrArea: villageOrArea,
          road: road,
          houseNumber: houseNumber,
        );
        if (resolved.displayLabel != null) {
          return resolved;
        }
      }

      final displayName = data['display_name'];
      if (displayName is String && displayName.trim().isNotEmpty) {
        return _ResolvedAddress(rawLabel: displayName.trim());
      }
    } catch (_) {
      // Keep falling back to coordinates.
    }
    return null;
  }

  _ResolvedAddress? _buildAddressFromPlacemark(Placemark placemark) {
    final countyOrCity = _firstNonEmpty(<String?>[
      _valueIfCountyOrCity(placemark.administrativeArea),
      _valueIfCountyOrCity(placemark.subAdministrativeArea),
      placemark.administrativeArea,
      placemark.subAdministrativeArea,
    ]);
    final districtOrTown = _firstNonEmpty(<String?>[
      placemark.locality,
      placemark.subAdministrativeArea == countyOrCity
          ? null
          : placemark.subAdministrativeArea,
    ]);
    final resolved = _ResolvedAddress(
      countyOrCity: countyOrCity,
      districtOrTown: districtOrTown,
      villageOrArea: placemark.subLocality,
      road: placemark.thoroughfare,
      houseNumber: placemark.subThoroughfare,
    );

    if (resolved.displayLabel == null) {
      return null;
    }
    return resolved;
  }

  _ResolvedAddress? _pickBestAddress({
    _ResolvedAddress? primary,
    _ResolvedAddress? secondary,
  }) {
    if (primary == null) {
      return secondary;
    }
    if (secondary == null) {
      return primary;
    }
    if (secondary.score > primary.score) {
      return secondary;
    }
    return primary;
  }

  String? _firstNonEmpty(List<String?> candidates) {
    for (final candidate in candidates) {
      final normalized = _normalizeAddressPart(candidate);
      if (normalized != null) {
        return normalized;
      }
    }
    return null;
  }

  String? _normalizeAddressPart(String? value) {
    final cleaned = value?.trim();
    if (cleaned == null || cleaned.isEmpty) {
      return null;
    }
    if (const <String>{
      '台灣省',
      '臺灣省',
      '台湾省',
      'Taiwan Province',
    }.contains(cleaned)) {
      return null;
    }
    return cleaned;
  }

  bool _looksLikeHighwayCode(String? value) {
    final text = value?.trim();
    if (text == null || text.isEmpty) return false;
    return RegExp(r'^\d+[甲乙丙丁戊己庚辛壬癸]?$').hasMatch(text);
  }

  String? _valueIfCountyOrCity(String? value) {
    final normalized = _normalizeAddressPart(value);
    if (normalized == null) {
      return null;
    }
    if (normalized.contains('縣') || normalized.contains('市')) {
      return normalized;
    }
    return null;
  }
}

class _ResolvedAddress {
  const _ResolvedAddress({
    this.countyOrCity,
    this.districtOrTown,
    this.villageOrArea,
    this.road,
    this.houseNumber,
    this.rawLabel,
  });

  final String? countyOrCity;
  final String? districtOrTown;
  final String? villageOrArea;
  final String? road;
  final String? houseNumber;
  final String? rawLabel;

  int get score {
    var value = 0;
    if (_hasText(countyOrCity)) {
      value += 4;
    }
    if (_hasText(districtOrTown)) {
      value += 3;
    }
    if (_hasText(villageOrArea)) {
      value += 2;
    }
    if (_hasText(road)) {
      value += 2;
    }
    if (_shouldIncludeHouseNumber) {
      value += 1;
    }
    if (!_hasStructuredParts && _hasText(rawLabel)) {
      value += 1;
    }
    return value;
  }

  String? get displayLabel {
    final structuredParts = <String>[
      if (_hasText(countyOrCity)) countyOrCity!.trim(),
      if (_hasText(districtOrTown)) districtOrTown!.trim(),
      if (_hasText(villageOrArea)) villageOrArea!.trim(),
      if (_hasText(road)) road!.trim(),
      if (_shouldIncludeHouseNumber) houseNumber!.trim(),
    ];

    if (structuredParts.isNotEmpty) {
      return structuredParts.join();
    }

    final fallback = rawLabel?.trim();
    if (fallback == null || fallback.isEmpty) {
      return null;
    }
    return fallback;
  }

  bool get _hasStructuredParts =>
      _hasText(countyOrCity) ||
      _hasText(districtOrTown) ||
      _hasText(villageOrArea) ||
      _hasText(road);

  bool get _shouldIncludeHouseNumber =>
      _hasText(road) && _hasText(houseNumber) && !_looksLikeOnlyLotNumber;

  bool get _looksLikeOnlyLotNumber {
    final text = houseNumber?.trim();
    if (text == null || text.isEmpty) {
      return false;
    }
    return RegExp(r'^\d+[甲乙丙丁戊己庚辛壬癸]?$').hasMatch(text);
  }

  bool _hasText(String? value) {
    final text = value?.trim();
    return text != null && text.isNotEmpty;
  }
}
