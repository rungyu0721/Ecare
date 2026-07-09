import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app.dart';
import '../models/report_item.dart';
import '../services/api_service.dart';

class RecordsScreen extends StatefulWidget {
  const RecordsScreen({super.key});

  @override
  State<RecordsScreen> createState() => _RecordsScreenState();
}

class _RecordsScreenState extends State<RecordsScreen> {
  final ApiService _apiService = ApiService();
  late Future<List<ReportItem>> _future;
  String _selectedCategory = '全部';

  @override
  void initState() {
    super.initState();
    _future = _apiService.fetchReports();
  }

  Color _tagColor(String level) {
    switch (level) {
      case 'High':
        return const Color(0xFFDF8B7C);
      case 'Medium':
        return const Color(0xFFF1D98D);
      default:
        return const Color(0xFFBCD8BF);
    }
  }

  Color _tagTextColor(String level) {
    switch (level) {
      case 'High':
        return const Color(0xFF4B130B);
      case 'Medium':
        return const Color(0xFF4E3A00);
      default:
        return const Color(0xFF203323);
    }
  }

  Uri? _mapsUri(ReportItem item) {
    final lat = item.latitude;
    final lng = item.longitude;
    if (lat != null && lng != null) {
      return Uri.parse('https://www.google.com/maps?q=$lat,$lng');
    }

    // fallback: try to extract (lat, lng) embedded in location string
    final match = RegExp(r'\((-?\d+\.\d+),\s*(-?\d+\.\d+)\)')
        .firstMatch(item.location);
    if (match == null) return null;
    final parsedLat = double.tryParse(match.group(1)!);
    final parsedLng = double.tryParse(match.group(2)!);
    if (parsedLat == null || parsedLng == null) return null;
    return Uri.parse('https://www.google.com/maps?q=$parsedLat,$parsedLng');
  }

  String _riskLabel(String level) {
    switch (level) {
      case 'High':
        return '\u9ad8\u98a8\u96aa';
      case 'Medium':
        return '\u4e2d\u98a8\u96aa';
      default:
        return '\u4f4e\u98a8\u96aa';
    }
  }

  List<String> _categoryOptions(List<ReportItem> reports) {
    final categories = reports
        .map((ReportItem item) => item.category.trim())
        .where((String category) => category.isNotEmpty)
        .toSet()
        .toList()
      ..sort();
    return <String>['全部', ...categories];
  }

  IconData _categoryIcon(String category) {
    if (category.contains('醫療')) return Icons.medical_services_outlined;
    if (category.contains('火災')) return Icons.local_fire_department_outlined;
    if (category.contains('天然災害')) return Icons.warning_amber_rounded;
    if (category.contains('受困救援')) return Icons.lock_outline;
    if (category.contains('自殺危機')) return Icons.support_agent_outlined;
    if (category.contains('失蹤走失')) return Icons.person_search_outlined;
    if (category.contains('山域') || category.contains('水域')) {
      return Icons.terrain_outlined;
    }
    if (category.contains('暴力')) return Icons.security_outlined;
    if (category.contains('交通')) return Icons.traffic_outlined;
    if (category.contains('可疑')) return Icons.visibility_outlined;
    if (category.contains('噪音')) return Icons.volume_up_outlined;
    return Icons.category_outlined;
  }

  Color _categoryColor(String category) {
    if (category.contains('醫療')) return const Color(0xFFE9B7AA);
    if (category.contains('火災')) return const Color(0xFFE89A74);
    if (category.contains('天然災害')) return const Color(0xFFC6D7A7);
    if (category.contains('受困救援')) return const Color(0xFFAED0D6);
    if (category.contains('自殺危機')) return const Color(0xFFD8B5D8);
    if (category.contains('失蹤走失')) return const Color(0xFFF0C66D);
    if (category.contains('山域') || category.contains('水域')) {
      return const Color(0xFFA9C8A6);
    }
    if (category.contains('暴力')) return const Color(0xFFDF8B7C);
    if (category.contains('交通')) return const Color(0xFFB6C7E3);
    if (category.contains('可疑')) return const Color(0xFFD8C6A2);
    if (category.contains('噪音')) return const Color(0xFFCDB7E9);
    return const Color.fromRGBO(58, 42, 29, 0.08);
  }

  Widget _categoryBadge(String category) {
    final display = category.trim().isEmpty ? '待確認' : category.trim();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: _categoryColor(display),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(
            _categoryIcon(display),
            size: 16,
            color: const Color(0xFF3A2A1D),
          ),
          const SizedBox(width: 6),
          Text(
            display,
            style: const TextStyle(
              color: Color(0xFF3A2A1D),
              fontWeight: FontWeight.w900,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }

  Widget _categoryFilters(List<String> categories, String selectedCategory) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 6),
      child: Row(
        children: categories.map((String category) {
          final selected = category == selectedCategory;
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              selected: selected,
              avatar: Icon(
                category == '全部' ? Icons.filter_list : _categoryIcon(category),
                size: 16,
                color: selected ? Colors.white : const Color(0xFF3A2A1D),
              ),
              label: Text(category),
              labelStyle: TextStyle(
                color: selected ? Colors.white : const Color(0xFF3A2A1D),
                fontWeight: FontWeight.w800,
              ),
              selectedColor: EcareApp.primary,
              backgroundColor: const Color(0xFFFFF6E8),
              side: const BorderSide(color: Color.fromRGBO(58, 42, 29, 0.14)),
              onSelected: (_) {
                setState(() {
                  _selectedCategory = category;
                });
              },
            ),
          );
        }).toList(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF6DEB2),
      appBar: AppBar(
        backgroundColor: const Color(0xFFF0D9A6),
        foregroundColor: EcareApp.text,
        title: const Text('\u901a\u5831\u7d00\u9304'),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 920),
          child: FutureBuilder<List<ReportItem>>(
            future: _future,
            builder: (BuildContext context, AsyncSnapshot<List<ReportItem>> snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }

              if (snapshot.hasError) {
                return const Center(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      '\u76ee\u524d\u7121\u6cd5\u8b80\u53d6\u901a\u5831\u7d00\u9304\uff0c\u8acb\u5148\u78ba\u8a8d\u5f8c\u7aef\u8207\u8cc7\u6599\u5eab\u8a2d\u5b9a\u3002',
                    ),
                  ),
                );
              }

              final reports = snapshot.data ?? <ReportItem>[];
              if (reports.isEmpty) {
                return const Center(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text('\u76ee\u524d\u6c92\u6709\u901a\u5831\u8cc7\u6599'),
                  ),
                );
              }

              final categories = _categoryOptions(reports);
              final selectedCategory = categories.contains(_selectedCategory)
                  ? _selectedCategory
                  : '全部';
              final visibleReports = selectedCategory == '全部'
                  ? reports
                  : reports
                      .where((ReportItem item) =>
                          item.category.trim() == selectedCategory)
                      .toList();

              return Column(
                children: <Widget>[
                  _categoryFilters(categories, selectedCategory),
                  if (visibleReports.isEmpty)
                    const Expanded(
                      child: Center(
                        child: Text('這個分類目前沒有通報資料'),
                      ),
                    )
                  else
                    Expanded(
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(14, 8, 14, 14),
                        itemCount: visibleReports.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 14),
                        itemBuilder: (BuildContext context, int index) {
                          final item = visibleReports[index];
                          final mapUri = _mapsUri(item);
                          final coordinateText =
                              item.latitude != null && item.longitude != null
                                  ? '${item.latitude!.toStringAsFixed(6)}, ${item.longitude!.toStringAsFixed(6)}'
                                  : null;

                          return Container(
                            decoration: BoxDecoration(
                              color: const Color(0xFFFFF6E8),
                              borderRadius: BorderRadius.circular(18),
                              boxShadow: const <BoxShadow>[
                                BoxShadow(
                                  color: Color.fromRGBO(0, 0, 0, 0.08),
                                  blurRadius: 18,
                                  offset: Offset(0, 6),
                                ),
                              ],
                            ),
                            padding: const EdgeInsets.all(14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: <Widget>[
                                Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: <Widget>[
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 12,
                                        vertical: 8,
                                      ),
                                      decoration: BoxDecoration(
                                        color: _tagColor(item.riskLevel),
                                        borderRadius:
                                            BorderRadius.circular(999),
                                      ),
                                      child: Text(
                                        '${item.id} | ${_riskLabel(item.riskLevel)}',
                                        style: TextStyle(
                                          color: _tagTextColor(item.riskLevel),
                                          fontWeight: FontWeight.w900,
                                          fontSize: 12,
                                        ),
                                      ),
                                    ),
                                    const Spacer(),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 10,
                                        vertical: 6,
                                      ),
                                      decoration: BoxDecoration(
                                        color: const Color.fromRGBO(
                                            58, 42, 29, 0.08),
                                        borderRadius:
                                            BorderRadius.circular(999),
                                      ),
                                      child: Text(
                                        item.status,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w900,
                                          fontSize: 13,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 12),
                                Text(
                                  item.title.isNotEmpty
                                      ? item.title
                                      : item.category,
                                  style: const TextStyle(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w800,
                                    color: EcareApp.text,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                _categoryBadge(item.category),
                                const SizedBox(height: 4),
                                Text(
                                  '風險分數：${item.riskScore.toStringAsFixed(2)}',
                                ),
                                const SizedBox(height: 10),
                                Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: <Widget>[
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: <Widget>[
                                          Text(
                                            '位置：${item.location}',
                                            style:
                                                const TextStyle(height: 1.6),
                                          ),
                                          if (coordinateText != null)
                                            Text(
                                              '座標：$coordinateText',
                                              style: const TextStyle(
                                                  height: 1.6),
                                            ),
                                        ],
                                      ),
                                    ),
                                    if (mapUri != null)
                                      TextButton(
                                        onPressed: () => launchUrl(mapUri),
                                        child: const Text('查看地圖'),
                                      ),
                                  ],
                                ),
                                const SizedBox(height: 10),
                                Container(
                                  width: double.infinity,
                                  padding: const EdgeInsets.all(12),
                                  decoration: BoxDecoration(
                                    color:
                                        Colors.white.withValues(alpha: 0.66),
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                  child: Text(
                                    item.description,
                                    style: const TextStyle(
                                      height: 1.6,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  item.createdAt,
                                  style: const TextStyle(
                                    color: EcareApp.muted,
                                    fontSize: 12,
                                  ),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
                    ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}
