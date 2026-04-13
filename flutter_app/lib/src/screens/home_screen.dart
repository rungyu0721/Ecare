import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app.dart';
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
  String _locationText = '\u5c1a\u672a\u53d6\u5f97\u4f4d\u7f6e';
  String _statusText = '\u5f85\u547d\u4e2d';
  String _resultText =
      '\u9577\u6309 3 \u79d2\u5373\u53ef\u555f\u52d5\u7dca\u6025\u901a\u5831\u3002\u7cfb\u7d71\u6703\u6574\u7406\u4f4d\u7f6e\u8207\u500b\u4eba\u8cc7\u6599\uff0c\u65b9\u4fbf\u4f60\u5f8c\u7e8c\u901a\u5831\u3002';
  bool _loading = true;
  bool _isHolding = false;
  double _holdProgress = 0;
  Future<void>? _locationFetchTask;

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
        _welcomeText = refreshed == null ? '' : '\u60a8\u597d\uff0c${refreshed.name}';
        _loading = false;
        _resultText = refreshed == null
            ? '\u8acb\u5148\u5b8c\u6210\u500b\u4eba\u8cc7\u6599\u8a2d\u5b9a\uff0c\u4e4b\u5f8c\u9047\u5230\u7dca\u6025\u72c0\u6cc1\u6642\u624d\u80fd\u5feb\u901f\u5e36\u5165\u8cc7\u8a0a\u3002'
            : '\u76ee\u524d\u8cc7\u6599\u5df2\u6e96\u5099\u5b8c\u6210\uff1a${refreshed.name} / ${refreshed.phone}';
      });
      unawaited(_primeLocationFetch());
      return;
    }

    setState(() {
      _profile = profile;
      _welcomeText = '\u60a8\u597d\uff0c${profile.name}';
      _loading = false;
      _resultText = '\u76ee\u524d\u8cc7\u6599\u5df2\u6e96\u5099\u5b8c\u6210\uff1a${profile.name} / ${profile.phone}';
    });
    unawaited(_primeLocationFetch());
  }

  Future<void> _startEmergencyFlow() async {
    final profile = _profile;
    if (profile == null) {
      return;
    }

    setState(() {
      _statusText = '\u6b63\u5728\u6574\u7406\u7dca\u6025\u8cc7\u8a0a...';
    });

    try {
      final location = await _locationService.getCurrentLocation();
      final locationText = location.toDisplayText();

      await _apiService.createReport(
        title: '\u7dca\u6025\u901a\u5831',
        category: '\u7dca\u6025\u4e8b\u4ef6',
        location: locationText,
        riskLevel: 'High',
        riskScore: 1.0,
        description:
            '\u4f7f\u7528\u8005\u9577\u6309 3 \u79d2\u555f\u52d5\u7dca\u6025\u901a\u5831\u3002\n\u59d3\u540d\uff1a${profile.name}\n\u96fb\u8a71\uff1a${profile.phone}\n\u7dca\u6025\u806f\u7d61\u4eba\uff1a${profile.emergencyName}\n\u5730\u5740\uff1a${profile.address}',
      );

      if (!mounted) {
        return;
      }

      setState(() {
        _locationText = locationText;
        _statusText = '\u7dca\u6025\u901a\u5831\u5df2\u9001\u51fa';
        _resultText =
            '\u7cfb\u7d71\u5df2\u5efa\u7acb\u4e00\u7b46\u9ad8\u98a8\u96aa\u901a\u5831\uff0c\u82e5\u60c5\u6cc1\u5371\u6025\uff0c\u8acb\u7acb\u5373\u64a5\u6253 110 \u6216 119\u3002';
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _statusText = '\u7dca\u6025\u901a\u5831\u5931\u6557';
        _resultText = ApiService.describeError(
          error,
          action: '\u9001\u51fa\u901a\u5831',
        );
      });
    }
  }

  Future<void> _primeLocationFetch({bool force = false}) {
    if (!force && _locationText != '\u5c1a\u672a\u53d6\u5f97\u4f4d\u7f6e') {
      return Future<void>.value();
    }

    final existingTask = _locationFetchTask;
    if (existingTask != null) {
      return existingTask;
    }

    late final Future<void> task;
    task = _fetchLocationOnce(
      updateStatus: force || _locationText == '\u5c1a\u672a\u53d6\u5f97\u4f4d\u7f6e',
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
        _statusText = '\u6b63\u5728\u53d6\u5f97\u4f4d\u7f6e...';
      });
    }

    try {
      final location = await _locationService.getCurrentLocation();
      if (!mounted) {
        return;
      }
      setState(() {
        _locationText = location.toDisplayText();
        _statusText = '\u5df2\u66f4\u65b0\u4f4d\u7f6e';
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _statusText = '\u7121\u6cd5\u53d6\u5f97\u4f4d\u7f6e';
        _resultText =
            '\u5b9a\u4f4d\u5931\u6557\uff0c\u8acb\u78ba\u8a8d\u88dd\u7f6e\u5df2\u958b\u555f\u5b9a\u4f4d\u8207\u6b0a\u9650\u3002';
      });
    }
  }

  Future<void> _handleEmergencyPress() async {
    if (_isHolding) {
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

  Future<void> _openTel() async {
    await launchUrl(Uri.parse('tel:110'));
  }

  Future<void> _confirmEmergencyFlow() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('\u78ba\u8a8d\u9001\u51fa\u7dca\u6025\u901a\u5831'),
          content: const Text(
            '\u7cfb\u7d71\u5c07\u4f7f\u7528\u4f60\u7684\u500b\u4eba\u8cc7\u6599\u8207\u76ee\u524d\u4f4d\u7f6e\u5efa\u7acb\u4e00\u7b46\u7dca\u6025\u901a\u5831\uff0c\u78ba\u5b9a\u8981\u7e7c\u7e8c\u55ce\uff1f',
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('\u53d6\u6d88'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('\u78ba\u8a8d\u9001\u51fa'),
            ),
          ],
        );
      },
    );

    if (confirmed == true) {
      await _startEmergencyFlow();
    } else if (mounted) {
      setState(() {
        _statusText = '\u5f85\u547d\u4e2d';
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
              constraints: const BoxConstraints(maxWidth: 920),
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 18, 16, 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    Center(
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
                            '\u667a\u6167\u7dca\u6025\u4e8b\u4ef6\u52a9\u624b',
                            style: TextStyle(fontSize: 18, color: EcareApp.text),
                          ),
                          if (_welcomeText.isNotEmpty) ...<Widget>[
                            const SizedBox(height: 8),
                            Text(
                              _welcomeText,
                              style: const TextStyle(color: EcareApp.muted),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    GestureDetector(
                      onLongPressStart: (_) => _handleEmergencyPress(),
                      onLongPressEnd: (_) => _cancelEmergencyPress(),
                      child: Container(
                        decoration: BoxDecoration(
                          gradient: const LinearGradient(
                            colors: <Color>[EcareApp.primary, EcareApp.primaryDark],
                            begin: Alignment.topCenter,
                            end: Alignment.bottomCenter,
                          ),
                          borderRadius: BorderRadius.circular(22),
                          boxShadow: const <BoxShadow>[
                            BoxShadow(
                              color: Color.fromRGBO(0, 0, 0, 0.12),
                              blurRadius: 26,
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
                                  width: 54,
                                  height: 54,
                                  decoration: BoxDecoration(
                                    color: Colors.white.withValues(alpha: 0.12),
                                    borderRadius: BorderRadius.circular(16),
                                  ),
                                  child: const Icon(
                                    Icons.emergency,
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
                                        '\u7dca\u6025\u901a\u5831',
                                        style: TextStyle(
                                          color: Colors.white,
                                          fontSize: 30,
                                          fontWeight: FontWeight.w800,
                                        ),
                                      ),
                                      SizedBox(height: 4),
                                      Text(
                                        '\u9577\u6309 3 \u79d2\u5373\u53ef\u9001\u51fa',
                                        style: TextStyle(
                                          color: Colors.white,
                                          fontSize: 18,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            ClipRRect(
                              borderRadius: BorderRadius.circular(999),
                              child: LinearProgressIndicator(
                                value: _holdProgress,
                                minHeight: 8,
                                backgroundColor: Colors.white.withValues(alpha: 0.18),
                                color: Colors.white,
                              ),
                            ),
                            const SizedBox(height: 10),
                            Align(
                              alignment: Alignment.centerRight,
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 8,
                                ),
                                decoration: BoxDecoration(
                                  color: Colors.black.withValues(alpha: 0.18),
                                  borderRadius: BorderRadius.circular(999),
                                ),
                                child: Text(
                                  _isHolding
                                      ? '\u8acb\u7e7c\u7e8c\u9577\u6309...'
                                      : '\u9577\u6309 3 \u79d2\u555f\u52d5',
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 12,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    LayoutBuilder(
                      builder: (BuildContext context, BoxConstraints constraints) {
                        final wide = constraints.maxWidth >= 760;
                        if (!wide) {
                          return Column(
                            children: <Widget>[
                              _BigTile(
                                icon: Icons.support_agent,
                                label: 'E-CARE',
                                onTap: () {
                                  Navigator.of(context).push(
                                    MaterialPageRoute<void>(builder: (_) => const ChatScreen()),
                                  );
                                },
                              ),
                              const SizedBox(height: 12),
                              _ListTileButton(
                                icon: Icons.article_outlined,
                                label: '\u901a\u5831\u7d00\u9304',
                                onTap: () {
                                  Navigator.of(context).push(
                                    MaterialPageRoute<void>(builder: (_) => const RecordsScreen()),
                                  );
                                },
                              ),
                              const SizedBox(height: 12),
                              _ListTileButton(
                                icon: Icons.person_outline,
                                label: '\u500b\u4eba\u8cc7\u6599',
                                onTap: () async {
                                  await Navigator.of(context).push(
                                    MaterialPageRoute<void>(builder: (_) => const ProfileScreen()),
                                  );
                                  await _loadProfile();
                                },
                              ),
                            ],
                          );
                        }

                        return Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Expanded(
                              flex: 5,
                              child: _BigTile(
                                icon: Icons.support_agent,
                                label: 'E-CARE',
                                onTap: () {
                                  Navigator.of(context).push(
                                    MaterialPageRoute<void>(builder: (_) => const ChatScreen()),
                                  );
                                },
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              flex: 4,
                              child: Column(
                                children: <Widget>[
                                  _ListTileButton(
                                    icon: Icons.article_outlined,
                                    label: '\u901a\u5831\u7d00\u9304',
                                    onTap: () {
                                      Navigator.of(context).push(
                                        MaterialPageRoute<void>(builder: (_) => const RecordsScreen()),
                                      );
                                    },
                                  ),
                                  const SizedBox(height: 12),
                                  _ListTileButton(
                                    icon: Icons.person_outline,
                                    label: '\u500b\u4eba\u8cc7\u6599',
                                    onTap: () async {
                                      await Navigator.of(context).push(
                                        MaterialPageRoute<void>(builder: (_) => const ProfileScreen()),
                                      );
                                      await _loadProfile();
                                    },
                                  ),
                                ],
                              ),
                            ),
                          ],
                        );
                      },
                    ),
                    const SizedBox(height: 16),
                    Container(
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.35),
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(
                          color: const Color.fromRGBO(58, 42, 29, 0.12),
                        ),
                      ),
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        children: <Widget>[
                          Align(
                            alignment: Alignment.centerRight,
                            child: TextButton.icon(
                              onPressed: _locationFetchTask != null
                                  ? null
                                  : () {
                                      unawaited(_primeLocationFetch(force: true));
                                    },
                              icon: const Icon(Icons.my_location, size: 16),
                              label: Text(
                                _locationFetchTask != null
                                    ? '\u53d6\u5f97\u4e2d...'
                                    : '\u66f4\u65b0\u4f4d\u7f6e',
                              ),
                            ),
                          ),
                          _InfoRow(
                            label: '\u4f4d\u7f6e',
                            value: _locationText,
                            mono: true,
                          ),
                          const SizedBox(height: 8),
                          _InfoRow(label: '\u72c0\u614b', value: _statusText),
                          const SizedBox(height: 10),
                          Container(
                            width: double.infinity,
                            decoration: BoxDecoration(
                              color: Colors.white.withValues(alpha: 0.65),
                              borderRadius: BorderRadius.circular(14),
                              border: Border.all(
                                color: const Color.fromRGBO(58, 42, 29, 0.12),
                              ),
                            ),
                            padding: const EdgeInsets.all(14),
                            child: Text(
                              _resultText,
                              style: const TextStyle(
                                color: EcareApp.muted,
                                height: 1.6,
                                fontSize: 13,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 18),
                    Center(
                      child: TextButton(
                        onPressed: _openTel,
                        child: const Text('\u76f4\u63a5\u64a5\u6253 110'),
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

class _BigTile extends StatelessWidget {
  const _BigTile({
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
      color: const Color(0xFFF7D28E),
      borderRadius: BorderRadius.circular(22),
      child: InkWell(
        borderRadius: BorderRadius.circular(22),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
          child: Row(
            children: <Widget>[
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.06),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Icon(icon, size: 32, color: EcareApp.text),
              ),
              const SizedBox(width: 14),
              Text(
                label,
                style: const TextStyle(
                  fontSize: 34,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 3,
                  color: EcareApp.text,
                ),
              ),
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
      color: Colors.white.withValues(alpha: 0.55),
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 16),
          child: Row(
            children: <Widget>[
              SizedBox(width: 40, child: Icon(icon, color: EcareApp.text)),
              Expanded(
                child: Text(
                  label,
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: EcareApp.text,
                  ),
                ),
              ),
              const Icon(Icons.chevron_right, color: EcareApp.text),
            ],
          ),
        ),
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
          width: 56,
          child: Text(
            label,
            style: const TextStyle(color: EcareApp.muted, fontSize: 13),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: TextStyle(
              color: EcareApp.text,
              height: 1.5,
              fontFamily: mono ? 'monospace' : null,
            ),
          ),
        ),
      ],
    );
  }
}
