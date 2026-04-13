import 'dart:async';

import 'package:audioplayers/audioplayers.dart';

class AudioPlaybackSnapshot {
  const AudioPlaybackSnapshot({
    this.currentFilePath,
    this.isPlaying = false,
    this.position = Duration.zero,
    this.duration = Duration.zero,
  });

  final String? currentFilePath;
  final bool isPlaying;
  final Duration position;
  final Duration duration;

  AudioPlaybackSnapshot copyWith({
    String? currentFilePath,
    bool? isPlaying,
    Duration? position,
    Duration? duration,
    bool clearCurrentFilePath = false,
  }) {
    return AudioPlaybackSnapshot(
      currentFilePath: clearCurrentFilePath
          ? null
          : (currentFilePath ?? this.currentFilePath),
      isPlaying: isPlaying ?? this.isPlaying,
      position: position ?? this.position,
      duration: duration ?? this.duration,
    );
  }
}

class AudioPlaybackService {
  AudioPlaybackService({AudioPlayer? player})
      : _player = player ?? AudioPlayer() {
    _player.setReleaseMode(ReleaseMode.stop);
    _subscriptions = <StreamSubscription<dynamic>>[
      _player.onPlayerStateChanged.listen((PlayerState state) {
        _emit(_snapshot.copyWith(isPlaying: state == PlayerState.playing));
      }),
      _player.onPositionChanged.listen((Duration position) {
        _emit(_snapshot.copyWith(position: position));
      }),
      _player.onDurationChanged.listen((Duration duration) {
        _emit(_snapshot.copyWith(duration: duration));
      }),
      _player.onPlayerComplete.listen((_) {
        _emit(
          _snapshot.copyWith(
            isPlaying: false,
            position: Duration.zero,
          ),
        );
      }),
    ];
  }

  final AudioPlayer _player;
  final StreamController<AudioPlaybackSnapshot> _controller =
      StreamController<AudioPlaybackSnapshot>.broadcast();
  late final List<StreamSubscription<dynamic>> _subscriptions;

  AudioPlaybackSnapshot _snapshot = const AudioPlaybackSnapshot();

  Stream<AudioPlaybackSnapshot> get snapshots => _controller.stream;

  AudioPlaybackSnapshot get snapshot => _snapshot;

  Future<void> toggle(String filePath) async {
    final isSameFile = _snapshot.currentFilePath == filePath;

    if (isSameFile && _snapshot.isPlaying) {
      await _player.pause();
      return;
    }

    if (isSameFile &&
        _snapshot.duration > Duration.zero &&
        _snapshot.position >= _snapshot.duration) {
      await _player.seek(Duration.zero);
    }

    if (isSameFile &&
        !_snapshot.isPlaying &&
        _snapshot.position > Duration.zero) {
      await _player.resume();
      return;
    }

    _emit(
      AudioPlaybackSnapshot(
        currentFilePath: filePath,
        isPlaying: false,
        position: Duration.zero,
        duration: Duration.zero,
      ),
    );
    await _player.play(DeviceFileSource(filePath));
  }

  Future<void> stop() async {
    await _player.stop();
    _emit(
      _snapshot.copyWith(
        isPlaying: false,
        position: Duration.zero,
      ),
    );
  }

  Future<void> dispose() async {
    for (final subscription in _subscriptions) {
      await subscription.cancel();
    }
    await _player.dispose();
    await _controller.close();
  }

  void _emit(AudioPlaybackSnapshot snapshot) {
    _snapshot = snapshot;
    if (!_controller.isClosed) {
      _controller.add(snapshot);
    }
  }
}
