class AudioAnalysis {
  const AudioAnalysis({
    required this.transcript,
    required this.emotion,
    required this.emotionScore,
    required this.situation,
    required this.riskLevel,
    required this.riskScore,
    required this.extracted,
  });

  final String transcript;
  final String emotion;
  final double? emotionScore;
  final String situation;
  final String riskLevel;
  final double? riskScore;
  final Map<String, dynamic>? extracted;

  Map<String, dynamic> toAudioContext() {
    return <String, dynamic>{
      'transcript': transcript,
      'emotion': emotion,
      'emotion_score': emotionScore,
      'situation': situation,
      'risk_level': riskLevel,
      'risk_score': riskScore,
      'extracted': extracted,
    };
  }

  factory AudioAnalysis.fromJson(Map<String, dynamic> json) {
    return AudioAnalysis(
      transcript: json['transcript'] as String? ?? '',
      emotion: json['emotion'] as String? ?? 'unknown',
      emotionScore: (json['emotion_score'] as num?)?.toDouble(),
      situation: json['situation'] as String? ?? '',
      riskLevel: json['risk_level'] as String? ?? 'Low',
      riskScore: (json['risk_score'] as num?)?.toDouble(),
      extracted: json['extracted'] as Map<String, dynamic>?,
    );
  }
}
