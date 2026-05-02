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
    return '${latitude.toStringAsFixed(6)}, '
        '${longitude.toStringAsFixed(6)} '
        '(+/- ${accuracy.round()}m)';
  }
}
