class LocationSnapshot {
  const LocationSnapshot({
    required this.latitude,
    required this.longitude,
    required this.accuracy,
    this.address,
  });

  final double latitude;
  final double longitude;
  final double accuracy;
  final String? address;

  String toDisplayText() {
    final addressText = address?.trim();
    if (addressText != null && addressText.isNotEmpty) {
      return '$addressText (+/- ${accuracy.round()}m)';
    }
    return '座標 $latitude, $longitude (+/- ${accuracy.round()}m)';
  }

  String toReportLocationText() {
    final addressText = address?.trim();
    if (addressText != null && addressText.isNotEmpty) {
      return '$addressText (+/- ${accuracy.round()}m)';
    }
    return '座標 $latitude, $longitude';
  }
}
