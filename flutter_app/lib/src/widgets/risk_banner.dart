import 'package:flutter/material.dart';

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
    _pulseOpacity = Tween<double>(begin: 0.18, end: 0.48).animate(
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
          background: const Color(0xFFFFEEEB),
          foreground: const Color(0xFF8F2E22),
          border: const Color(0xFFD57B71),
          barColor: const Color(0xFFB83A2B),
          title: '高風險',
          label: '請優先判斷 119 或 110。保留 GPS、地標、同行人數、傷勢、手機電量與是否受困。',
          icon: Icons.warning_rounded,
        ),
      'Medium' => (
          background: const Color(0xFFFFF6DE),
          foreground: const Color(0xFF75540F),
          border: const Color(0xFFD5B66E),
          barColor: const Color(0xFFC8882A),
          title: '中風險',
          label: '請補充位置、附近地標、是否有人受傷、能否移動，以及是否需要警消協助。',
          icon: Icons.info_outline_rounded,
        ),
      _ => (
          background: const Color(0xFFF3FAF6),
          foreground: const Color(0xFF2F5D50),
          border: const Color(0xFFB8D6C8),
          barColor: const Color(0xFF2F5D50),
          title: '低風險',
          label: '目前未偵測到立即危險，仍可持續補充狀況與位置，必要時系統會重新判斷。',
          icon: Icons.check_circle_outline_rounded,
        ),
    };

    final scoreBarWidth = widget.riskScore.clamp(0.0, 1.0);

    Widget banner = Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: style.background,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: style.border, width: 1.2),
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
                  fontWeight: FontWeight.w900,
                  fontSize: 15,
                ),
              ),
              const Spacer(),
              Text(
                widget.riskScore.toStringAsFixed(2),
                style: TextStyle(
                  color: style.foreground,
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
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
            borderRadius: BorderRadius.circular(10),
            boxShadow: <BoxShadow>[
              BoxShadow(
                color: const Color(0xFFB83A2B)
                    .withValues(alpha: _pulseOpacity.value),
                blurRadius: 14,
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
