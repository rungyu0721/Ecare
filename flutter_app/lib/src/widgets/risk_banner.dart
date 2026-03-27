import 'package:flutter/material.dart';

class RiskBanner extends StatelessWidget {
  const RiskBanner({
    super.key,
    required this.riskLevel,
    required this.riskScore,
  });

  final String riskLevel;
  final double riskScore;

  @override
  Widget build(BuildContext context) {
    final style = switch (riskLevel) {
      'High' => (
          background: const Color(0xFFFFEBEB),
          foreground: const Color(0xFF8F2E22),
          border: const Color(0xFFD57B71),
          title: '\u9ad8\u98a8\u96aa',
          label: '\u5efa\u8b70\u512a\u5148\u806f\u7e6b\u7dca\u6025\u806f\u7d61\u4eba\uff0c\u5fc5\u8981\u6642\u7acb\u5373\u901a\u5831\u3002',
        ),
      'Medium' => (
          background: const Color(0xFFFFF4DD),
          foreground: const Color(0xFF7A5C1C),
          border: const Color(0xFFD3B06F),
          title: '\u4e2d\u98a8\u96aa',
          label: '\u8acb\u6301\u7e8c\u88dc\u5145\u4e8b\u4ef6\u7d30\u7bc0\uff0c\u7cfb\u7d71\u6703\u5354\u52a9\u5224\u65b7\u5f8c\u7e8c\u8655\u7f6e\u3002',
        ),
      _ => (
          background: const Color(0xFFFFFFF5),
          foreground: const Color(0xFF3A2A1D),
          border: const Color(0xFFCDB89C),
          title: '\u4f4e\u98a8\u96aa',
          label: '\u76ee\u524d\u98a8\u96aa\u8f03\u4f4e\uff0c\u4ecd\u5efa\u8b70\u6301\u7e8c\u7559\u610f\u72c0\u6cc1\u8b8a\u5316\u3002',
        ),
    };

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: style.background,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: style.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            style.title,
            style: TextStyle(
              color: style.foreground,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.4,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            '\u98a8\u96aa\u5206\u6578 ${riskScore.toStringAsFixed(2)}',
            style: TextStyle(
              color: style.foreground,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            style.label,
            style: TextStyle(
              color: style.foreground,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}
