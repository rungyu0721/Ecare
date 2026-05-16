import 'dart:async';
import 'dart:io';

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

    if (!Platform.isWindows) {
      throw UnsupportedError('目前 demo 版語音播報先支援 Windows。');
    }

    _emit(VoicePromptSnapshot(currentText: prompt, isSpeaking: true));

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

    unawaited(
      process.stderr.drain<void>().catchError((_) {}),
    );
    unawaited(
      process.stdout.drain<void>().catchError((_) {}),
    );

    try {
      await process.exitCode;
    } finally {
      if (identical(_process, process)) {
        _process = null;
        _emit(
          _snapshot.copyWith(
            isSpeaking: false,
            clearCurrentText: true,
          ),
        );
      }
    }
  }

  Future<void> stop() async {
    final process = _process;
    if (process != null) {
      process.kill();
      _process = null;
    }
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
    await _controller.close();
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
