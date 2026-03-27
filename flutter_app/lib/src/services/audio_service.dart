import 'dart:io';

import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';

class AudioService {
  AudioService({AudioRecorder? recorder}) : _recorder = recorder ?? AudioRecorder();

  final AudioRecorder _recorder;

  Future<bool> ensurePermission() async {
    final status = await Permission.microphone.request();
    return status.isGranted;
  }

  Future<void> startRecording({required String path}) async {
    final hasPermission = await ensurePermission();
    if (!hasPermission) {
      throw Exception('Microphone permission denied.');
    }

    await _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
      ),
      path: path,
    );
  }

  Future<String?> stopRecording() async {
    return _recorder.stop();
  }

  Future<void> dispose() async {
    await _recorder.dispose();
  }

  Future<bool> hasActiveRecording() {
    return _recorder.isRecording();
  }

  Future<File?> stopToFile() async {
    final path = await stopRecording();
    if (path == null) {
      return null;
    }
    return File(path);
  }
}
