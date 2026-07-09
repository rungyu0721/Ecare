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
import '../services/voice_prompt_service.dart';
import '../widgets/risk_banner.dart';
import 'records_screen.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  static const String _assistantGreeting =
      '您好，我是 E-CARE 救援助理。我在這裡陪您整理狀況；請直接說目前發生什麼事、位置或附近地標，我會一步步協助整理給 119/110 的重點。';

  final ApiService _apiService = ApiService();
  final AudioService _audioService = AudioService();
  final AudioPlaybackService _audioPlaybackService = AudioPlaybackService();
  final VoicePromptService _voicePromptService = VoicePromptService();
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
  bool _reportCreated = false;
  String? _activeReportId;
  bool _isRecording = false;
  bool _isProcessingAudio = false;
  StreamSubscription<AudioPlaybackSnapshot>? _audioPlaybackSubscription;
  StreamSubscription<VoicePromptSnapshot>? _voicePromptSubscription;
  AudioPlaybackSnapshot _playbackSnapshot = const AudioPlaybackSnapshot();
  VoicePromptSnapshot _voicePromptSnapshot = const VoicePromptSnapshot();
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
    _voicePromptSubscription =
        _voicePromptService.snapshots.listen((VoicePromptSnapshot snapshot) {
      if (!mounted) {
        return;
      }
      setState(() {
        _voicePromptSnapshot = snapshot;
      });
    });
  }

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    _recordingTicker?.cancel();
    _audioPlaybackSubscription?.cancel();
    _voicePromptSubscription?.cancel();
    _audioPlaybackService.dispose();
    _voicePromptService.dispose();
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

  Future<void> _sendQuickReply(String text) async {
    if (_isSending || _isRecording || _isProcessingAudio) {
      return;
    }

    await _sendMessage(
      backendText: text,
      timelineItem: _ChatTimelineItem.text(role: 'user', content: text),
    );
  }

  String _inputHintText() {
    final response = _latestResponse;
    if (response == null) {
      return '請輸入目前發生的狀況...';
    }

    final category = response.extracted.category?.trim() ?? '';
    final hasConfirmedIncident =
        category.isNotEmpty && category != '待確認' && category != '一般事件';
    final needsOngoingUpdate = hasConfirmedIncident ||
        response.riskLevel != 'Low' ||
        response.riskScore >= 0.5;

    if (needsOngoingUpdate) {
      return '回報現場新的變化...';
    }
    return '請輸入目前發生的狀況...';
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
      _timeline.add(
        const _ChatTimelineItem.text(
          role: 'assistant',
          content: 'E-CARE \u6b63\u5728\u6574\u7406\u56de\u8986...',
          isPending: true,
        ),
      );
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
        reportCreated: _reportCreated,
      );
      if (!mounted) {
        return false;
      }

      setState(() {
        _latestResponse = response;
        _removePendingAssistantMessage();
      });

      final nextQ = response.nextQuestion;
      final showNext = _shouldAppendNextQuestion(response.reply, nextQ);
      final combined = showNext && nextQ != null
          ? '${response.reply}\n\n$nextQ'
          : response.reply;
      await _appendAssistantMessageAnimated(combined);

      _scrollToBottom();
      if (response.shouldSpeak) {
        unawaited(_speakVoicePrompt(
          response.voicePrompt,
          isAutomatic: true,
          cacheKey: response.ttsCacheKey,
        ));
      }

      if (response.shouldEscalate && !_reportCreated) {
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
      setState(_removePendingAssistantMessage);
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

  void _removePendingAssistantMessage() {
    final index = _timeline.lastIndexWhere(
      (item) => item.role == 'assistant' && item.isPending,
    );
    if (index != -1) {
      _timeline.removeAt(index);
    }
  }

  Future<void> _appendAssistantMessageAnimated(String content) async {
    final text = content.trim();
    if (text.isEmpty) {
      return;
    }

    final alreadyShown = _timeline.isNotEmpty &&
        _timeline.last.role == 'assistant' &&
        (_timeline.last.content ?? '').trim() == text;
    if (alreadyShown || !mounted) {
      return;
    }

    final timelineIndex = _timeline.length;
    setState(() {
      _timeline.add(
        const _ChatTimelineItem.text(role: 'assistant', content: ''),
      );
    });
    _scrollToBottom();

    const charsPerTick = 2;
    const tickDuration = Duration(milliseconds: 18);
    for (var end = charsPerTick; end < text.length; end += charsPerTick) {
      await Future<void>.delayed(tickDuration);
      if (!mounted || timelineIndex >= _timeline.length) {
        return;
      }
      setState(() {
        _timeline[timelineIndex] = _ChatTimelineItem.text(
          role: 'assistant',
          content: text.substring(0, end),
        );
      });
      _scrollToBottom();
    }

    if (!mounted || timelineIndex >= _timeline.length) {
      return;
    }
    setState(() {
      _history.add(ChatMessage(role: 'assistant', content: text));
      _timeline[timelineIndex] = _ChatTimelineItem.text(
        role: 'assistant',
        content: text,
      );
    });
    _scrollToBottom();
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

    if (_hasSimilarQuestion(reply, next)) {
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

  bool _hasSimilarQuestion(String reply, String nextQuestion) {
    final questions = RegExp(r'[^。！？!?]+[？?]')
        .allMatches(reply)
        .map((match) => match.group(0)?.trim() ?? '')
        .where((text) => text.isNotEmpty);
    return questions.any((question) {
      final replyTopics = _questionTopics(question);
      final nextTopics = _questionTopics(nextQuestion);
      final overlap = replyTopics.intersection(nextTopics);
      if (overlap.length >= 2 || overlap.contains('detail')) {
        return true;
      }
      if (overlap.contains('disturbance') &&
          (replyTopics.contains('ongoing') || nextTopics.contains('ongoing'))) {
        return true;
      }
      if (overlap.contains('danger') &&
          (replyTopics.contains('ongoing') || nextTopics.contains('ongoing'))) {
        return true;
      }
      return false;
    });
  }

  Set<String> _questionTopics(String text) {
    final normalized =
        text.replaceAll(RegExp(r'[\s，,。！？!?、：:；;（）()「」『』]+'), '');
    final topicGroups = <String, List<String>>{
      'location': <String>['地點', '位置', '在哪', '哪裡', '地址', '路口'],
      'injury': <String>['受傷', '傷者', '流血', '送醫', '救護車'],
      'weapon': <String>['武器', '刀', '槍', '棍棒', '持刀'],
      'danger': <String>['危險', '威脅', '攻擊', '衝突', '靠近', '追', '還在現場'],
      'ongoing': <String>['持續', '還在', '仍在', '沒有停', '現在還', '平靜', '緩和', '停下'],
      'disturbance': <String>['吵架', '爭吵', '吵鬧', '噪音', '大叫', '吼叫', '摔東西'],
      'breathing': <String>['呼吸', '喘', '沒呼吸', '吸不到氣'],
      'conscious': <String>['意識', '反應', '叫得醒', '叫不醒', '清醒'],
      'fire': <String>['火', '火勢', '濃煙', '冒煙', '燃燒'],
      'traffic': <String>['車禍', '車道', '車流', '撞', '事故'],
      'detail': <String>['狀況', '發生什麼', '補充', '描述', '看到', '聽到'],
    };

    return topicGroups.entries
        .where((entry) => entry.value.any(normalized.contains))
        .map((entry) => entry.key)
        .toSet();
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
      await _voicePromptService.stop();
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
      await _voicePromptService.stop();
      await _audioPlaybackService.toggle(filePath);
    } catch (_) {
      _showSnackBar('\u7121\u6cd5\u64ad\u653e\u9019\u6bb5\u9304\u97f3');
    }
  }

  Future<void> _toggleVoicePrompt(String? prompt) async {
    if (_voicePromptSnapshot.isSpeaking) {
      await _voicePromptService.stop();
      return;
    }
    await _speakVoicePrompt(prompt);
  }

  Future<void> _speakVoicePrompt(
    String? prompt, {
    bool isAutomatic = false,
    String? cacheKey,
  }) async {
    final text = prompt?.trim() ?? '';
    if (text.isEmpty && cacheKey == null) {
      if (!isAutomatic) {
        _showSnackBar('目前沒有可播報的語音提示');
      }
      return;
    }

    try {
      await _audioPlaybackService.stop();
      if (cacheKey != null) {
        await _voicePromptService.speakFromKey(cacheKey, fallbackText: text);
      } else {
        await _voicePromptService.speak(text);
      }
    } catch (_) {
      if (!isAutomatic) {
        _showSnackBar('目前無法播報語音提示，請先看畫面文字。');
      }
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

  List<_IncidentStatusPill> _incidentStatusPills() {
    final response = _latestResponse;
    if (response == null || !_hasActionableIncident(response)) {
      return const <_IncidentStatusPill>[];
    }

    final extracted = response.extracted;
    final items = <_IncidentStatusPill>[
      _IncidentStatusPill(
        icon: Icons.category_outlined,
        label: '\u985e\u578b',
        value: _fallbackText(extracted.category, '\u5f85\u78ba\u8a8d'),
      ),
      _IncidentStatusPill(
        icon: Icons.location_on_outlined,
        label: '\u5730\u9ede',
        value: _preferredLocationText(extracted.location),
      ),
      _IncidentStatusPill(
        icon: Icons.warning_amber_rounded,
        label: '\u72c0\u614b',
        value: _dangerStatusText(extracted.dangerActive),
      ),
    ];

    if (extracted.peopleInjured != null) {
      items.add(
        _IncidentStatusPill(
          icon: Icons.medical_services_outlined,
          label: '\u50b7\u8005',
          value: extracted.peopleInjured!
              ? '\u6709\u4eba\u53d7\u50b7'
              : '\u672a\u767c\u73fe\u50b7\u8005',
        ),
      );
    }

    if (extracted.weapon != null) {
      items.add(
        _IncidentStatusPill(
          icon: Icons.report_problem_outlined,
          label: '\u5371\u96aa\u7269',
          value: extracted.weapon!
              ? '\u7591\u4f3c\u6709\u6b66\u5668'
              : '\u672a\u63d0\u5230\u6b66\u5668',
        ),
      );
    }

    final reportStatus = _reportStatusText(response.reportStatusHint);
    if (reportStatus != null) {
      items.add(
        _IncidentStatusPill(
          icon: Icons.assignment_turned_in_outlined,
          label: '通報',
          value: reportStatus,
        ),
      );
    }

    return items;
  }

  String? _reportStatusText(String? statusHint) {
    return switch (statusHint?.trim()) {
      'monitoring' => '持續觀察',
      'high_risk_detected' => '高風險已偵測',
      'report_recommended' => '建議建立通報',
      'report_created' => '通報已建立',
      'waiting_for_update' => '等待現場更新',
      'none' || null || '' => null,
      _ => '狀態更新',
    };
  }

  String _fallbackText(String? value, String fallback) {
    final trimmed = value?.trim() ?? '';
    return trimmed.isEmpty ? fallback : trimmed;
  }

  String _dangerStatusText(bool? dangerActive) {
    if (dangerActive == true) {
      return '\u6301\u7e8c\u4e2d';
    }
    if (dangerActive == false) {
      return '\u5df2\u7de9\u548c';
    }
    return '\u672a\u78ba\u8a8d';
  }

  List<_QuickReplyAction> _quickReplyActions() {
    final response = _latestResponse;
    if (response == null || !_hasActionableIncident(response)) {
      return const <_QuickReplyAction>[];
    }

    final category = response.extracted.category ?? '';
    final isHighRisk = response.riskLevel == 'High' || response.shouldEscalate;
    final isMedical = category.contains('\u91ab\u7642');
    final isRemoteRescue = category.contains('山域') || category.contains('水域');
    final isNaturalDisaster = category.contains('天然災害');
    final isTrappedRescue = category.contains('受困救援');
    final isSelfHarm = category.contains('自殺危機');
    final isMissingPerson = category.contains('失蹤走失');
    final isViolenceOrNoise =
        category.contains('\u66b4\u529b') || category.contains('\u566a\u97f3');
    final isFire = category.contains('\u706b\u707d');
    final isTraffic = category.contains('\u4ea4\u901a') ||
        category.contains('\u8eca\u798d') ||
        category.contains('\u4e8b\u6545');
    final isChildConcern = _containsChildConcern(_latestUserText());

    if (isTraffic) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(
            Icons.medical_services_outlined, '\u6709\u4eba\u53d7\u50b7'),
        _QuickReplyAction(
            Icons.traffic_outlined, '\u8eca\u9084\u5728\u8eca\u9053'),
        _QuickReplyAction(
            Icons.directions_walk_outlined, '\u5df2\u79fb\u5230\u8def\u908a'),
        _QuickReplyAction(
            Icons.phone_in_talk_outlined, '\u5df2\u64a5\u6253 110/119'),
        _QuickReplyAction(Icons.help_outline, '\u4e0d\u78ba\u5b9a'),
      ];
    }

    if (isHighRisk && (isViolenceOrNoise || isChildConcern)) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.shield_outlined, '\u6211\u5df2\u9060\u96e2'),
        _QuickReplyAction(
            Icons.medical_services_outlined, '\u6709\u4eba\u53d7\u50b7'),
        _QuickReplyAction(
            Icons.report_problem_outlined, '\u770b\u5230\u6b66\u5668'),
        _QuickReplyAction(
            Icons.phone_in_talk_outlined, '\u5df2\u64a5\u6253 110'),
      ];
    }

    if (isRemoteRescue) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.my_location_outlined, '可提供 GPS/地標'),
        _QuickReplyAction(Icons.medical_services_outlined, '有人受傷'),
        _QuickReplyAction(Icons.battery_alert_outlined, '手機快沒電'),
        _QuickReplyAction(Icons.phone_in_talk_outlined, '已撥打 119'),
        _QuickReplyAction(Icons.help_outline, '不確定'),
      ];
    }

    if (isNaturalDisaster) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.shield_outlined, '已到安全處'),
        _QuickReplyAction(Icons.warning_amber_rounded, '危險仍持續'),
        _QuickReplyAction(Icons.medical_services_outlined, '有人受困受傷'),
        _QuickReplyAction(Icons.phone_in_talk_outlined, '已撥打 119'),
        _QuickReplyAction(Icons.help_outline, '不確定'),
      ];
    }

    if (isTrappedRescue) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.location_on_outlined, '可提供樓層位置'),
        _QuickReplyAction(Icons.warning_amber_rounded, '仍受困'),
        _QuickReplyAction(Icons.medical_services_outlined, '有人不舒服'),
        _QuickReplyAction(Icons.phone_in_talk_outlined, '已撥打 119'),
        _QuickReplyAction(Icons.help_outline, '不確定'),
      ];
    }

    if (isSelfHarm) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.shield_outlined, '已保持安全距離'),
        _QuickReplyAction(Icons.warning_amber_rounded, '仍在危險位置'),
        _QuickReplyAction(Icons.medical_services_outlined, '已受傷或吞藥'),
        _QuickReplyAction(Icons.phone_in_talk_outlined, '已撥打 110/119'),
        _QuickReplyAction(Icons.help_outline, '不確定'),
      ];
    }

    if (isMissingPerson) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.location_on_outlined, '可提供最後位置'),
        _QuickReplyAction(Icons.person_search_outlined, '仍找不到人'),
        _QuickReplyAction(Icons.phone_in_talk_outlined, '已撥打 110'),
        _QuickReplyAction(Icons.medical_services_outlined, '可能受困受傷'),
        _QuickReplyAction(Icons.help_outline, '不確定'),
      ];
    }

    if (isHighRisk) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.shield_outlined, '\u6211\u5df2\u9060\u96e2'),
        _QuickReplyAction(
            Icons.medical_services_outlined, '\u6709\u4eba\u53d7\u50b7'),
        _QuickReplyAction(
            Icons.phone_in_talk_outlined, '\u5df2\u64a5\u6253 119'),
        _QuickReplyAction(Icons.help_outline, '\u4e0d\u78ba\u5b9a'),
      ];
    }

    if (isChildConcern) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.child_care_outlined, '\u9084\u5728\u54ed'),
        _QuickReplyAction(
            Icons.record_voice_over_outlined, '\u807d\u5230\u6253\u7f75'),
        _QuickReplyAction(
            Icons.medical_services_outlined, '\u6c92\u53cd\u61c9'),
        _QuickReplyAction(
            Icons.apartment_outlined, '\u5df2\u901a\u77e5\u7ba1\u7406\u54e1'),
      ];
    }

    if (isMedical) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(
            Icons.visibility_outlined, '\u610f\u8b58\u6e05\u695a'),
        _QuickReplyAction(Icons.air_outlined, '\u547c\u5438\u56f0\u96e3'),
        _QuickReplyAction(
            Icons.medical_services_outlined, '\u75c7\u72c0\u8b8a\u56b4\u91cd'),
        _QuickReplyAction(Icons.help_outline, '\u4e0d\u78ba\u5b9a'),
      ];
    }

    if (isFire) {
      return const <_QuickReplyAction>[
        _QuickReplyAction(
            Icons.directions_run_outlined, '\u5df2\u96e2\u958b\u73fe\u5834'),
        _QuickReplyAction(Icons.smoke_free_outlined, '\u6709\u6fc3\u7159'),
        _QuickReplyAction(
            Icons.group_outlined, '\u9084\u6709\u4eba\u5728\u88e1\u9762'),
        _QuickReplyAction(Icons.help_outline, '\u4e0d\u78ba\u5b9a'),
      ];
    }

    if (isViolenceOrNoise || response.riskLevel == 'Medium') {
      return const <_QuickReplyAction>[
        _QuickReplyAction(Icons.volume_up_outlined, '\u53ea\u662f\u5435\u67b6'),
        _QuickReplyAction(
            Icons.broken_image_outlined, '\u6709\u6454\u6771\u897f'),
        _QuickReplyAction(
            Icons.record_voice_over_outlined, '\u6709\u4eba\u6c42\u6551'),
        _QuickReplyAction(
            Icons.medical_services_outlined, '\u770b\u5230\u53d7\u50b7'),
        _QuickReplyAction(Icons.help_outline, '\u4e0d\u78ba\u5b9a'),
      ];
    }

    return const <_QuickReplyAction>[
      _QuickReplyAction(
          Icons.check_circle_outline, '\u60c5\u6cc1\u5df2\u7de9\u548c'),
      _QuickReplyAction(
          Icons.warning_amber_outlined, '\u60c5\u6cc1\u9084\u5728\u6301\u7e8c'),
      _QuickReplyAction(Icons.help_outline, '\u4e0d\u78ba\u5b9a'),
    ];
  }

  bool _hasActionableIncident(ChatResponse response) {
    final latestUserText = _latestUserText();
    if (_isGreetingOnly(latestUserText)) {
      return false;
    }

    final extracted = response.extracted;
    final category = extracted.category?.trim() ?? '';
    if (category.isNotEmpty &&
        category != '\u5f85\u78ba\u8a8d' &&
        category != '\u4e00\u822c\u4e8b\u4ef6') {
      return true;
    }

    if (response.riskLevel != 'Low' || response.riskScore >= 0.5) {
      return true;
    }

    if (extracted.peopleInjured != null ||
        extracted.weapon != null ||
        extracted.dangerActive != null) {
      return true;
    }

    final advice = extracted.dispatchAdvice?.trim() ?? '';
    if (advice.isNotEmpty && !advice.contains('\u5f85\u78ba\u8a8d')) {
      return true;
    }

    return _containsIncidentSignal(latestUserText);
  }

  String _latestUserText() {
    for (final message in _history.reversed) {
      if (message.role == 'user') {
        return message.content.trim();
      }
    }
    return '';
  }

  bool _isGreetingOnly(String text) {
    final normalized =
        text.toLowerCase().replaceAll(RegExp(r'[\s,，。.!！?？~～]+'), '');
    const greetings = <String>{
      '',
      '你好',
      '您好',
      '嗨',
      '哈囉',
      'hello',
      'hi',
    };
    return greetings.contains(normalized);
  }

  bool _containsIncidentSignal(String text) {
    const signals = <String>[
      '\u6025',
      '\u6551',
      '\u5c0f\u5b69',
      '\u5b69\u5b50',
      '\u5152\u7ae5',
      '\u5b30\u5152',
      '\u54ed',
      '\u6c92\u53cd\u61c9',
      '\u6c92\u6709\u53cd\u61c9',
      '\u7121\u53cd\u61c9',
      '\u53eb\u4e0d\u9192',
      '\u706b',
      '\u7159',
      '\u5435',
      '\u722d\u5435',
      '\u6253',
      '\u50b7',
      '\u6d41\u8840',
      '\u8eca\u798d',
      '\u4e8b\u6545',
      '\u53ef\u7591',
      '\u5bb3\u6015',
      '\u5371\u96aa',
      '\u95d6\u5165',
      '\u6454\u6771\u897f',
      '\u5012\u5728',
    ];
    return signals.any(text.contains);
  }

  bool _containsChildConcern(String text) {
    const childTerms = <String>[
      '\u5c0f\u5b69',
      '\u5b69\u5b50',
      '\u5152\u7ae5',
      '\u5b30\u5152',
      '\u5bf6\u5bf6',
    ];
    const distressTerms = <String>[
      '\u54ed',
      '\u54ed\u8072',
      '\u6c42\u6551',
      '\u5c16\u53eb',
      '\u54c0\u865f',
      '\u6c92\u53cd\u61c9',
      '\u53eb\u4e0d\u9192',
    ];
    return childTerms.any(text.contains) || distressTerms.any(text.contains);
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
      setState(() {
        _reportCreated = true;
        _activeReportId = report.id;
      });
      _showSnackBar('\u901a\u5831\u5df2\u5efa\u7acb\uff1a${report.id}');
    } catch (error) {
      _showSnackBar(
        ApiService.describeError(
          error,
          action: '\u5efa\u7acb\u901a\u5831',
        ),
      );
    }
  }

  Future<void> _updateReportStatus(String status) async {
    final reportId = _activeReportId;
    if (reportId == null) return;
    try {
      await _apiService.updateReportStatus(reportId, status);
    } catch (_) {
      // Status log failure is non-critical; the user message still goes through.
    }
    unawaited(_sendQuickReply(status));
  }

  String _preferredLocationText(String? extractedLocation) {
    final currentLocationText = _currentLocation?.toDisplayText();
    if (currentLocationText != null && currentLocationText.trim().isNotEmpty) {
      return currentLocationText;
    }

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

    return '\u5c1a\u672a\u53d6\u5f97\u4f4d\u7f6e';
  }

  void _showEscalationDialog(ChatResponse response) {
    showDialog<void>(
      context: context,
      builder: (BuildContext context) {
        final locationText =
            _preferredLocationText(response.extracted.location);
        final category = response.extracted.category ?? '\u5f85\u78ba\u8a8d';
        final riskLevel = response.riskLevel;
        final advice = response.extracted.dispatchAdvice?.trim() ?? '';
        final prompt = response.voicePrompt?.trim() ?? '';

        const red = Color(0xFF8F2E22);
        const redLight = Color(0xFFFFEEEB);

        return Dialog(
          backgroundColor: Colors.transparent,
          child: Container(
            width: 440,
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              boxShadow: const <BoxShadow>[
                BoxShadow(
                  color: Color.fromRGBO(0, 0, 0, 0.18),
                  blurRadius: 24,
                  offset: Offset(0, 8),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                // Header bar
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
                  decoration: const BoxDecoration(
                    color: red,
                    borderRadius: BorderRadius.only(
                      topLeft: Radius.circular(16),
                      topRight: Radius.circular(16),
                    ),
                  ),
                  child: const Row(
                    children: <Widget>[
                      Icon(Icons.crisis_alert_rounded,
                          color: Colors.white, size: 22),
                      SizedBox(width: 8),
                      Text(
                        'E-CARE 高風險救援通報',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 17,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(18, 16, 18, 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      // Category + risk chips
                      Row(
                        children: <Widget>[
                          _DialogChip(label: '\u4e8b\u4ef6', value: category),
                          const SizedBox(width: 8),
                          _DialogChip(
                            label: '\u98a8\u96aa',
                            value: switch (riskLevel) {
                              'High' => '\u9ad8\u5371',
                              'Medium' => '\u4e2d\u7b49',
                              _ => '\u4f4e',
                            },
                            accent: riskLevel == 'High',
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      // Location
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          const Icon(Icons.location_on_outlined,
                              size: 15, color: EcareApp.muted),
                          const SizedBox(width: 5),
                          Expanded(
                            child: Text(
                              locationText,
                              style: const TextStyle(
                                  color: EcareApp.text,
                                  fontSize: 13,
                                  height: 1.4),
                            ),
                          ),
                        ],
                      ),
                      if (advice.isNotEmpty) ...<Widget>[
                        const SizedBox(height: 10),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 11, vertical: 8),
                          decoration: BoxDecoration(
                            color: redLight,
                            borderRadius: BorderRadius.circular(8),
                            border:
                                Border.all(color: red.withValues(alpha: 0.3)),
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: <Widget>[
                              const Icon(Icons.directions_run_rounded,
                                  size: 14, color: red),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  advice,
                                  style: const TextStyle(
                                    color: red,
                                    fontSize: 12,
                                    fontWeight: FontWeight.w700,
                                    height: 1.45,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      if (prompt.isNotEmpty) ...<Widget>[
                        const SizedBox(height: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 11, vertical: 8),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFFF7EA),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: const Color(0xFFE5D3B5)),
                          ),
                          child: Row(
                            children: <Widget>[
                              const Icon(Icons.record_voice_over_outlined,
                                  size: 14, color: EcareApp.muted),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  prompt,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    color: EcareApp.text,
                                    fontSize: 12,
                                    height: 1.4,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      const SizedBox(height: 10),
                      const Text(
                        '系統會依事件判斷 119/110：消防、醫療、天然災害、受困救援與山域水域救援偏 119；自殺危機、失蹤走失、人身威脅或犯罪偏 110 或同步通報。',
                        style: TextStyle(color: EcareApp.muted, fontSize: 12),
                      ),
                      const SizedBox(height: 14),
                      // Action buttons
                      Row(
                        children: <Widget>[
                          Expanded(
                            child: FilledButton.icon(
                              onPressed: () async {
                                Navigator.of(context).pop();
                                await _createReportFromLatest();
                              },
                              icon:
                                  const Icon(Icons.add_task_outlined, size: 16),
                              label: const Text('\u5efa\u7acb\u901a\u5831'),
                              style: FilledButton.styleFrom(
                                backgroundColor: red,
                                foregroundColor: Colors.white,
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(10),
                                ),
                              ),
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
                      const SizedBox(height: 4),
                    ],
                  ),
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
    final incidentStatusPills = _incidentStatusPills();
    final quickReplyActions = _quickReplyActions();

    return Scaffold(
      backgroundColor: EcareApp.background,
      appBar: AppBar(
        titleSpacing: 0,
        leading: IconButton(
          onPressed: () => Navigator.of(context).maybePop(),
          icon: const Icon(Icons.arrow_back_ios_new, size: 18),
        ),
        title: const Text('E-CARE 救援助理'),
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
                if (incidentStatusPills.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                    child: _IncidentSnapshotPanel(
                      riskLevel: bannerRiskLevel ?? 'Low',
                      statusPills: incidentStatusPills,
                      dispatchAdvice: _latestResponse?.extracted.dispatchAdvice,
                      voicePrompt: _latestResponse?.voicePrompt,
                      shouldSpeak: _latestResponse?.shouldSpeak ?? false,
                      isVoiceSpeaking: _voicePromptSnapshot.isSpeaking,
                      onToggleVoicePrompt: () =>
                          _toggleVoicePrompt(_latestResponse?.voicePrompt),
                      reportCreated: _reportCreated,
                      onStatusUpdate: _updateReportStatus,
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
                      final screenWidth = MediaQuery.sizeOf(context).width;
                      final maxBubbleWidth = screenWidth < 720
                          ? screenWidth * 0.74
                          : (isUser ? screenWidth * 0.42 : screenWidth * 0.50);

                      final Widget bubble = item.when(
                        text: (String content) => Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 14, vertical: 12),
                          constraints: BoxConstraints(
                            maxWidth: maxBubbleWidth.clamp(280.0, 620.0),
                          ),
                          decoration: BoxDecoration(
                            color: isUser
                                ? EcareApp.primary
                                : item.isPending
                                    ? const Color(0xFFFFFBF5)
                                    : Colors.white,
                            borderRadius: isUser
                                ? const BorderRadius.only(
                                    topLeft: Radius.circular(16),
                                    topRight: Radius.circular(16),
                                    bottomLeft: Radius.circular(16),
                                    bottomRight: Radius.circular(4),
                                  )
                                : const BorderRadius.only(
                                    topLeft: Radius.circular(4),
                                    topRight: Radius.circular(16),
                                    bottomLeft: Radius.circular(16),
                                    bottomRight: Radius.circular(16),
                                  ),
                            boxShadow: isUser
                                ? const <BoxShadow>[
                                    BoxShadow(
                                      color: Color.fromRGBO(184, 75, 61, 0.2),
                                      blurRadius: 10,
                                      offset: Offset(0, 4),
                                    ),
                                  ]
                                : const <BoxShadow>[
                                    BoxShadow(
                                      color: Color.fromRGBO(0, 0, 0, 0.08),
                                      blurRadius: 8,
                                      offset: Offset(0, 2),
                                    ),
                                  ],
                          ),
                          child: item.isPending
                              ? const Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: <Widget>[
                                    SizedBox(
                                      width: 14,
                                      height: 14,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: EcareApp.primary,
                                      ),
                                    ),
                                    SizedBox(width: 8),
                                    Flexible(
                                      child: Text(
                                        'E-CARE \u6b63\u5728\u6574\u7406\u56de\u8986...',
                                        style: TextStyle(
                                          color: EcareApp.muted,
                                          height: 1.4,
                                        ),
                                      ),
                                    ),
                                  ],
                                )
                              : Text(
                                  content,
                                  style: TextStyle(
                                    color:
                                        isUser ? Colors.white : EcareApp.text,
                                    height: 1.55,
                                    fontSize: 15,
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
                      );

                      return Padding(
                        padding: const EdgeInsets.only(bottom: 14),
                        child: isUser
                            ? Align(
                                alignment: Alignment.centerRight,
                                child: bubble,
                              )
                            : Row(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: <Widget>[
                                  Container(
                                    width: 34,
                                    height: 34,
                                    margin: const EdgeInsets.only(right: 8),
                                    decoration: const BoxDecoration(
                                      color: EcareApp.primary,
                                      shape: BoxShape.circle,
                                    ),
                                    child: const Icon(
                                      Icons.support_agent_rounded,
                                      size: 18,
                                      color: Colors.white,
                                    ),
                                  ),
                                  Flexible(child: bubble),
                                ],
                              ),
                      );
                    },
                  ),
                ),
                Container(
                  decoration: const BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.only(
                      topLeft: Radius.circular(20),
                      topRight: Radius.circular(20),
                    ),
                    boxShadow: <BoxShadow>[
                      BoxShadow(
                        color: Color(0x12000000),
                        blurRadius: 14,
                        offset: Offset(0, -4),
                      ),
                    ],
                  ),
                  padding: const EdgeInsets.fromLTRB(12, 14, 12, 14),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      if (quickReplyActions.isNotEmpty &&
                          !_isRecording &&
                          !_isProcessingAudio) ...<Widget>[
                        _QuickReplyBar(
                          actions: quickReplyActions,
                          enabled: !_isSending,
                          onSelected: _sendQuickReply,
                        ),
                        const SizedBox(height: 10),
                      ],
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
                                      key: const ValueKey<String>('recording'),
                                      duration: _recordingDuration,
                                      willCancel: _willCancelRecording,
                                      dragDx: _recordingDragDx,
                                    )
                                  : TextField(
                                      key: const ValueKey<String>('text-input'),
                                      controller: _inputController,
                                      enabled: !_isProcessingAudio,
                                      minLines: 1,
                                      maxLines: 4,
                                      textInputAction: TextInputAction.send,
                                      onSubmitted: (_) => _sendTextMessage(),
                                      decoration: InputDecoration(
                                        hintText: _inputHintText(),
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
    this.isPending = false,
  })  : type = _ChatTimelineItemType.text,
        audio = null,
        duration = Duration.zero;

  const _ChatTimelineItem.audio({
    required this.role,
    required this.audio,
    required this.duration,
  })  : type = _ChatTimelineItemType.audio,
        content = null,
        isPending = false,
        assert(audio != null);

  final String role;
  final _ChatTimelineItemType type;
  final String? content;
  final AudioAnalysis? audio;
  final Duration duration;
  final bool isPending;

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

class _IncidentStatusPill {
  const _IncidentStatusPill({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;
}

class _QuickReplyAction {
  const _QuickReplyAction(this.icon, this.text);

  final IconData icon;
  final String text;
}

class _IncidentSnapshotPanel extends StatefulWidget {
  const _IncidentSnapshotPanel({
    required this.riskLevel,
    required this.statusPills,
    this.dispatchAdvice,
    this.voicePrompt,
    this.shouldSpeak = false,
    this.isVoiceSpeaking = false,
    this.onToggleVoicePrompt,
    this.reportCreated = false,
    this.onStatusUpdate,
  });

  final String riskLevel;
  final List<_IncidentStatusPill> statusPills;
  final String? dispatchAdvice;
  final String? voicePrompt;
  final bool shouldSpeak;
  final bool isVoiceSpeaking;
  final VoidCallback? onToggleVoicePrompt;
  final bool reportCreated;
  final ValueChanged<String>? onStatusUpdate;

  @override
  State<_IncidentSnapshotPanel> createState() => _IncidentSnapshotPanelState();
}

class _IncidentSnapshotPanelState extends State<_IncidentSnapshotPanel> {
  bool _expanded = true;

  String get _title {
    return switch (widget.riskLevel) {
      'High' => '優先處理中',
      'Medium' => '持續觀察中',
      _ => '事件摘要',
    };
  }

  Color get _accentColor {
    return switch (widget.riskLevel) {
      'High' => const Color(0xFF8F2E22),
      'Medium' => const Color(0xFFC95A4A),
      _ => EcareApp.muted,
    };
  }

  @override
  Widget build(BuildContext context) {
    final advice = widget.dispatchAdvice?.trim() ?? '';
    final prompt = widget.voicePrompt?.trim() ?? '';

    return AnimatedSize(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeInOut,
      alignment: Alignment.topCenter,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.92),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE5D3B5)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: () => setState(() => _expanded = !_expanded),
              child: Row(
                children: <Widget>[
                  Icon(Icons.checklist_rtl_rounded,
                      color: _accentColor, size: 18),
                  const SizedBox(width: 6),
                  Text(
                    _title,
                    style: const TextStyle(
                      color: EcareApp.text,
                      fontWeight: FontWeight.w800,
                      fontSize: 14,
                    ),
                  ),
                  const Spacer(),
                  if (widget.riskLevel == 'High' && _expanded)
                    const Icon(
                      Icons.priority_high_rounded,
                      color: Color(0xFF8F2E22),
                      size: 18,
                    ),
                  const SizedBox(width: 4),
                  Icon(
                    _expanded ? Icons.expand_less : Icons.expand_more,
                    color: _accentColor.withValues(alpha: 0.6),
                    size: 18,
                  ),
                ],
              ),
            ),
            if (_expanded) ...[
              const SizedBox(height: 9),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: widget.statusPills
                    .map((item) => _IncidentStatusChip(item: item))
                    .toList(),
              ),
              const SizedBox(height: 9),
              Container(
                width: double.infinity,
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                decoration: BoxDecoration(
                  color: const Color(0xFFEFF7F5),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: const Color(0xFFC8DDD7)),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Icon(Icons.terrain_outlined,
                        size: 14, color: Color(0xFF47665E)),
                    SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        '山區/偏鄉救援請優先補 GPS 或地標、同行人數、傷勢、手機電量與訊號。',
                        style: TextStyle(
                          color: Color(0xFF47665E),
                          fontSize: 12,
                          height: 1.45,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              if (advice.isNotEmpty) ...<Widget>[
                const SizedBox(height: 9),
                Container(
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                  decoration: BoxDecoration(
                    color: _accentColor.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: _accentColor.withValues(alpha: 0.25),
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Icon(
                        Icons.directions_run_rounded,
                        size: 14,
                        color: _accentColor,
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          advice,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: _accentColor,
                            fontSize: 12,
                            height: 1.45,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              if (prompt.isNotEmpty) ...<Widget>[
                const SizedBox(height: 9),
                Container(
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                  decoration: BoxDecoration(
                    color: widget.shouldSpeak
                        ? const Color(0xFFFFF0EA)
                        : const Color(0xFFFFF7EA),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: widget.shouldSpeak
                          ? EcareApp.primary.withValues(alpha: 0.35)
                          : const Color(0xFFEBDCC3),
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: <Widget>[
                      Icon(
                        widget.isVoiceSpeaking
                            ? Icons.graphic_eq_rounded
                            : widget.shouldSpeak
                                ? Icons.volume_up_rounded
                                : Icons.record_voice_over_outlined,
                        size: 15,
                        color: widget.shouldSpeak
                            ? EcareApp.primaryDark
                            : EcareApp.muted,
                      ),
                      const SizedBox(width: 7),
                      Expanded(
                        child: Text(
                          prompt,
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: widget.shouldSpeak
                                ? EcareApp.primaryDark
                                : EcareApp.text,
                            fontSize: 12,
                            height: 1.45,
                            fontWeight: widget.shouldSpeak
                                ? FontWeight.w800
                                : FontWeight.w600,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      SizedBox.square(
                        dimension: 34,
                        child: IconButton(
                          tooltip: widget.isVoiceSpeaking ? '停止播報' : '重播語音提示',
                          onPressed: widget.onToggleVoicePrompt,
                          padding: EdgeInsets.zero,
                          iconSize: 19,
                          style: IconButton.styleFrom(
                            backgroundColor:
                                Colors.white.withValues(alpha: 0.82),
                            foregroundColor: widget.shouldSpeak
                                ? EcareApp.primaryDark
                                : EcareApp.muted,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          icon: Icon(
                            widget.isVoiceSpeaking
                                ? Icons.stop_rounded
                                : Icons.play_arrow_rounded,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              if (widget.reportCreated &&
                  widget.onStatusUpdate != null) ...<Widget>[
                const SizedBox(height: 10),
                const Divider(height: 1, color: Color(0xFFEBDCC3)),
                const SizedBox(height: 10),
                Row(
                  children: <Widget>[
                    const Icon(Icons.assignment_turned_in_outlined,
                        size: 13, color: EcareApp.muted),
                    const SizedBox(width: 5),
                    const Text(
                      '通報已建立 · 更新狀態',
                      style: TextStyle(
                        color: EcareApp.muted,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 7),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: <Widget>[
                      _StatusUpdateChip(
                        icon: Icons.local_police_outlined,
                        label: '救援已抵達',
                        onTap: () => widget.onStatusUpdate!('救援已抵達'),
                      ),
                      const SizedBox(width: 7),
                      _StatusUpdateChip(
                        icon: Icons.sentiment_satisfied_outlined,
                        label: '情況緩和',
                        onTap: () => widget.onStatusUpdate!('情況緩和'),
                      ),
                      const SizedBox(width: 7),
                      _StatusUpdateChip(
                        icon: Icons.shield_outlined,
                        label: '我已安全',
                        onTap: () => widget.onStatusUpdate!('我已安全'),
                      ),
                      const SizedBox(width: 7),
                      _StatusUpdateChip(
                        icon: Icons.directions_run_outlined,
                        label: '撤離完成',
                        onTap: () => widget.onStatusUpdate!('撤離完成'),
                      ),
                    ],
                  ),
                ),
              ],
            ], // if (_expanded)
          ],
        ),
      ), // Container
    ); // AnimatedSize
  }
}

class _IncidentStatusChip extends StatelessWidget {
  const _IncidentStatusChip({required this.item});

  final _IncidentStatusPill item;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7EA),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFEBDCC3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(item.icon, size: 15, color: EcareApp.primary),
          const SizedBox(width: 5),
          Text(
            '${item.label}: ',
            style: const TextStyle(
              color: EcareApp.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 220),
            child: Text(
              item.value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: EcareApp.text,
                fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _QuickReplyBar extends StatelessWidget {
  const _QuickReplyBar({
    required this.actions,
    required this.enabled,
    required this.onSelected,
  });

  final List<_QuickReplyAction> actions;
  final bool enabled;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: actions
              .map(
                (action) => Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ActionChip(
                    avatar: Icon(action.icon, size: 16),
                    label: Text(action.text),
                    onPressed: enabled ? () => onSelected(action.text) : null,
                    visualDensity: VisualDensity.compact,
                    backgroundColor: const Color(0xFFFFF7EA),
                    disabledColor: const Color(0xFFF2E5D3),
                    side: const BorderSide(color: Color(0xFFE5D3B5)),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                    labelStyle: const TextStyle(
                      color: EcareApp.text,
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              )
              .toList(),
        ),
      ),
    );
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

class _StatusUpdateChip extends StatelessWidget {
  const _StatusUpdateChip({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
        decoration: BoxDecoration(
          color: const Color(0xFFF0FFF4),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFB7DFC4)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(icon, size: 13, color: const Color(0xFF2D7A47)),
            const SizedBox(width: 5),
            Text(
              label,
              style: const TextStyle(
                color: Color(0xFF2D7A47),
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DialogChip extends StatelessWidget {
  const _DialogChip({
    required this.label,
    required this.value,
    this.accent = false,
  });

  final String label;
  final String value;
  final bool accent;

  @override
  Widget build(BuildContext context) {
    const red = Color(0xFF8F2E22);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: accent ? const Color(0xFFFFEEEB) : const Color(0xFFFFF7EA),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: accent ? red.withValues(alpha: 0.35) : const Color(0xFFE5D3B5),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(
            '$label: ',
            style: TextStyle(
              color: accent ? red : EcareApp.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          Text(
            value,
            style: TextStyle(
              color: accent ? red : EcareApp.text,
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}
