class ChatMessage {
  const ChatMessage({
    required this.role,
    required this.content,
  });

  final String role;
  final String content;

  Map<String, dynamic> toJson() {
    return {
      'role': role,
      'content': content,
    };
  }
}

class ExtractedData {
  const ExtractedData({
    this.category,
    this.location,
    this.peopleInjured,
    this.weapon,
    this.dangerActive,
    this.dispatchAdvice,
    this.description,
  });

  final String? category;
  final String? location;
  final bool? peopleInjured;
  final bool? weapon;
  final bool? dangerActive;
  final String? dispatchAdvice;
  final String? description;

  factory ExtractedData.fromJson(Map<String, dynamic> json) {
    return ExtractedData(
      category: json['category'] as String?,
      location: json['location'] as String?,
      peopleInjured: json['people_injured'] as bool?,
      weapon: json['weapon'] as bool?,
      dangerActive: json['danger_active'] as bool?,
      dispatchAdvice: json['dispatch_advice'] as String?,
      description: json['description'] as String?,
    );
  }
}

class SemanticEntities {
  const SemanticEntities({
    this.location,
    this.injured,
    this.weapon,
    this.dangerActive,
  });

  final String? location;
  final bool? injured;
  final bool? weapon;
  final bool? dangerActive;

  factory SemanticEntities.fromJson(Map<String, dynamic> json) {
    return SemanticEntities(
      location: json['location'] as String?,
      injured: json['injured'] as bool?,
      weapon: json['weapon'] as bool?,
      dangerActive: json['danger_active'] as bool?,
    );
  }
}

class SemanticData {
  const SemanticData({
    required this.intent,
    required this.primaryNeed,
    required this.emotion,
    required this.replyStrategy,
    required this.entities,
  });

  final String intent;
  final String primaryNeed;
  final String emotion;
  final String replyStrategy;
  final SemanticEntities entities;

  factory SemanticData.fromJson(Map<String, dynamic> json) {
    return SemanticData(
      intent: json['intent'] as String? ?? '未知',
      primaryNeed: json['primary_need'] as String? ?? '釐清狀況',
      emotion: json['emotion'] as String? ?? 'neutral',
      replyStrategy: json['reply_strategy'] as String? ?? '先確認事件重點',
      entities: SemanticEntities.fromJson(
        (json['entities'] as Map<String, dynamic>?) ?? <String, dynamic>{},
      ),
    );
  }
}

class ChatResponse {
  const ChatResponse({
    required this.reply,
    required this.riskScore,
    required this.riskLevel,
    required this.shouldEscalate,
    required this.nextQuestion,
    required this.extracted,
    required this.semantic,
  });

  final String reply;
  final double riskScore;
  final String riskLevel;
  final bool shouldEscalate;
  final String? nextQuestion;
  final ExtractedData extracted;
  final SemanticData semantic;

  factory ChatResponse.fromJson(Map<String, dynamic> json) {
    return ChatResponse(
      reply: json['reply'] as String? ?? '',
      riskScore: (json['risk_score'] as num?)?.toDouble() ?? 0,
      riskLevel: json['risk_level'] as String? ?? 'Low',
      shouldEscalate: json['should_escalate'] as bool? ?? false,
      nextQuestion: json['next_question'] as String?,
      extracted: ExtractedData.fromJson(
        (json['extracted'] as Map<String, dynamic>?) ?? <String, dynamic>{},
      ),
      semantic: SemanticData.fromJson(
        (json['semantic'] as Map<String, dynamic>?) ?? <String, dynamic>{},
      ),
    );
  }
}
