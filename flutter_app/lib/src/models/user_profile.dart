class UserProfile {
  const UserProfile({
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

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
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
}
