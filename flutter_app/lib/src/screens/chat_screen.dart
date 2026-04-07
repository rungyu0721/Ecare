import 'dart:io';

import 'package:flutter/material.dart';

import '../app.dart';
import '../models/audio_models.dart';
import '../models/chat_models.dart';
import '../models/location_models.dart';
import '../services/api_service.dart';
import '../services/audio_service.dart';
import '../services/location_service.dart';
import '../widgets/risk_banner.dart';
import 'records_screen.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  static const String _assistantGreeting =
      '\u60a8\u597d\uff0c\u6211\u662f E-CARE\uff0c\u8acb\u554f\u73fe\u5728\u767c\u751f\u4e86\u4ec0\u9ebc\u4e8b\uff1f\n\u6211\u6703\u4e00\u6b65\u6b65\u5354\u52a9\u60a8\u3002';

  final ApiService _apiService = ApiService();
  final AudioService _audioService = AudioService();
  final LocationService _locationService = LocationService();
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  final List<ChatMessage> _history = <ChatMessage>[
    const ChatMessage(role: 'assistant', content: _assistantGreeting),
  ];

  ChatResponse? _latestResponse;
  AudioAnalysis? _latestAudio;
  LocationSnapshot? _currentLocation;
  bool _isSending = false;
  bool _isRecording = false;

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    _audioService.dispose();
    super.dispose();
  }

  Future<void> _sendMessage({String? textOverride, AudioAnalysis? audio}) async {
    final text = (textOverride ?? _inputController.text).trim();
    if (text.isEmpty || _isSending) {
      return;
    }

    setState(() {
      _isSending = true;
      if (textOverride == null) {
        _inputController.clear();
      }
      _history.add(ChatMessage(role: 'user', content: text));
    });

    _scrollToBottom();
    await _tryFetchLocation();

    try {
      final audioContext = <String, dynamic>{
        ...?audio?.toAudioContext(),
        if (_currentLocation != null)
          'client_location': <String, dynamic>{
            'latitude': _currentLocation!.latitude,
            'longitude': _currentLocation!.longitude,
            'accuracy': _currentLocation!.accuracy,
            'address': _currentLocation!.address,
            'display_text': _currentLocation!.toDisplayText(),
          },
      };

      final response = await _apiService.sendChat(
        messages: _history,
        audioContext: audioContext.isEmpty ? null : audioContext,
      );
      if (!mounted) {
        return;
      }

      setState(() {
        _latestResponse = response;
        _appendAssistantMessage(response.reply);
        if (_shouldAppendNextQuestion(response.reply, response.nextQuestion)) {
          _appendAssistantMessage(response.nextQuestion!);
        }
      });

      _scrollToBottom();

      if (response.shouldEscalate) {
        _showEscalationDialog(response);
      }
    } catch (error) {
      if (!mounted) {
        return;
      }
      _showSnackBar(
        ApiService.describeError(
          error,
          action: '\u804a\u5929\u8acb\u6c42',
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSending = false;
        });
      }
    }
  }

  void _appendAssistantMessage(String content) {
    final text = content.trim();
    if (text.isEmpty) {
      return;
    }

    for (int index = _history.length - 1; index >= 0; index--) {
      final message = _history[index];
      if (message.role != 'assistant') {
        continue;
      }
      if (message.content.trim() == text) {
        return;
      }
      break;
    }

    _history.add(ChatMessage(role: 'assistant', content: text));
  }

  bool _shouldAppendNextQuestion(String reply, String? nextQuestion) {
    final next = nextQuestion?.trim() ?? '';
    if (next.isEmpty) {
      return false;
    }

    final normalizedReply = _normalizeComparableText(reply);
    final normalizedNext = _normalizeComparableText(next);

    if (normalizedNext.isEmpty) {
      return false;
    }

    if (normalizedReply == normalizedNext) {
      return false;
    }

    if (normalizedReply.contains(normalizedNext) ||
        normalizedNext.contains(normalizedReply)) {
      return false;
    }

    return true;
  }

  String _normalizeComparableText(String text) {
    return text
        .replaceAll(RegExp(r'\s+'), '')
        .replaceAll(RegExp(r'[，。！？；：「」、『』（）()\-]'), '')
        .replaceAll('請問', '')
        .replaceAll('請告訴我', '')
        .replaceAll('告訴我', '')
        .replaceAll('可以先告訴我', '')
        .replaceAll('目前', '')
        .replaceAll('現在', '')
        .replaceAll('您', '')
        .replaceAll('你', '')
        .replaceAll('是否', '')
        .trim();
  }

  Future<void> _openRecords() async {
    if (!mounted) {
      return;
    }

    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const RecordsScreen()),
    );
  }

  Future<void> _tryFetchLocation() async {
    if (_currentLocation != null) {
      return;
    }

    try {
      final location = await _locationService.getCurrentLocation();
      if (!mounted) {
        return;
      }
      setState(() {
        _currentLocation = location;
      });
    } catch (_) {
      // Desktop testing can continue without location.
    }
  }

  Future<void> _toggleRecording() async {
    if (_isRecording) {
      await _stopRecordingAndSend();
      return;
    }

    try {
      final directory = Directory.systemTemp;
      final path = '${directory.path}${Platform.pathSeparator}ecare_recording.wav';
      await _audioService.startRecording(path: path);
      if (!mounted) {
        return;
      }
      setState(() {
        _isRecording = true;
      });
      _showSnackBar('\u958b\u59cb\u9304\u97f3');
    } catch (error) {
      _showSnackBar('\u7121\u6cd5\u958b\u59cb\u9304\u97f3\uff0c\u8acb\u78ba\u8a8d\u9ea5\u514b\u98a8\u6b0a\u9650\u3002');
    }
  }

  Future<void> _stopRecordingAndSend() async {
    try {
      final audioFile = await _audioService.stopToFile();
      if (!mounted) {
        return;
      }
      setState(() {
        _isRecording = false;
      });

      if (audioFile == null || !await audioFile.exists()) {
        _showSnackBar('\u6c92\u6709\u53d6\u5f97\u9304\u97f3\u6a94');
        return;
      }

      final analysis = await _apiService.uploadAudio(filePath: audioFile.path);
      if (!mounted) {
        return;
      }

      setState(() {
        _latestAudio = analysis;
      });

      if (analysis.transcript.trim().isEmpty) {
        _showSnackBar('\u6c92\u6709\u8fa8\u8b58\u5230\u8a9e\u97f3\u5167\u5bb9\uff0c\u8acb\u518d\u8a66\u4e00\u6b21');
        return;
      }

      await _sendMessage(textOverride: analysis.transcript, audio: analysis);
    } catch (error) {
      if (mounted) {
        setState(() {
          _isRecording = false;
        });
      }
      _showSnackBar(
        ApiService.describeError(
          error,
          action: '\u8a9e\u97f3\u5206\u6790',
        ),
      );
    }
  }

  Future<void> _createReportFromLatest() async {
    final latest = _latestResponse;
    if (latest == null) {
      _showSnackBar('\u76ee\u524d\u9084\u6c92\u6709\u53ef\u5efa\u7acb\u901a\u5831\u7684\u5206\u6790\u7d50\u679c');
      return;
    }

    final extracted = latest.extracted;
    final locationText = _preferredLocationText(extracted.location);

    try {
      final report = await _apiService.createReport(
        title: extracted.category ?? 'E-CARE \u901a\u5831',
        category: extracted.category ?? '\u4e00\u822c\u4e8b\u4ef6',
        location: locationText,
        riskLevel: latest.riskLevel,
        riskScore: latest.riskScore,
        description: extracted.description ?? latest.reply,
      );
      if (!mounted) {
        return;
      }
      _showSnackBar('\u5df2\u5efa\u7acb\u901a\u5831\uff1a${report.id}');
    } catch (error) {
      _showSnackBar(
        ApiService.describeError(
          error,
          action: '\u5efa\u7acb\u901a\u5831',
        ),
      );
    }
  }

  String _preferredLocationText(String? extractedLocation) {
    final normalized = extractedLocation?.trim() ?? '';
    const vagueLocations = <String>{
      '',
      '\u6211\u65c1\u908a',
      '\u65c1\u908a',
      '\u9019\u88e1',
      '\u9019\u908a',
      '\u9644\u8fd1',
      '\u73fe\u5834',
      '\u6211\u9019\u88e1',
      '\u6211\u9019\u908a',
      '\u90a3\u88e1',
      '\u90a3\u908a',
    };

    if (!vagueLocations.contains(normalized)) {
      return normalized;
    }

    return _currentLocation?.toDisplayText() ?? '\u5c1a\u672a\u53d6\u5f97\u4f4d\u7f6e';
  }

  void _showEscalationDialog(ChatResponse response) {
    showDialog<void>(
      context: context,
      builder: (BuildContext context) {
        final locationText = _preferredLocationText(response.extracted.location);
        return Dialog(
          backgroundColor: Colors.transparent,
          child: Container(
            width: 420,
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const Text(
                  '\u9ad8\u98a8\u96aa\u63d0\u9192',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                    color: EcareApp.text,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  [
                    '\u7cfb\u7d71\u5224\u65b7\u76ee\u524d\u60c5\u6cc1\u9700\u8981\u512a\u5148\u8655\u7406\u3002',
                    '\u4f4d\u7f6e\uff1a$locationText',
                    response.extracted.dispatchAdvice ??
                        '\u5efa\u8b70\u76e1\u5feb\u806f\u7e6b\u5bb6\u4eba\u3001\u5b78\u6821\u6216\u64a5\u6253\u7dca\u6025\u96fb\u8a71\u3002',
                  ].join('\n'),
                  style: const TextStyle(color: EcareApp.text, height: 1.6),
                ),
                const SizedBox(height: 10),
                const Text(
                  '\u5982\u679c\u60c5\u6cc1\u6301\u7e8c\u60e1\u5316\uff0c\u8acb\u7acb\u5373\u64a5\u6253 110 \u6216 119\u3002',
                  style: TextStyle(color: EcareApp.muted),
                ),
                const SizedBox(height: 12),
                Row(
                  children: <Widget>[
                    Expanded(
                      child: FilledButton(
                        onPressed: () async {
                          Navigator.of(context).pop();
                          await _createReportFromLatest();
                        },
                        style: FilledButton.styleFrom(
                          backgroundColor: EcareApp.primary,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10),
                          ),
                        ),
                        child: const Text('\u5efa\u7acb\u901a\u5831'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: TextButton(
                        onPressed: () => Navigator.of(context).pop(),
                        style: TextButton.styleFrom(
                          backgroundColor: const Color(0xFFF2F2F2),
                          foregroundColor: EcareApp.text,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10),
                          ),
                        ),
                        child: const Text('\u7a0d\u5f8c\u518d\u8aaa'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _showSnackBar(String message) {
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) {
        return;
      }
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: EcareApp.background,
      appBar: AppBar(
        titleSpacing: 0,
        leading: IconButton(
          onPressed: () => Navigator.of(context).maybePop(),
          icon: const Icon(Icons.arrow_back_ios_new, size: 18),
        ),
        title: const Text('E-CARE \u7dca\u6025\u52a9\u624b'),
        actions: <Widget>[
          IconButton(
            onPressed: _openRecords,
            icon: const Icon(Icons.assignment_outlined),
            tooltip: '\u901a\u5831\u7d00\u9304',
          ),
          IconButton(
            onPressed: _createReportFromLatest,
            icon: const Icon(Icons.add_task_outlined),
            tooltip: '\u5efa\u7acb\u901a\u5831',
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 940),
            child: Column(
              children: <Widget>[
                if (_latestResponse != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                    child: RiskBanner(
                      riskLevel: _latestResponse!.riskLevel,
                      riskScore: _latestResponse!.riskScore,
                    ),
                  ),
                if (_currentLocation != null || _latestAudio != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
                    child: Column(
                      children: <Widget>[
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: <Widget>[
                            if (_currentLocation != null)
                              Chip(
                                backgroundColor: Colors.white.withValues(alpha: 0.75),
                                avatar: const Icon(Icons.location_on_outlined, size: 18),
                                label: Text(_currentLocation!.toDisplayText()),
                              ),
                          ],
                        ),
                        if (_latestAudio != null) ...<Widget>[
                          const SizedBox(height: 10),
                          _VoicePreviewCard(audio: _latestAudio!),
                        ],
                      ],
                    ),
                  ),
                Expanded(
                  child: ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(15),
                    itemCount: _history.length,
                    itemBuilder: (BuildContext context, int index) {
                      final item = _history[index];
                      final isUser = item.role == 'user';

                      return Align(
                        alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 12),
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                          constraints: const BoxConstraints(maxWidth: 420),
                          decoration: BoxDecoration(
                            color: isUser ? EcareApp.primary : EcareApp.card,
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Text(
                            item.content,
                            style: TextStyle(
                              color: isUser ? Colors.white : EcareApp.text,
                              height: 1.4,
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
                  child: Container(
                    color: Colors.white,
                    padding: const EdgeInsets.all(10),
                    child: Row(
                      children: <Widget>[
                        SizedBox(
                          width: 44,
                          height: 44,
                          child: OutlinedButton(
                            onPressed: _toggleRecording,
                            style: OutlinedButton.styleFrom(
                              padding: EdgeInsets.zero,
                              side: BorderSide(
                                color: _isRecording ? EcareApp.primary : const Color(0xFFCCCCCC),
                              ),
                              backgroundColor: _isRecording ? EcareApp.primary : Colors.white,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(10),
                              ),
                            ),
                            child: Icon(
                              _isRecording ? Icons.stop : Icons.mic_none,
                              color: _isRecording ? Colors.white : EcareApp.text,
                              size: 20,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: TextField(
                            controller: _inputController,
                            minLines: 1,
                            maxLines: 4,
                            textInputAction: TextInputAction.send,
                            onSubmitted: (_) => _sendMessage(),
                            decoration: InputDecoration(
                              hintText: '\u8f38\u5165\u4f60\u73fe\u5728\u7684\u72c0\u6cc1...',
                              filled: true,
                              fillColor: Colors.white,
                              contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                              enabledBorder: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(10),
                                borderSide: const BorderSide(color: Color(0xFFCCCCCC)),
                              ),
                              focusedBorder: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(10),
                                borderSide: const BorderSide(color: EcareApp.primary),
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        SizedBox(
                          height: 44,
                          child: FilledButton(
                            onPressed: _isSending ? null : _sendMessage,
                            style: FilledButton.styleFrom(
                              backgroundColor: EcareApp.primary,
                              foregroundColor: Colors.white,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(10),
                              ),
                              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                            ),
                            child: _isSending
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(strokeWidth: 2),
                                  )
                                : const Text('\u9001\u51fa'),
                          ),
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
    );
  }
}

class _VoicePreviewCard extends StatelessWidget {
  const _VoicePreviewCard({
    required this.audio,
  });

  final AudioAnalysis audio;

  @override
  Widget build(BuildContext context) {
    final bars = List<int>.generate(18, (int index) => 10 + ((index * 7) % 24));

    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        width: 320,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: <Color>[Color(0xFF6D5DFC), Color(0xFF4D46E5)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(24),
          boxShadow: const <BoxShadow>[
            BoxShadow(
              color: Color.fromRGBO(77, 70, 229, 0.18),
              blurRadius: 20,
              offset: Offset(0, 8),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.18),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(Icons.play_arrow, color: Colors.white),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: SizedBox(
                    height: 42,
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: bars
                          .map(
                            (int height) => Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 2.5),
                              child: Container(
                                width: 6,
                                height: height.toDouble(),
                                decoration: BoxDecoration(
                                  color: Colors.white.withValues(alpha: 0.9),
                                  borderRadius: BorderRadius.circular(999),
                                ),
                              ),
                            ),
                          )
                          .toList(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                const Text(
                  '00:03',
                  style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: <Widget>[
                _VoiceActionChip(label: '\u60c5\u7dd2 ${audio.emotion}'),
                const SizedBox(width: 8),
                _VoiceActionChip(label: '\u98a8\u96aa ${audio.riskLevel}'),
              ],
            ),
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF7EA),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                audio.transcript,
                style: const TextStyle(color: EcareApp.text, height: 1.5),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _VoiceActionChip extends StatelessWidget {
  const _VoiceActionChip({
    required this.label,
  });

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white.withValues(alpha: 0.22)),
      ),
      child: Text(
        label,
        style: const TextStyle(color: Colors.white, fontSize: 13),
      ),
    );
  }
}
