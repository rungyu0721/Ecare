class AudioAnalysis {
  const AudioAnalysis({
    required this.transcript,
    required this.emotion,
    required this.emotionScore,
    required this.situation,
    required this.riskLevel,
    required this.riskScore,
    required this.shouldEscalate,
    required this.analysisSummary,
    required this.extracted,
    this.localFilePath,
  });

  final String transcript;
  final String emotion;
  final double? emotionScore;
  final String situation;
  final String riskLevel;
  final double? riskScore;
  final bool shouldEscalate;
  final String analysisSummary;
  final Map<String, dynamic>? extracted;
  final String? localFilePath;

  bool get isHighRisk => riskLevel == 'High' || shouldEscalate;

  String get localizedEmotion {
    return switch (emotion) {
      'panic' => '\u614c\u5f35',
      'fearful' => '\u5bb3\u6015',
      'sad' => '\u96e3\u53d7',
      'angry' => '\u6fc0\u52d5',
      'neutral' => '\u5e73\u7a69',
      _ => '\u5f85\u78ba\u8a8d',
    };
  }

  String get localizedRiskLevel {
    return switch (riskLevel) {
      'High' => '\u9ad8\u98a8\u96aa',
      'Medium' => '\u4e2d\u98a8\u96aa',
      _ => '\u4f4e\u98a8\u96aa',
    };
  }

  Map<String, dynamic> toAudioContext() {
    return <String, dynamic>{
      'transcript': transcript,
      'emotion': emotion,
      'emotion_score': emotionScore,
      'situation': situation,
      'risk_level': riskLevel,
      'risk_score': riskScore,
      'should_escalate': shouldEscalate,
      'analysis_summary': analysisSummary,
      'extracted': extracted,
    };
  }

  AudioAnalysis copyWith({
    String? localFilePath,
  }) {
    return AudioAnalysis(
      transcript: transcript,
      emotion: emotion,
      emotionScore: emotionScore,
      situation: situation,
      riskLevel: riskLevel,
      riskScore: riskScore,
      shouldEscalate: shouldEscalate,
      analysisSummary: analysisSummary,
      extracted: extracted,
      localFilePath: localFilePath ?? this.localFilePath,
    );
  }

  factory AudioAnalysis.fromJson(Map<String, dynamic> json) {
    return AudioAnalysis(
      transcript: json['transcript'] as String? ?? '',
      emotion: json['emotion'] as String? ?? 'unknown',
      emotionScore: (json['emotion_score'] as num?)?.toDouble(),
      situation: json['situation'] as String? ?? '',
      riskLevel: json['risk_level'] as String? ?? 'Low',
      riskScore: (json['risk_score'] as num?)?.toDouble(),
      shouldEscalate: json['should_escalate'] as bool? ?? false,
      analysisSummary: json['analysis_summary'] as String? ?? '',
      extracted: json['extracted'] as Map<String, dynamic>?,
      localFilePath: null,
    );
  }
}
