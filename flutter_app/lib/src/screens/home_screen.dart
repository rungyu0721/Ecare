import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app.dart';
import '../models/location_models.dart';
import '../models/user_profile.dart';
import '../services/api_service.dart';
import '../services/location_service.dart';
import '../services/profile_service.dart';
import 'chat_screen.dart';
import 'profile_screen.dart';
import 'records_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final ProfileService _profileService = ProfileService();
  final LocationService _locationService = LocationService();
  final ApiService _apiService = ApiService();

  UserProfile? _profile;
  String _welcomeText = '';
  String _locationText = '尚未取得位置';
  String _statusText = '待命中';
  String _resultText = '長按 3 秒會將目前位置與個人資料送至 E-CARE 管理端；若有立即危險，請同步撥打 119 或 110。';
  bool _loading = true;
  bool _isHolding = false;
  bool _isSubmittingEmergency = false;
  double _holdProgress = 0;
  Future<void>? _locationFetchTask;
  LocationSnapshot? _currentLocation;

  @override
  void initState() {
    super.initState();
    _loadProfile();
  }

  Future<void> _loadProfile() async {
    final profile = await _profileService.loadProfile();
    if (!mounted) {
      return;
    }

    if (profile == null || !profile.hasRequiredFields) {
      await Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => const ProfileScreen()),
      );
      final refreshed = await _profileService.loadProfile();
      if (!mounted) {
        return;
      }
      setState(() {
        _profile = refreshed;
        _welcomeText = refreshed == null ? '' : '您好，${refreshed.name}';
        _loading = false;
        _resultText = refreshed == null
            ? '請先完成個人資料，緊急時才能快速整理姓名、電話與聯絡資訊。'
            : '個人資料已準備完成：${refreshed.name} / ${refreshed.phone}';
      });
      unawaited(_primeLocationFetch());
      return;
    }

    setState(() {
      _profile = profile;
      _welcomeText = '您好，${profile.name}';
      _loading = false;
      _resultText = '個人資料已準備完成：${profile.name} / ${profile.phone}';
    });
    unawaited(_primeLocationFetch());
  }

  Future<void> _startEmergencyFlow() async {
    if (_isSubmittingEmergency) {
      return;
    }

    final profile = _profile;
    if (profile == null) {
      setState(() {
        _statusText = '缺少個人資料';
        _resultText = '請先完成個人資料，再送出緊急通報。';
        _holdProgress = 0;
      });
      return;
    }

    setState(() {
      _isSubmittingEmergency = true;
      _statusText = '正在送出緊急通報...';
    });

    try {
      final location =
          _currentLocation ?? await _locationService.getCurrentLocation();
      final locationText = _locationDisplayText(location);

      await _apiService.createReport(
        title: 'E-CARE 緊急通報',
        category: '救援通報',
        location: locationText,
        latitude: location.latitude,
        longitude: location.longitude,
        riskLevel: 'High',
        riskScore: 1.0,
        description: '''
使用者長按 3 秒送出緊急通報。
姓名：${profile.name}
電話：${profile.phone}
緊急聯絡人：${profile.emergencyName}
地址/備註：${profile.address}
請依狀況判斷 119、110 或同步通報。
''',
      );

      if (!mounted) {
        return;
      }

      setState(() {
        _currentLocation = location;
        _locationText = locationText;
        _statusText = '緊急通報已送出';
        _resultText =
            '緊急通報已送至 E-CARE 管理端。若有立即危險，請同步撥打 119 或 110；醫療、火災、天然災害、受困、山域或水域救援優先 119，人身威脅、犯罪或暴力事件優先 110。';
        _holdProgress = 0;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _statusText = '緊急通報送出失敗';
        _resultText = ApiService.describeError(
          error,
          action: '建立通報',
        );
        _holdProgress = 0;
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSubmittingEmergency = false;
        });
      }
    }
  }

  Future<void> _primeLocationFetch({bool force = false}) {
    if (!force && _locationText != '尚未取得位置') {
      return Future<void>.value();
    }

    final existingTask = _locationFetchTask;
    if (existingTask != null) {
      return existingTask;
    }

    late final Future<void> task;
    task = _fetchLocationOnce(
      updateStatus: force || _locationText == '尚未取得位置',
    ).whenComplete(() {
      if (identical(_locationFetchTask, task)) {
        _locationFetchTask = null;
      }
    });
    _locationFetchTask = task;
    return task;
  }

  Future<void> _fetchLocationOnce({bool updateStatus = true}) async {
    if (updateStatus && mounted) {
      setState(() {
        _statusText = '正在取得位置...';
      });
    }

    try {
      final location = await _locationService.getCurrentLocation();
      if (!mounted) {
        return;
      }
      setState(() {
        _currentLocation = location;
        _locationText = _locationDisplayText(location);
        _statusText = '已更新位置';
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _statusText = '無法取得位置';
        _resultText = '定位失敗，請確認裝置已開啟定位與權限；山區可改用地標、步道名稱或座標口頭通報。';
      });
    }
  }

  String _locationDisplayText(LocationSnapshot location) {
    final address = location.address?.trim();
    if (address != null && address.isNotEmpty) {
      final suffix = _isSpecificAddress(address) ? '' : '附近';
      return '$address$suffix (+/- ${location.accuracy.round()}m)';
    }

    return location.toDisplayText();
  }

  bool _isSpecificAddress(String address) {
    return RegExp(r'[路街巷弄號村里鄉鎮區市縣]').hasMatch(address);
  }

  Future<void> _handleEmergencyPress() async {
    if (_isHolding || _isSubmittingEmergency) {
      return;
    }

    setState(() {
      _isHolding = true;
      _holdProgress = 0;
    });

    for (var index = 1; index <= 30; index += 1) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
      if (!mounted || !_isHolding) {
        return;
      }
      setState(() {
        _holdProgress = index / 30;
      });
    }

    if (!mounted) {
      return;
    }

    setState(() {
      _isHolding = false;
    });
    await _confirmEmergencyFlow();
  }

  void _cancelEmergencyPress() {
    if (!_isHolding) {
      return;
    }
    setState(() {
      _isHolding = false;
      _holdProgress = 0;
    });
  }

  Future<void> _openTel119() async {
    await launchUrl(Uri.parse('tel:119'));
  }

  Future<void> _openTel110() async {
    await launchUrl(Uri.parse('tel:110'));
  }

  Future<void> _confirmEmergencyFlow() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('送出緊急通報？'),
          content: const Text(
            '系統會將目前位置與個人資料送至 E-CARE 管理端。若已有人受傷、受困或有立即危險，請不要等待，直接撥打 119 或 110。',
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('取消'),
            ),
            FilledButton.icon(
              onPressed: () => Navigator.of(context).pop(true),
              icon: const Icon(Icons.crisis_alert_rounded),
              label: const Text('送出通報'),
            ),
          ],
        );
      },
    );

    if (confirmed == true) {
      await _startEmergencyFlow();
    } else if (mounted) {
      setState(() {
        _statusText = '待命中';
        _holdProgress = 0;
      });
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
        color: const Color(0xFFF5EFE4),
        child: SafeArea(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 960),
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 18, 16, 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    _Header(welcomeText: _welcomeText),
                    const SizedBox(height: 16),
                    _EmergencyCard(
                      isHolding: _isHolding,
                      isSubmitting: _isSubmittingEmergency,
                      holdProgress: _holdProgress,
                      onLongPressStart: _handleEmergencyPress,
                      onLongPressEnd: _cancelEmergencyPress,
                    ),
                    const SizedBox(height: 14),
                    const _DispatchHint(),
                    const SizedBox(height: 16),
                    LayoutBuilder(
                      builder:
                          (BuildContext context, BoxConstraints constraints) {
                        final wide = constraints.maxWidth >= 760;
                        final chatTile = _BigTile(
                          icon: Icons.support_agent_rounded,
                          label: '救援對話',
                          subtitle: '不知道該怎麼辦時，先從這裡說',
                          onTap: () {
                            Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => const ChatScreen(),
                              ),
                            );
                          },
                        );
                        final sideActions = Column(
                          children: <Widget>[
                            _ListTileButton(
                              icon: Icons.article_outlined,
                              label: '通報紀錄',
                              onTap: () {
                                Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) => const RecordsScreen(),
                                  ),
                                );
                              },
                            ),
                            const SizedBox(height: 10),
                            _ListTileButton(
                              icon: Icons.person_outline_rounded,
                              label: '個人資料',
                              onTap: () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) => const ProfileScreen(),
                                  ),
                                );
                                await _loadProfile();
                              },
                            ),
                          ],
                        );

                        if (!wide) {
                          return Column(
                            children: <Widget>[
                              chatTile,
                              const SizedBox(height: 10),
                              sideActions,
                            ],
                          );
                        }

                        return Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Expanded(flex: 5, child: chatTile),
                            const SizedBox(width: 12),
                            Expanded(flex: 4, child: sideActions),
                          ],
                        );
                      },
                    ),
                    const SizedBox(height: 16),
                    _LocationPanel(
                      locationText: _locationText,
                      statusText: _statusText,
                      resultText: _resultText,
                      loadingLocation: _locationFetchTask != null,
                      onRefreshLocation: () {
                        unawaited(_primeLocationFetch(force: true));
                      },
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      alignment: WrapAlignment.center,
                      spacing: 10,
                      runSpacing: 8,
                      children: <Widget>[
                        FilledButton.icon(
                          onPressed: _openTel119,
                          icon:
                              const Icon(Icons.local_fire_department_outlined),
                          label: const Text('撥打 119'),
                          style: FilledButton.styleFrom(
                            backgroundColor: EcareApp.primary,
                            foregroundColor: Colors.white,
                          ),
                        ),
                        OutlinedButton.icon(
                          onPressed: _openTel110,
                          icon: const Icon(Icons.local_police_outlined),
                          label: const Text('撥打 110'),
                        ),
                      ],
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

class _Header extends StatelessWidget {
  const _Header({required this.welcomeText});

  final String welcomeText;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: <Widget>[
        const Text(
          'E-CARE',
          style: TextStyle(
            fontSize: 34,
            fontWeight: FontWeight.w900,
            letterSpacing: 0,
            color: EcareApp.text,
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          '救援助理',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 18,
            color: EcareApp.text,
            fontWeight: FontWeight.w700,
          ),
        ),
        if (welcomeText.isNotEmpty) ...<Widget>[
          const SizedBox(height: 6),
          Text(
            welcomeText,
            style: const TextStyle(color: EcareApp.muted),
          ),
        ],
      ],
    );
  }
}

class _EmergencyCard extends StatelessWidget {
  const _EmergencyCard({
    required this.isHolding,
    required this.isSubmitting,
    required this.holdProgress,
    required this.onLongPressStart,
    required this.onLongPressEnd,
  });

  final bool isHolding;
  final bool isSubmitting;
  final double holdProgress;
  final VoidCallback onLongPressStart;
  final VoidCallback onLongPressEnd;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onLongPressStart: (_) => onLongPressStart(),
      onLongPressEnd: (_) => onLongPressEnd(),
      child: Container(
        decoration: BoxDecoration(
          color: EcareApp.primary,
          borderRadius: BorderRadius.circular(18),
          boxShadow: const <BoxShadow>[
            BoxShadow(
              color: Color.fromRGBO(0, 0, 0, 0.14),
              blurRadius: 22,
              offset: Offset(0, 10),
            ),
          ],
        ),
        padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.14),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: const Icon(
                    Icons.crisis_alert_rounded,
                    color: Colors.white,
                    size: 30,
                  ),
                ),
                const SizedBox(width: 14),
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        '緊急通報',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 28,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      SizedBox(height: 4),
                      Text(
                        '長按 3 秒送出位置與個人資料',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: LinearProgressIndicator(
                value: holdProgress,
                minHeight: 8,
                backgroundColor: Colors.white.withValues(alpha: 0.2),
                color: Colors.white,
              ),
            ),
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerRight,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  isSubmitting
                      ? '送出中...'
                      : isHolding
                          ? '保持按住，正在確認...'
                          : '長按啟動',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DispatchHint extends StatelessWidget {
  const _DispatchHint();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: const <Widget>[
        Expanded(
          child: _DispatchChip(
            icon: Icons.local_fire_department_outlined,
            title: '119',
            text: '醫療、火災、天然災害、受困、山域/水域救援',
            color: Color(0xFFC95A4A),
          ),
        ),
        SizedBox(width: 10),
        Expanded(
          child: _DispatchChip(
            icon: Icons.local_police_outlined,
            title: '110',
            text: '人身威脅、暴力、犯罪或治安事件',
            color: Color(0xFF2F5D50),
          ),
        ),
      ],
    );
  }
}

class _DispatchChip extends StatelessWidget {
  const _DispatchChip({
    required this.icon,
    required this.title,
    required this.text,
    required this.color,
  });

  final IconData icon;
  final String title;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 78),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.22)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, color: color, size: 22),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  title,
                  style: TextStyle(
                    color: color,
                    fontWeight: FontWeight.w900,
                    fontSize: 18,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: const TextStyle(
                    color: EcareApp.muted,
                    fontSize: 12,
                    height: 1.35,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _BigTile extends StatelessWidget {
  const _BigTile({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFFFFD98C),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          child: Row(
            children: <Widget>[
              Container(
                width: 54,
                height: 54,
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.06),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, size: 30, color: EcareApp.text),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      label,
                      style: const TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w900,
                        color: EcareApp.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        color: EcareApp.muted,
                        fontSize: 13,
                        height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: EcareApp.text),
            ],
          ),
        ),
      ),
    );
  }
}

class _ListTileButton extends StatelessWidget {
  const _ListTileButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 15),
          child: Row(
            children: <Widget>[
              SizedBox(width: 38, child: Icon(icon, color: EcareApp.text)),
              Expanded(
                child: Text(
                  label,
                  style: const TextStyle(
                    fontSize: 19,
                    fontWeight: FontWeight.w800,
                    color: EcareApp.text,
                  ),
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: EcareApp.text),
            ],
          ),
        ),
      ),
    );
  }
}

class _LocationPanel extends StatelessWidget {
  const _LocationPanel({
    required this.locationText,
    required this.statusText,
    required this.resultText,
    required this.loadingLocation,
    required this.onRefreshLocation,
  });

  final String locationText;
  final String statusText;
  final String resultText;
  final bool loadingLocation;
  final VoidCallback onRefreshLocation;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE1D5C5)),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.my_location_rounded,
                  size: 18, color: EcareApp.primary),
              const SizedBox(width: 7),
              const Expanded(
                child: Text(
                  '位置與通報狀態',
                  style: TextStyle(
                    color: EcareApp.text,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              TextButton.icon(
                onPressed: loadingLocation ? null : onRefreshLocation,
                icon: const Icon(Icons.gps_fixed_rounded, size: 16),
                label: Text(loadingLocation ? '取得中...' : '更新位置'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _InfoRow(label: '位置', value: locationText, mono: true),
          const SizedBox(height: 8),
          _InfoRow(label: '狀態', value: statusText),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            decoration: BoxDecoration(
              color: const Color(0xFFF9F5EE),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFE5D8C7)),
            ),
            padding: const EdgeInsets.all(12),
            child: Text(
              resultText,
              style: const TextStyle(
                color: EcareApp.muted,
                height: 1.55,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.label,
    required this.value,
    this.mono = false,
  });

  final String label;
  final String value;
  final bool mono;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        SizedBox(
          width: 44,
          child: Text(
            label,
            style: const TextStyle(
              color: EcareApp.muted,
              fontSize: 13,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: TextStyle(
              color: EcareApp.text,
              height: 1.45,
              fontFamily: mono ? 'monospace' : null,
            ),
          ),
        ),
      ],
    );
  }
}
