import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../app.dart';
import '../models/audio_models.dart';
import '../models/chat_models.dart';
import '../models/location_models.dart';
import '../models/user_profile.dart';
import '../services/api_service.dart';
import '../services/audio_playback_service.dart';
import '../services/audio_service.dart';
import '../services/location_service.dart';
import '../services/profile_service.dart';
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
  final AudioPlaybackService _audioPlaybackService = AudioPlaybackService();
  final LocationService _locationService = LocationService();
  final ProfileService _profileService = ProfileService();
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final String _sessionId = DateTime.now().millisecondsSinceEpoch.toString();

  final List<ChatMessage> _history = <ChatMessage>[
    const ChatMessage(role: 'assistant', content: _assistantGreeting),
  ];
  final List<_ChatTimelineItem> _timeline = <_ChatTimelineItem>[
    const _ChatTimelineItem.text(
      role: 'assistant',
      content: _assistantGreeting,
    ),
  ];

  ChatResponse? _latestResponse;
  AudioAnalysis? _latestAudio;
  LocationSnapshot? _currentLocation;
  Future<void>? _locationFetchTask;
  UserProfile? _profile;
  bool _isSending = false;
  bool _isSendingAudioTurn = false;
  bool _isRecording = false;
  bool _isProcessingAudio = false;
  StreamSubscription<AudioPlaybackSnapshot>? _audioPlaybackSubscription;
  AudioPlaybackSnapshot _playbackSnapshot = const AudioPlaybackSnapshot();
  Timer? _recordingTicker;
  DateTime? _recordingStartedAt;
  Duration _recordingDuration = Duration.zero;
  double _recordingDragDx = 0;
  bool _willCancelRecording = false;

  @override
  void initState() {
    super.initState();
    _loadProfileContext();
    _primeLocationFetch();
    _audioPlaybackSubscription = _audioPlaybackService.snapshots
        .listen((AudioPlaybackSnapshot snapshot) {
      if (!mounted) {
        return;
      }
      setState(() {
        _playbackSnapshot = snapshot;
      });
    });
  }

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    _recordingTicker?.cancel();
    _audioPlaybackSubscription?.cancel();
    _audioPlaybackService.dispose();
    _audioService.dispose();
    super.dispose();
  }

  Future<void> _loadProfileContext() async {
    final profile = await _profileService.loadProfile();
    if (!mounted) {
      return;
    }
    setState(() {
      _profile = profile;
    });
  }

  Future<void> _sendTextMessage() async {
    final text = _inputController.text.trim();
    if (text.isEmpty || _isSending || _isRecording || _isProcessingAudio) {
      return;
    }

    final textTurnStopwatch = Stopwatch()..start();
    final isSuccess = await _sendMessage(
      backendText: text,
      timelineItem: _ChatTimelineItem.text(role: 'user', content: text),
      clearInput: true,
    );
    textTurnStopwatch.stop();

    if (isSuccess && mounted) {
      _reportTextTurnLatency(textTurnStopwatch.elapsed);
    }
  }

  Future<bool> _sendMessage({
    required String backendText,
    required _ChatTimelineItem timelineItem,
    AudioAnalysis? audio,
    bool clearInput = false,
  }) async {
    final text = backendText.trim();
    if (text.isEmpty || _isSending || _isRecording || _isProcessingAudio) {
      return false;
    }

    setState(() {
      _isSending = true;
      _isSendingAudioTurn = timelineItem.type == _ChatTimelineItemType.audio;
      if (clearInput) {
        _inputController.clear();
      }
      _history.add(ChatMessage(role: 'user', content: text));
      _timeline.add(timelineItem);
    });

    _scrollToBottom();
    final locationFetch = _primeLocationFetch();

    try {
      if (_currentLocation == null) {
        try {
          await locationFetch.timeout(const Duration(milliseconds: 1200));
        } catch (_) {
          // Keep chat responsive if location takes longer than expected.
        }
      }

      final profile = _profile ?? await _profileService.loadProfile();
      if (mounted && profile != _profile) {
        setState(() {
          _profile = profile;
        });
      }

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
        sessionId: _sessionId,
        userContext: profile == null
            ? null
            : <String, dynamic>{
                if (profile.id != null) 'user_id': profile.id,
                if (profile.name.trim().isNotEmpty) 'name': profile.name.trim(),
                if (profile.phone.trim().isNotEmpty)
                  'phone': profile.phone.trim(),
              },
      );
      if (!mounted) {
        return false;
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
      return true;
    } catch (error) {
      if (!mounted) {
        return false;
      }
      _showSnackBar(
        ApiService.describeError(
          error,
          action: '\u804a\u5929\u8acb\u6c42',
        ),
      );
      return false;
    } finally {
      if (mounted) {
        setState(() {
          _isSending = false;
          _isSendingAudioTurn = false;
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
    _timeline.add(_ChatTimelineItem.text(role: 'assistant', content: text));
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

  Future<void> _primeLocationFetch() {
    if (_currentLocation != null) {
      return Future<void>.value();
    }

    final existingTask = _locationFetchTask;
    if (existingTask != null) {
      return existingTask;
    }

    late final Future<void> task;
    task = _tryFetchLocation().whenComplete(() {
      if (identical(_locationFetchTask, task)) {
        _locationFetchTask = null;
      }
    });
    _locationFetchTask = task;
    return task;
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
    if ((_isSending || _isProcessingAudio) && !_isRecording) {
      _showSnackBar(
          '\u8acb\u5148\u7b49\u5f85\u76ee\u524d\u7684\u8a0a\u606f\u8655\u7406\u5b8c\u6210');
      return;
    }

    if (_isRecording) {
      await _stopRecordingAndSend();
      return;
    }

    await _startRecording();
  }

  Future<void> _startRecording() async {
    try {
      await _audioPlaybackService.stop();
      final directory = Directory.systemTemp;
      final path =
          '${directory.path}${Platform.pathSeparator}ecare_recording.wav';
      await _audioService.startRecording(path: path);
      if (!mounted) {
        return;
      }
      setState(() {
        _isRecording = true;
        _recordingStartedAt = DateTime.now();
        _recordingDuration = Duration.zero;
        _recordingDragDx = 0;
        _willCancelRecording = false;
      });
      _startRecordingTicker();
      _scrollToBottom();
      _showSnackBar('\u958b\u59cb\u9304\u97f3');
    } catch (error) {
      _showSnackBar(
          '\u7121\u6cd5\u958b\u59cb\u9304\u97f3\uff0c\u8acb\u78ba\u8a8d\u9ea5\u514b\u98a8\u6b0a\u9650\u3002');
    }
  }

  Future<void> _stopRecordingAndSend() async {
    try {
      final voiceTurnStopwatch = Stopwatch()..start();
      final startedAt = _recordingStartedAt;
      _stopRecordingTicker();
      final audioFile = await _audioService.stopToFile();
      if (!mounted) {
        return;
      }
      final duration = startedAt == null
          ? _recordingDuration
          : DateTime.now().difference(startedAt);
      setState(() {
        _isRecording = false;
        _isProcessingAudio = true;
        _recordingStartedAt = null;
        _recordingDuration = Duration.zero;
        _recordingDragDx = 0;
        _willCancelRecording = false;
      });

      if (audioFile == null || !await audioFile.exists()) {
        if (mounted) {
          setState(() {
            _isProcessingAudio = false;
          });
        }
        _showSnackBar('\u6c92\u6709\u53d6\u5f97\u9304\u97f3\u6a94');
        return;
      }

      final audioAnalysisStopwatch = Stopwatch()..start();
      final analysis = (await _apiService.uploadAudio(filePath: audioFile.path))
          .copyWith(localFilePath: audioFile.path);
      audioAnalysisStopwatch.stop();
      if (!mounted) {
        return;
      }

      setState(() {
        _latestAudio = analysis;
        _isProcessingAudio = false;
      });

      if (analysis.transcript.trim().isEmpty) {
        _showSnackBar(
            '\u6c92\u6709\u8fa8\u8b58\u5230\u8a9e\u97f3\u5167\u5bb9\uff0c\u8acb\u518d\u8a66\u4e00\u6b21');
        return;
      }

      final chatReplyStopwatch = Stopwatch()..start();
      final isSuccess = await _sendMessage(
        backendText: analysis.transcript,
        audio: analysis,
        timelineItem: _ChatTimelineItem.audio(
          role: 'user',
          audio: analysis,
          duration: duration,
        ),
      );
      chatReplyStopwatch.stop();
      voiceTurnStopwatch.stop();

      if (isSuccess && mounted) {
        _reportVoiceTurnLatency(
          audioAnalysisDuration: audioAnalysisStopwatch.elapsed,
          chatReplyDuration: chatReplyStopwatch.elapsed,
          totalDuration: voiceTurnStopwatch.elapsed,
        );
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _isRecording = false;
          _isProcessingAudio = false;
          _recordingStartedAt = null;
          _recordingDuration = Duration.zero;
          _recordingDragDx = 0;
          _willCancelRecording = false;
        });
      }
      _stopRecordingTicker();
      _showSnackBar(
        ApiService.describeError(
          error,
          action: '\u8a9e\u97f3\u5206\u6790',
        ),
      );
    }
  }

  Future<void> _cancelRecording() async {
    try {
      _stopRecordingTicker();
      final audioFile = await _audioService.stopToFile();
      if (audioFile != null && await audioFile.exists()) {
        await audioFile.delete();
      }
    } catch (_) {
      // Ignore cleanup failures for cancelled drafts.
    } finally {
      if (mounted) {
        setState(() {
          _isRecording = false;
          _isProcessingAudio = false;
          _recordingStartedAt = null;
          _recordingDuration = Duration.zero;
          _recordingDragDx = 0;
          _willCancelRecording = false;
        });
      }
    }

    _showSnackBar('\u5df2\u53d6\u6d88\u9304\u97f3');
  }

  Future<void> _toggleAudioPlayback(String filePath) async {
    final file = File(filePath);
    if (!await file.exists()) {
      _showSnackBar('\u627e\u4e0d\u5230\u9019\u6bb5\u9304\u97f3\u6a94');
      return;
    }

    try {
      await _audioPlaybackService.toggle(filePath);
    } catch (_) {
      _showSnackBar('\u7121\u6cd5\u64ad\u653e\u9019\u6bb5\u9304\u97f3');
    }
  }

  Future<void> _handleRecordingLongPressStart() async {
    if (_isRecording || _isSending || _isProcessingAudio) {
      return;
    }
    await _startRecording();
  }

  void _handleRecordingLongPressMove(LongPressMoveUpdateDetails details) {
    if (!_isRecording) {
      return;
    }

    final dragDx = details.localOffsetFromOrigin.dx;
    final shouldCancel = dragDx <= -90;
    if (_recordingDragDx == dragDx && _willCancelRecording == shouldCancel) {
      return;
    }

    setState(() {
      _recordingDragDx = dragDx;
      _willCancelRecording = shouldCancel;
    });
  }

  Future<void> _handleRecordingLongPressEnd() async {
    if (!_isRecording) {
      return;
    }

    if (_willCancelRecording) {
      await _cancelRecording();
      return;
    }

    await _stopRecordingAndSend();
  }

  String? _voiceStatusText() {
    if (_isRecording) {
      if (_willCancelRecording) {
        return '\u653e\u958b\u5f8c\u5c07\u53d6\u6d88\u9019\u6bb5\u9304\u97f3';
      }
      return '\u9304\u97f3\u4e2d\uff0c\u9b06\u958b\u5c31\u6703\u9001\u51fa\uff0c\u5de6\u6ed1\u53ef\u53d6\u6d88';
    }

    if (_isProcessingAudio) {
      return '\u8a9e\u97f3\u5206\u6790\u4e2d\uff0c\u6b63\u5728\u5206\u6790\u8a9e\u97f3\u8207\u60c5\u7dd2...';
    }

    if (_isSending && _isSendingAudioTurn) {
      return '\u5df2\u6536\u5230\u8a9e\u97f3\u8a0a\u606f\uff0c\u6b63\u5728\u6839\u64da\u9019\u6bb5\u9304\u97f3\u6574\u7406\u56de\u8986...';
    }

    return null;
  }

  Color _voiceStatusColor() {
    if (_willCancelRecording) {
      return const Color(0xFF8F2E22);
    }

    if (_isRecording) {
      return EcareApp.primary;
    }

    if (_isProcessingAudio) {
      return EcareApp.primaryDark;
    }

    return EcareApp.muted;
  }

  void _startRecordingTicker() {
    _recordingTicker?.cancel();
    _recordingTicker = Timer.periodic(const Duration(milliseconds: 250), (_) {
      final startedAt = _recordingStartedAt;
      if (!mounted || startedAt == null) {
        return;
      }
      setState(() {
        _recordingDuration = DateTime.now().difference(startedAt);
      });
    });
  }

  void _stopRecordingTicker() {
    _recordingTicker?.cancel();
    _recordingTicker = null;
  }

  Future<void> _createReportFromLatest() async {
    final latest = _latestResponse;
    if (latest == null) {
      _showSnackBar(
          '\u76ee\u524d\u9084\u6c92\u6709\u53ef\u5efa\u7acb\u901a\u5831\u7684\u5206\u6790\u7d50\u679c');
      return;
    }

    final extracted = latest.extracted;
    final locationText = _preferredLocationText(extracted.location);

    try {
      final report = await _apiService.createReport(
        title: extracted.category ?? 'E-CARE \u901a\u5831',
        category: extracted.category ?? '\u4e00\u822c\u4e8b\u4ef6',
        location: locationText,
        latitude: _currentLocation?.latitude,
        longitude: _currentLocation?.longitude,
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

    return _currentLocation?.toDisplayText() ??
        '\u5c1a\u672a\u53d6\u5f97\u4f4d\u7f6e';
  }

  void _showEscalationDialog(ChatResponse response) {
    showDialog<void>(
      context: context,
      builder: (BuildContext context) {
        final locationText =
            _preferredLocationText(response.extracted.location);
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
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  void _reportVoiceTurnLatency({
    required Duration audioAnalysisDuration,
    required Duration chatReplyDuration,
    required Duration totalDuration,
  }) {
    debugPrint(
      'E-CARE voice latency -> analysis: ${_formatLatency(audioAnalysisDuration)}, '
      'chat: ${_formatLatency(chatReplyDuration)}, '
      'total: ${_formatLatency(totalDuration)}',
    );
  }

  void _reportTextTurnLatency(Duration totalDuration) {
    debugPrint(
      'E-CARE text latency -> total: ${_formatLatency(totalDuration)}',
    );
  }

  String _formatLatency(Duration duration) {
    final milliseconds = duration.inMilliseconds;
    if (milliseconds >= 1000) {
      return '${(milliseconds / 1000).toStringAsFixed(1)}\u79d2';
    }
    return '$milliseconds ms';
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
    final bannerRiskLevel =
        _latestResponse?.riskLevel ?? _latestAudio?.riskLevel;
    final bannerRiskScore =
        _latestResponse?.riskScore ?? _latestAudio?.riskScore;
    final voiceStatusText = _voiceStatusText();

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
                if (bannerRiskLevel != null && bannerRiskScore != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                    child: RiskBanner(
                      riskLevel: bannerRiskLevel,
                      riskScore: bannerRiskScore,
                    ),
                  ),
                if (_currentLocation != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: <Widget>[
                        Chip(
                          backgroundColor: Colors.white.withValues(alpha: 0.75),
                          avatar:
                              const Icon(Icons.location_on_outlined, size: 18),
                          label: Text(_currentLocation!.toDisplayText()),
                        ),
                      ],
                    ),
                  ),
                Expanded(
                  child: ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(15),
                    itemCount: _timeline.length + (_isRecording ? 1 : 0),
                    itemBuilder: (BuildContext context, int index) {
                      if (_isRecording && index == _timeline.length) {
                        return Align(
                          alignment: Alignment.centerRight,
                          child: _AudioMessageBubble.live(
                            duration: _recordingDuration,
                            willCancel: _willCancelRecording,
                          ),
                        );
                      }

                      final item = _timeline[index];
                      final isUser = item.role == 'user';

                      return Align(
                        alignment: isUser
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        child: item.when(
                          text: (String content) => Container(
                            margin: const EdgeInsets.only(bottom: 12),
                            padding: const EdgeInsets.symmetric(
                                horizontal: 14, vertical: 12),
                            constraints: const BoxConstraints(maxWidth: 420),
                            decoration: BoxDecoration(
                              color: isUser ? EcareApp.primary : EcareApp.card,
                              borderRadius: BorderRadius.circular(14),
                            ),
                            child: Text(
                              content,
                              style: TextStyle(
                                color: isUser ? Colors.white : EcareApp.text,
                                height: 1.4,
                              ),
                            ),
                          ),
                          audio: (AudioAnalysis audio, Duration duration) {
                            final audioPath = audio.localFilePath;
                            final isCurrentPlayback = audioPath != null &&
                                _playbackSnapshot.currentFilePath == audioPath;
                            return _AudioMessageBubble.sent(
                              audio: audio,
                              duration: duration,
                              isSendingReply: _isSendingAudioTurn &&
                                  _isSending &&
                                  index == _timeline.length - 1,
                              isPlaying: isCurrentPlayback &&
                                  _playbackSnapshot.isPlaying,
                              playbackPosition: isCurrentPlayback
                                  ? _playbackSnapshot.position
                                  : Duration.zero,
                              onTogglePlayback: audioPath == null
                                  ? null
                                  : () => _toggleAudioPlayback(audioPath),
                            );
                          },
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
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Row(
                          children: <Widget>[
                            SizedBox(
                              width: 48,
                              height: 48,
                              child: GestureDetector(
                                onTap: (_isSending || _isProcessingAudio) &&
                                        !_isRecording
                                    ? null
                                    : _toggleRecording,
                                onLongPressStart: (_isSending ||
                                        _isProcessingAudio ||
                                        _isRecording)
                                    ? null
                                    : (_) => _handleRecordingLongPressStart(),
                                onLongPressMoveUpdate: _isRecording
                                    ? _handleRecordingLongPressMove
                                    : null,
                                onLongPressEnd: _isRecording
                                    ? (_) => _handleRecordingLongPressEnd()
                                    : null,
                                child: AnimatedContainer(
                                  duration: const Duration(milliseconds: 180),
                                  decoration: BoxDecoration(
                                    color: _isRecording
                                        ? (_willCancelRecording
                                            ? const Color(0xFF8F2E22)
                                            : EcareApp.primary)
                                        : Colors.white,
                                    borderRadius: BorderRadius.circular(14),
                                    border: Border.all(
                                      color: _isRecording
                                          ? Colors.transparent
                                          : const Color(0xFFCCCCCC),
                                    ),
                                    boxShadow: _isRecording
                                        ? <BoxShadow>[
                                            BoxShadow(
                                              color: (_willCancelRecording
                                                      ? const Color(0xFF8F2E22)
                                                      : EcareApp.primary)
                                                  .withValues(alpha: 0.28),
                                              blurRadius: 18,
                                              offset: const Offset(0, 8),
                                            ),
                                          ]
                                        : const <BoxShadow>[],
                                  ),
                                  child: Icon(
                                    _isRecording
                                        ? (_willCancelRecording
                                            ? Icons.delete_outline
                                            : Icons.mic_rounded)
                                        : Icons.mic_none,
                                    color: _isRecording
                                        ? Colors.white
                                        : EcareApp.text,
                                    size: 22,
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: AnimatedSwitcher(
                                duration: const Duration(milliseconds: 180),
                                child: _isRecording
                                    ? _RecordingComposerStrip(
                                        key:
                                            const ValueKey<String>('recording'),
                                        duration: _recordingDuration,
                                        willCancel: _willCancelRecording,
                                        dragDx: _recordingDragDx,
                                      )
                                    : TextField(
                                        key: const ValueKey<String>(
                                            'text-input'),
                                        controller: _inputController,
                                        enabled: !_isProcessingAudio,
                                        minLines: 1,
                                        maxLines: 4,
                                        textInputAction: TextInputAction.send,
                                        onSubmitted: (_) => _sendTextMessage(),
                                        decoration: InputDecoration(
                                          hintText:
                                              '\u8f38\u5165\u4f60\u73fe\u5728\u7684\u72c0\u6cc1...',
                                          filled: true,
                                          fillColor: Colors.white,
                                          contentPadding:
                                              const EdgeInsets.symmetric(
                                                  horizontal: 12, vertical: 10),
                                          enabledBorder: OutlineInputBorder(
                                            borderRadius:
                                                BorderRadius.circular(10),
                                            borderSide: const BorderSide(
                                                color: Color(0xFFCCCCCC)),
                                          ),
                                          focusedBorder: OutlineInputBorder(
                                            borderRadius:
                                                BorderRadius.circular(10),
                                            borderSide: const BorderSide(
                                                color: EcareApp.primary),
                                          ),
                                          disabledBorder: OutlineInputBorder(
                                            borderRadius:
                                                BorderRadius.circular(10),
                                            borderSide: const BorderSide(
                                                color: Color(0xFFE3D6C5)),
                                          ),
                                        ),
                                      ),
                              ),
                            ),
                            if (!_isRecording) ...<Widget>[
                              const SizedBox(width: 8),
                              SizedBox(
                                height: 44,
                                child: FilledButton(
                                  onPressed: (_isSending || _isProcessingAudio)
                                      ? null
                                      : _sendTextMessage,
                                  style: FilledButton.styleFrom(
                                    backgroundColor: EcareApp.primary,
                                    foregroundColor: Colors.white,
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 14, vertical: 10),
                                  ),
                                  child: _isSending
                                      ? const SizedBox(
                                          width: 18,
                                          height: 18,
                                          child: CircularProgressIndicator(
                                              strokeWidth: 2),
                                        )
                                      : const Text('\u9001\u51fa'),
                                ),
                              ),
                            ] else ...<Widget>[
                              const SizedBox(width: 8),
                              AnimatedContainer(
                                duration: const Duration(milliseconds: 180),
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 8,
                                ),
                                decoration: BoxDecoration(
                                  color: _willCancelRecording
                                      ? const Color(0xFFFFE7E2)
                                      : const Color(0xFFFFF3E6),
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: Text(
                                  _willCancelRecording
                                      ? '\u653e\u958b\u53d6\u6d88'
                                      : '\u9b06\u958b\u9001\u51fa',
                                  style: TextStyle(
                                    color: _willCancelRecording
                                        ? const Color(0xFF8F2E22)
                                        : EcareApp.text,
                                    fontSize: 12,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ),
                        if (voiceStatusText != null) ...<Widget>[
                          const SizedBox(height: 8),
                          Row(
                            children: <Widget>[
                              Icon(
                                _isRecording
                                    ? Icons.graphic_eq_rounded
                                    : _isProcessingAudio
                                        ? Icons.psychology_alt_outlined
                                        : Icons.chat_bubble_outline_rounded,
                                size: 16,
                                color: _voiceStatusColor(),
                              ),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  voiceStatusText,
                                  style: TextStyle(
                                    color: _voiceStatusColor(),
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
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

enum _ChatTimelineItemType { text, audio }

class _ChatTimelineItem {
  const _ChatTimelineItem.text({
    required this.role,
    required this.content,
  })  : type = _ChatTimelineItemType.text,
        audio = null,
        duration = Duration.zero;

  const _ChatTimelineItem.audio({
    required this.role,
    required this.audio,
    required this.duration,
  })  : type = _ChatTimelineItemType.audio,
        content = null,
        assert(audio != null);

  final String role;
  final _ChatTimelineItemType type;
  final String? content;
  final AudioAnalysis? audio;
  final Duration duration;

  T when<T>({
    required T Function(String content) text,
    required T Function(AudioAnalysis audio, Duration duration) audio,
  }) {
    switch (type) {
      case _ChatTimelineItemType.text:
        return text(content ?? '');
      case _ChatTimelineItemType.audio:
        return audio(this.audio!, duration);
    }
  }
}

class _AudioMessageBubble extends StatelessWidget {
  const _AudioMessageBubble.sent({
    required this.audio,
    required this.duration,
    required this.isSendingReply,
    required this.isPlaying,
    required this.playbackPosition,
    required this.onTogglePlayback,
  })  : isLive = false,
        willCancel = false;

  const _AudioMessageBubble.live({
    required this.duration,
    required this.willCancel,
  })  : isLive = true,
        audio = null,
        isSendingReply = false,
        isPlaying = false,
        playbackPosition = Duration.zero,
        onTogglePlayback = null;

  final bool isLive;
  final AudioAnalysis? audio;
  final Duration duration;
  final bool isSendingReply;
  final bool willCancel;
  final bool isPlaying;
  final Duration playbackPosition;
  final VoidCallback? onTogglePlayback;

  String _formatDuration(Duration value) {
    final totalSeconds = value.inSeconds;
    final minutes = (totalSeconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (totalSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  List<double> _barHeights() {
    final seed = isLive
        ? duration.inMilliseconds ~/ 250
        : (isPlaying
            ? playbackPosition.inMilliseconds ~/ 180
            : duration.inMilliseconds ~/ 500);
    return List<double>.generate(
      16,
      (int index) => 10 + ((index * 7 + seed * 3) % 20).toDouble(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bars = _barHeights();
    final bubbleColor = isLive
        ? (willCancel ? const Color(0xFF8F2E22) : EcareApp.primaryDark)
        : EcareApp.primary;
    final bubbleShadow = isLive
        ? (willCancel
            ? const Color.fromRGBO(143, 46, 34, 0.28)
            : const Color.fromRGBO(184, 75, 61, 0.22))
        : const Color.fromRGBO(201, 90, 74, 0.18);
    final statusText = isLive
        ? (willCancel ? '\u653e\u958b\u5f8c\u53d6\u6d88' : '\u9304\u97f3\u4e2d')
        : isSendingReply
            ? '\u5df2\u9001\u51fa\uff0c\u5206\u6790\u4e2d'
            : isPlaying
                ? '\u64ad\u653e\u4e2d'
                : (audio?.isHighRisk ?? false)
                    ? '\u8a9e\u97f3\u8a0a\u606f\uff0c\u512a\u5148\u8655\u7406'
                    : '\u8a9e\u97f3\u8a0a\u606f';

    return GestureDetector(
      onTap: onTogglePlayback,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        constraints: const BoxConstraints(maxWidth: 360),
        decoration: BoxDecoration(
          color: bubbleColor,
          borderRadius: BorderRadius.circular(18),
          boxShadow: <BoxShadow>[
            BoxShadow(
              color: bubbleShadow,
              blurRadius: 16,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.16),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    isLive
                        ? Icons.mic_rounded
                        : isPlaying
                            ? Icons.pause_rounded
                            : Icons.play_arrow_rounded,
                    color: Colors.white,
                    size: 20,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: SizedBox(
                    height: 28,
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: bars
                          .map(
                            (double height) => Padding(
                              padding:
                                  const EdgeInsets.symmetric(horizontal: 2),
                              child: Container(
                                width: 4,
                                height: height,
                                decoration: BoxDecoration(
                                  color: Colors.white.withValues(alpha: 0.92),
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
                Text(
                  _formatDuration(isPlaying ? playbackPosition : duration),
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              statusText,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.9),
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RecordingComposerStrip extends StatelessWidget {
  const _RecordingComposerStrip({
    super.key,
    required this.duration,
    required this.willCancel,
    required this.dragDx,
  });

  final Duration duration;
  final bool willCancel;
  final double dragDx;

  String _formatDuration(Duration value) {
    final totalSeconds = value.inSeconds;
    final minutes = (totalSeconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (totalSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  List<double> _barHeights() {
    final seed = duration.inMilliseconds ~/ 180;
    return List<double>.generate(
      18,
      (int index) => 8 + ((index * 5 + seed * 3) % 18).toDouble(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bars = _barHeights();
    final clampedDx = dragDx.clamp(-120.0, 0.0);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      height: 48,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: willCancel ? const Color(0xFFFFE7E2) : const Color(0xFFFFF3E6),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: willCancel ? const Color(0xFFD97C6F) : const Color(0xFFE2C8A2),
        ),
      ),
      child: Row(
        children: <Widget>[
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(
              color: willCancel ? const Color(0xFF8F2E22) : EcareApp.primary,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            _formatDuration(duration),
            style: TextStyle(
              color: willCancel ? const Color(0xFF8F2E22) : EcareApp.text,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: bars
                  .map(
                    (double height) => Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 1.5),
                      child: Container(
                        width: 3,
                        height: height,
                        decoration: BoxDecoration(
                          color: (willCancel
                                  ? const Color(0xFF8F2E22)
                                  : EcareApp.primaryDark)
                              .withValues(alpha: 0.9),
                          borderRadius: BorderRadius.circular(999),
                        ),
                      ),
                    ),
                  )
                  .toList(),
            ),
          ),
          const SizedBox(width: 10),
          Transform.translate(
            offset: Offset(clampedDx / 5, 0),
            child: Text(
              willCancel
                  ? '\u653e\u958b\u53d6\u6d88'
                  : '\u5de6\u6ed1\u53d6\u6d88',
              style: TextStyle(
                color: willCancel ? const Color(0xFF8F2E22) : EcareApp.muted,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
