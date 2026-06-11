import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:dio/dio.dart';

import '../config/api_config.dart';

class VoicePromptSnapshot {
  const VoicePromptSnapshot({
    this.currentText,
    this.isSpeaking = false,
  });

  final String? currentText;
  final bool isSpeaking;

  VoicePromptSnapshot copyWith({
    String? currentText,
    bool? isSpeaking,
    bool clearCurrentText = false,
  }) {
    return VoicePromptSnapshot(
      currentText: clearCurrentText ? null : (currentText ?? this.currentText),
      isSpeaking: isSpeaking ?? this.isSpeaking,
    );
  }
}

class VoicePromptService {
  VoicePromptService({Dio? dio, AudioPlayer? player})
      : _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: ApiConfig.defaultBaseUrl,
                connectTimeout: const Duration(seconds: 10),
                receiveTimeout: const Duration(seconds: 90),
                headers: <String, String>{
                  'Content-Type': 'application/json',
                },
              ),
            ),
        _player = player ?? AudioPlayer() {
    _player.setReleaseMode(ReleaseMode.stop);
  }

  final Dio _dio;
  final AudioPlayer _player;
  final StreamController<VoicePromptSnapshot> _controller =
      StreamController<VoicePromptSnapshot>.broadcast();

  VoicePromptSnapshot _snapshot = const VoicePromptSnapshot();
  Process? _process;
  bool _disposed = false;

  Stream<VoicePromptSnapshot> get snapshots => _controller.stream;

  VoicePromptSnapshot get snapshot => _snapshot;

  Future<void> speak(String text) async {
    final prompt = text.trim();
    if (prompt.isEmpty) {
      return;
    }

    await stop();
    _emit(VoicePromptSnapshot(currentText: prompt, isSpeaking: true));

    try {
      await _speakWithBackendTts(prompt);
    } catch (_) {
      await _speakWithWindowsVoice(prompt);
    } finally {
      if (!_disposed) {
        _emit(
          _snapshot.copyWith(
            isSpeaking: false,
            clearCurrentText: true,
          ),
        );
      }
    }
  }

  /// Play pre-synthesized audio identified by [cacheKey] (from chat response
  /// field `tts_key`).  Falls back to on-demand synthesis if the key is
  /// missing or the backend returns an error.
  Future<void> speakFromKey(String cacheKey, {String? fallbackText}) async {
    await stop();
    final label = fallbackText?.trim() ?? cacheKey;
    _emit(VoicePromptSnapshot(currentText: label, isSpeaking: true));

    try {
      await _speakWithCacheKey(cacheKey);
    } catch (_) {
      // Fall back to on-demand TTS or Windows voice.
      final text = fallbackText?.trim() ?? '';
      if (text.isNotEmpty) {
        try {
          await _speakWithBackendTts(text);
        } catch (_) {
          await _speakWithWindowsVoice(text);
        }
      }
    } finally {
      if (!_disposed) {
        _emit(_snapshot.copyWith(isSpeaking: false, clearCurrentText: true));
      }
    }
  }

  Future<void> _speakWithCacheKey(String cacheKey) async {
    final response = await _dio.get<List<int>>(
      '/tts/ready/$cacheKey',
      options: Options(responseType: ResponseType.bytes),
    );
    final audioBytes = response.data;
    if (audioBytes == null || audioBytes.isEmpty) {
      throw StateError('Pre-cached TTS returned empty audio.');
    }

    final file = File(
      '${Directory.systemTemp.path}${Platform.pathSeparator}'
      'ecare_voice_${DateTime.now().microsecondsSinceEpoch}.wav',
    );
    await file.writeAsBytes(audioBytes, flush: true);
    await _playGeneratedWav(file.path);
  }

  Future<void> stop() async {
    final process = _process;
    if (process != null) {
      process.kill();
      _process = null;
    }
    await _player.stop();
    if (_snapshot.isSpeaking || _snapshot.currentText != null) {
      _emit(
        _snapshot.copyWith(
          isSpeaking: false,
          clearCurrentText: true,
        ),
      );
    }
  }

  Future<void> dispose() async {
    _disposed = true;
    await stop();
    await _player.dispose();
    await _controller.close();
  }

  Future<void> _speakWithBackendTts(String prompt) async {
    final response = await _dio.post<List<int>>(
      '/tts',
      data: <String, dynamic>{
        'text': prompt,
        'speed': 0.9,
      },
      options: Options(responseType: ResponseType.bytes),
    );
    final audioBytes = response.data;
    if (audioBytes == null || audioBytes.isEmpty) {
      throw StateError('Backend TTS returned empty audio.');
    }

    final file = File(
      '${Directory.systemTemp.path}${Platform.pathSeparator}'
      'ecare_voice_${DateTime.now().microsecondsSinceEpoch}.wav',
    );
    await file.writeAsBytes(audioBytes, flush: true);
    await _playGeneratedWav(file.path);
  }

  Future<void> _playGeneratedWav(String filePath) async {
    final completer = Completer<void>();
    StreamSubscription<void>? completedSub;
    StreamSubscription<PlayerState>? stateSub;

    completedSub = _player.onPlayerComplete.listen((_) {
      if (!completer.isCompleted) {
        completer.complete();
      }
    });
    stateSub = _player.onPlayerStateChanged.listen((PlayerState state) {
      if (state == PlayerState.stopped && !completer.isCompleted) {
        completer.complete();
      }
    });

    try {
      await _player.play(DeviceFileSource(filePath));
      await completer.future.timeout(const Duration(seconds: 90));
    } finally {
      await completedSub.cancel();
      await stateSub.cancel();
    }
  }

  Future<void> _speakWithWindowsVoice(String prompt) async {
    if (!Platform.isWindows) {
      throw UnsupportedError(
        'Voice prompt playback is only implemented for Windows.',
      );
    }

    final process = await Process.start(
      'powershell',
      <String>[
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        r'''
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Rate = -1
$speaker.Volume = 100
$text = [Console]::In.ReadToEnd()
$speaker.Speak($text)
$speaker.Dispose()
''',
      ],
      runInShell: false,
    );
    _process = process;
    process.stdin.write(prompt);
    await process.stdin.close();

    unawaited(process.stderr.drain<void>().catchError((_) {}));
    unawaited(process.stdout.drain<void>().catchError((_) {}));

    try {
      await process.exitCode;
    } finally {
      if (identical(_process, process)) {
        _process = null;
      }
    }
  }

  void _emit(VoicePromptSnapshot snapshot) {
    if (_disposed) {
      return;
    }
    _snapshot = snapshot;
    if (!_controller.isClosed) {
      _controller.add(snapshot);
    }
  }
}
