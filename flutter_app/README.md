# E-CARE Flutter App

This directory contains the Flutter client that will replace the old
Capacitor/Web frontend.

## Current scope

- Chat UI scaffold
- FastAPI `/chat` integration
- Risk banner and high-risk dialog
- Reports list scaffold via `/reports`
- Audio recording scaffold and `/audio` upload flow
- Location service scaffold for dispatch context

## Suggested next steps

1. Install Flutter SDK and run `flutter create .` inside this directory.
2. Merge the generated platform folders with this `lib/` structure.
3. Run `flutter pub get`.
4. Replace the English placeholder copy with your final Traditional Chinese UI text.
5. Add persistent state management if you want multi-page session memory.
