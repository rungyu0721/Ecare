class ReportItem {
  const ReportItem({
    required this.id,
    required this.title,
    required this.category,
    required this.location,
    this.latitude,
    this.longitude,
    required this.status,
    required this.createdAt,
    required this.riskLevel,
    required this.riskScore,
    required this.description,
  });

  final String id;
  final String title;
  final String category;
  final String location;
  final double? latitude;
  final double? longitude;
  final String status;
  final String createdAt;
  final String riskLevel;
  final double riskScore;
  final String description;

  factory ReportItem.fromJson(Map<String, dynamic> json) {
    return ReportItem(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      category: json['category'] as String? ?? '',
      location: json['location'] as String? ?? '',
      latitude: (json['latitude'] as num?)?.toDouble(),
      longitude: (json['longitude'] as num?)?.toDouble(),
      status: json['status'] as String? ?? '',
      createdAt: json['created_at'] as String? ?? '',
      riskLevel: json['risk_level'] as String? ?? 'Low',
      riskScore: (json['risk_score'] as num?)?.toDouble() ?? 0,
      description: json['description'] as String? ?? '',
    );
  }
}
