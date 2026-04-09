class UserProfile {
  const UserProfile({
    this.id,
    required this.name,
    required this.phone,
    this.gender = '',
    this.age = '',
    this.emergencyName = '',
    this.emergencyPhone = '',
    this.relationship = '',
    this.address = '',
    this.note = '',
    this.updatedAt = '',
  });

  final int? id;
  final String name;
  final String phone;
  final String gender;
  final String age;
  final String emergencyName;
  final String emergencyPhone;
  final String relationship;
  final String address;
  final String note;
  final String updatedAt;

  bool get hasRequiredFields => name.trim().isNotEmpty && phone.trim().isNotEmpty;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'id': id,
      'name': name,
      'phone': phone,
      'gender': gender,
      'age': age,
      'emergencyName': emergencyName,
      'emergencyPhone': emergencyPhone,
      'relationship': relationship,
      'address': address,
      'note': note,
      'updatedAt': updatedAt,
    };
  }

  Map<String, dynamic> toApiJson() {
    final normalizedAge = int.tryParse(age.trim());

    return <String, dynamic>{
      'name': name.trim(),
      'phone': phone.trim(),
      'gender': _nullableText(gender),
      'age': normalizedAge,
      'emergency_name': _nullableText(emergencyName),
      'emergency_phone': _nullableText(emergencyPhone),
      'relationship': _nullableText(relationship),
      'address': _nullableText(address),
      'notes': _nullableText(note),
    };
  }

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      id: json['id'] as int?,
      name: json['name'] as String? ?? '',
      phone: json['phone'] as String? ?? '',
      gender: json['gender'] as String? ?? '',
      age: json['age'] as String? ?? '',
      emergencyName: json['emergencyName'] as String? ?? '',
      emergencyPhone: json['emergencyPhone'] as String? ?? '',
      relationship: json['relationship'] as String? ?? '',
      address: json['address'] as String? ?? '',
      note: json['note'] as String? ?? '',
      updatedAt: json['updatedAt'] as String? ?? '',
    );
  }

  factory UserProfile.fromApiJson(Map<String, dynamic> json) {
    return UserProfile(
      id: json['id'] as int?,
      name: json['name'] as String? ?? '',
      phone: json['phone'] as String? ?? '',
      gender: json['gender'] as String? ?? '',
      age: _stringFromDynamic(json['age']),
      emergencyName: json['emergency_name'] as String? ?? '',
      emergencyPhone: json['emergency_phone'] as String? ?? '',
      relationship: json['relationship'] as String? ?? '',
      address: json['address'] as String? ?? '',
      note: json['notes'] as String? ?? '',
      updatedAt: json['created_at'] as String? ?? '',
    );
  }

  static String? _nullableText(String value) {
    final text = value.trim();
    return text.isEmpty ? null : text;
  }

  static String _stringFromDynamic(dynamic value) {
    if (value == null) {
      return '';
    }
    return '$value';
  }
}
