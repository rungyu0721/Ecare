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

              return ListView.separated(
                padding: const EdgeInsets.all(14),
                itemCount: reports.length,
                separatorBuilder: (_, __) => const SizedBox(height: 14),
                itemBuilder: (BuildContext context, int index) {
                  final item = reports[index];
                  final mapUri = _mapsUri(item);

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
                              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                              decoration: BoxDecoration(
                                color: _tagColor(item.riskLevel),
                                borderRadius: BorderRadius.circular(999),
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
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                              decoration: BoxDecoration(
                                color: const Color.fromRGBO(58, 42, 29, 0.08),
                                borderRadius: BorderRadius.circular(999),
                              ),
                              child: Text(
                                item.status,
                                style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 13),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(
                          item.title.isNotEmpty ? item.title : item.category,
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w800,
                            color: EcareApp.text,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text('\u985e\u5225\uff1a${item.category}'),
                        const SizedBox(height: 4),
                        Text('\u98a8\u96aa\u5206\u6578\uff1a${item.riskScore.toStringAsFixed(2)}'),
                        const SizedBox(height: 10),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Expanded(
                              child: Text(
                                '\u4f4d\u7f6e\uff1a${item.location}',
                                style: const TextStyle(height: 1.6),
                              ),
                            ),
                            if (mapUri != null)
                              TextButton(
                                onPressed: () => launchUrl(mapUri),
                                child: const Text('\u67e5\u770b\u5730\u5716'),
                              ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.66),
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Text(
                            item.description,
                            style: const TextStyle(height: 1.6, fontWeight: FontWeight.w700),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          item.createdAt,
                          style: const TextStyle(color: EcareApp.muted, fontSize: 12),
                        ),
                      ],
                    ),
                  );
                },
              );
            },
          ),
        ),
      ),
    );
  }
}
