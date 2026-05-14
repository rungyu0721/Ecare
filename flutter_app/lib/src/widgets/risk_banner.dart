import 'package:flutter/material.dart';

import '../app.dart';

class RiskBanner extends StatefulWidget {
  const RiskBanner({
    super.key,
    required this.riskLevel,
    required this.riskScore,
  });

  final String riskLevel;
  final double riskScore;

  @override
  State<RiskBanner> createState() => _RiskBannerState();
}

class _RiskBannerState extends State<RiskBanner>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulseController;
  late final Animation<double> _pulseOpacity;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    );
    _pulseOpacity = Tween<double>(begin: 0.25, end: 0.7).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    if (widget.riskLevel == 'High') {
      _pulseController.repeat(reverse: true);
    }
  }

  @override
  void didUpdateWidget(RiskBanner oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.riskLevel == 'High' && !_pulseController.isAnimating) {
      _pulseController.repeat(reverse: true);
    } else if (widget.riskLevel != 'High' && _pulseController.isAnimating) {
      _pulseController.stop();
      _pulseController.value = 0;
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final style = switch (widget.riskLevel) {
      'High' => (
          background: const Color(0xFFFFEBEB),
          foreground: const Color(0xFF8F2E22),
          border: const Color(0xFFD57B71),
          barColor: const Color(0xFFB83A2B),
          title: '高風險',
          label: '建議優先聯絡緊急聯絡人，必要時立即通報。',
          icon: Icons.warning_rounded,
        ),
      'Medium' => (
          background: const Color(0xFFFFF4DD),
          foreground: const Color(0xFF7A5C1C),
          border: const Color(0xFFD3B06F),
          barColor: const Color(0xFFC8882A),
          title: '中風險',
          label: '請持續補充事件細節，系統會協助判斷後續處置。',
          icon: Icons.info_outline_rounded,
        ),
      _ => (
          background: const Color(0xFFFFFFF5),
          foreground: const Color(0xFF3A2A1D),
          border: const Color(0xFFCDB89C),
          barColor: EcareApp.muted,
          title: '低風險',
          label: '目前風險較低，仍建議持續留意狀況變化。',
          icon: Icons.check_circle_outline_rounded,
        ),
    };

    final scoreBarWidth = widget.riskScore.clamp(0.0, 1.0);

    Widget banner = Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: style.background,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: style.border, width: 1.3),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(style.icon, color: style.foreground, size: 18),
              const SizedBox(width: 6),
              Text(
                style.title,
                style: TextStyle(
                  color: style.foreground,
                  fontWeight: FontWeight.w800,
                  fontSize: 15,
                  letterSpacing: 0.4,
                ),
              ),
              const Spacer(),
              Text(
                widget.riskScore.toStringAsFixed(2),
                style: TextStyle(
                  color: style.foreground,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 7),
          ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: SizedBox(
              height: 5,
              child: Stack(
                children: <Widget>[
                  Container(
                    width: double.infinity,
                    color: style.border.withValues(alpha: 0.35),
                  ),
                  FractionallySizedBox(
                    widthFactor: scoreBarWidth,
                    child: Container(color: style.barColor),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 7),
          Text(
            style.label,
            style: TextStyle(
              color: style.foreground,
              fontSize: 13,
              height: 1.4,
            ),
          ),
        ],
      ),
    );

    if (widget.riskLevel == 'High') {
      banner = AnimatedBuilder(
        animation: _pulseOpacity,
        builder: (context, child) => Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            boxShadow: <BoxShadow>[
              BoxShadow(
                color: const Color(0xFFB83A2B).withValues(alpha: _pulseOpacity.value),
                blurRadius: 18,
                spreadRadius: 1,
              ),
            ],
          ),
          child: child,
        ),
        child: banner,
      );
    }

    return banner;
  }
}
