import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import '../app.dart';
import '../models/user_profile.dart';
import '../services/profile_service.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  final _profileService = ProfileService();

  final _nameController = TextEditingController();
  final _phoneController = TextEditingController();
  final _genderController = TextEditingController();
  final _ageController = TextEditingController();
  final _emergencyNameController = TextEditingController();
  final _emergencyPhoneController = TextEditingController();
  final _relationshipController = TextEditingController();
  final _addressController = TextEditingController();
  final _noteController = TextEditingController();

  bool _loading = true;
  bool _isSaving = false;
  String _message = '';

  @override
  void initState() {
    super.initState();
    _loadExistingProfile();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    _genderController.dispose();
    _ageController.dispose();
    _emergencyNameController.dispose();
    _emergencyPhoneController.dispose();
    _relationshipController.dispose();
    _addressController.dispose();
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _loadExistingProfile() async {
    final profile = await _profileService.loadProfile();
    if (profile != null) {
      _nameController.text = profile.name;
      _phoneController.text = profile.phone;
      _genderController.text = profile.gender;
      _ageController.text = profile.age;
      _emergencyNameController.text = profile.emergencyName;
      _emergencyPhoneController.text = profile.emergencyPhone;
      _relationshipController.text = profile.relationship;
      _addressController.text = profile.address;
      _noteController.text = profile.note;
    }
    if (!mounted) {
      return;
    }
    setState(() {
      _loading = false;
    });
  }

  bool _isValidPhone(String value) {
    final regExp = RegExp(r'^[0-9+\-()#\s]{8,20}$');
    return regExp.hasMatch(value);
  }

  String _buildSaveErrorMessage(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map<String, dynamic>) {
        final detail = data['detail'];
        if (detail is String && detail.trim().isNotEmpty) {
          return 'Save failed: ' + detail.trim();
        }
      }

      final message = error.message?.trim();
      if (message != null && message.isNotEmpty) {
        return 'Save failed: ' + message;
      }
    }

    return 'Save failed. Please check backend and database connection.';
  }

  Future<void> _submit() async {
    if (_isSaving || !_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isSaving = true;
      _message = '';
    });

    try {
      final existingProfile = await _profileService.loadProfile();
      final profile = UserProfile(
        id: existingProfile?.id,
        name: _nameController.text.trim(),
        phone: _phoneController.text.trim(),
        gender: _genderController.text.trim(),
        age: _ageController.text.trim(),
        emergencyName: _emergencyNameController.text.trim(),
        emergencyPhone: _emergencyPhoneController.text.trim(),
        relationship: _relationshipController.text.trim(),
        address: _addressController.text.trim(),
        note: _noteController.text.trim(),
        updatedAt: DateTime.now().toIso8601String(),
      );

      final savedProfile = await _profileService.saveProfile(profile);
      if (!mounted) {
        return;
      }

      _nameController.text = savedProfile.name;
      _phoneController.text = savedProfile.phone;
      _genderController.text = savedProfile.gender;
      _ageController.text = savedProfile.age;
      _emergencyNameController.text = savedProfile.emergencyName;
      _emergencyPhoneController.text = savedProfile.emergencyPhone;
      _relationshipController.text = savedProfile.relationship;
      _addressController.text = savedProfile.address;
      _noteController.text = savedProfile.note;

      Navigator.of(context).pop();
    } catch (error) {
      if (!mounted) {
        return;
      }
      final errorMessage = _buildSaveErrorMessage(error);
      setState(() {
        _message = errorMessage;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(errorMessage)),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSaving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0, -0.5),
            radius: 1.2,
            colors: <Color>[
              EcareApp.backgroundAlt,
              EcareApp.background,
              Color(0xFFF3E8D4),
            ],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 760),
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 20, 16, 24),
                child: Column(
                  children: <Widget>[
                    const Text(
                      'E-CARE',
                      style: TextStyle(
                        fontSize: 34,
                        fontWeight: FontWeight.w900,
                        letterSpacing: 3,
                        color: EcareApp.text,
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      '\u500b\u4eba\u8cc7\u6599\u8a2d\u5b9a',
                      style: TextStyle(fontSize: 18, color: EcareApp.text),
                    ),
                    const SizedBox(height: 16),
                    Container(
                      decoration: BoxDecoration(
                        color: const Color.fromRGBO(255, 247, 234, 0.86),
                        borderRadius: BorderRadius.circular(24),
                        boxShadow: const <BoxShadow>[
                          BoxShadow(
                            color: Color.fromRGBO(0, 0, 0, 0.12),
                            blurRadius: 26,
                            offset: Offset(0, 10),
                          ),
                        ],
                        border: Border.all(color: const Color.fromRGBO(255, 255, 255, 0.5)),
                      ),
                      padding: const EdgeInsets.all(18),
                      child: Form(
                        key: _formKey,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: <Widget>[
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: <Widget>[
                                Container(
                                  width: 56,
                                  height: 56,
                                  decoration: BoxDecoration(
                                    color: const Color.fromRGBO(201, 90, 74, 0.12),
                                    borderRadius: BorderRadius.circular(18),
                                  ),
                                  child: const Icon(
                                    Icons.person_outline,
                                    color: EcareApp.primary,
                                    size: 28,
                                  ),
                                ),
                                const SizedBox(width: 14),
                                const Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: <Widget>[
                                      Text(
                                        '\u8acb\u5148\u5b8c\u6210\u57fa\u672c\u8cc7\u6599',
                                        style: TextStyle(
                                          fontSize: 22,
                                          fontWeight: FontWeight.w800,
                                          color: EcareApp.text,
                                        ),
                                      ),
                                      SizedBox(height: 6),
                                      Text(
                                        '\u9019\u4e9b\u8cc7\u6599\u6703\u7528\u5728\u7dca\u6025\u901a\u5831\u6642\u5feb\u901f\u5e36\u5165\uff0c\u8b93\u7cfb\u7d71\u66f4\u5feb\u6574\u7406\u4f60\u7684\u72c0\u6cc1\u3002',
                                        style: TextStyle(
                                          color: EcareApp.muted,
                                          height: 1.6,
                                          fontSize: 14,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 18),
                            _Field(
                              controller: _nameController,
                              label: '\u59d3\u540d',
                              requiredField: true,
                              validator: (value) {
                                if ((value ?? '').trim().isEmpty) {
                                  return '\u8acb\u8f38\u5165\u59d3\u540d';
                                }
                                return null;
                              },
                            ),
                            _Field(
                              controller: _phoneController,
                              label: '\u96fb\u8a71',
                              requiredField: true,
                              keyboardType: TextInputType.phone,
                              validator: (value) {
                                final text = (value ?? '').trim();
                                if (text.isEmpty) {
                                  return '\u8acb\u8f38\u5165\u96fb\u8a71';
                                }
                                if (!_isValidPhone(text)) {
                                  return '\u96fb\u8a71\u683c\u5f0f\u4e0d\u6b63\u78ba';
                                }
                                return null;
                              },
                            ),
                            _Field(controller: _genderController, label: '\u6027\u5225'),
                            _Field(
                              controller: _ageController,
                              label: '\u5e74\u9f61',
                              keyboardType: TextInputType.number,
                            ),
                            _Field(
                              controller: _emergencyNameController,
                              label: '\u7dca\u6025\u806f\u7d61\u4eba\u59d3\u540d',
                            ),
                            _Field(
                              controller: _emergencyPhoneController,
                              label: '\u7dca\u6025\u806f\u7d61\u4eba\u96fb\u8a71',
                              keyboardType: TextInputType.phone,
                              validator: (value) {
                                final text = (value ?? '').trim();
                                if (text.isNotEmpty && !_isValidPhone(text)) {
                                  return '\u7dca\u6025\u806f\u7d61\u4eba\u96fb\u8a71\u683c\u5f0f\u4e0d\u6b63\u78ba';
                                }
                                return null;
                              },
                            ),
                            _Field(controller: _relationshipController, label: '\u95dc\u4fc2'),
                            _Field(
                              controller: _addressController,
                              label: '\u5730\u5740',
                              maxLines: 3,
                            ),
                            _Field(
                              controller: _noteController,
                              label: '\u5099\u8a3b / \u75c5\u53f2',
                              maxLines: 3,
                            ),
                            const SizedBox(height: 8),
                            if (_message.isNotEmpty) ...<Widget>[
                              Text(
                                _message,
                                style: const TextStyle(
                                  color: EcareApp.primaryDark,
                                  fontWeight: FontWeight.w700,
                                  fontSize: 13,
                                ),
                              ),
                              const SizedBox(height: 8),
                            ],
                            FilledButton(
                              onPressed: _isSaving ? null : _submit,
                              style: FilledButton.styleFrom(
                                backgroundColor: EcareApp.primary,
                                foregroundColor: Colors.white,
                                minimumSize: const Size.fromHeight(48),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(14),
                                ),
                              ),
                              child: _isSaving
                                  ? const SizedBox(
                                      width: 18,
                                      height: 18,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: Colors.white,
                                      ),
                                    )
                                  : const Text('\u5132\u5b58\u8cc7\u6599'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({
    required this.controller,
    required this.label,
    this.requiredField = false,
    this.maxLines = 1,
    this.keyboardType,
    this.validator,
  });

  final TextEditingController controller;
  final String label;
  final bool requiredField;
  final int maxLines;
  final TextInputType? keyboardType;
  final String? Function(String?)? validator;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          RichText(
            text: TextSpan(
              children: <InlineSpan>[
                TextSpan(
                  text: label,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: EcareApp.text,
                  ),
                ),
                if (requiredField)
                  const TextSpan(
                    text: ' *',
                    style: TextStyle(color: EcareApp.primary),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          TextFormField(
            controller: controller,
            validator: validator,
            keyboardType: keyboardType,
            minLines: maxLines,
            maxLines: maxLines,
            decoration: InputDecoration(
              filled: true,
              fillColor: const Color(0xFFFFFAF1),
              contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: const BorderSide(color: Color.fromRGBO(58, 42, 29, 0.12)),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: const BorderSide(color: Color.fromRGBO(58, 42, 29, 0.12)),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
                borderSide: const BorderSide(color: Color.fromRGBO(201, 90, 74, 0.55)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
