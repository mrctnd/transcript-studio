# Transcript Studio project plan

The app turns public media links and uploaded files into timestamped transcripts. A local worker downloads or decodes the media, runs faster-whisper, and stores the result in SQLite. The browser provides source settings, job status and cancellation, an editable transcript, and five export formats.

The English redesign uses the existing React and FastAPI architecture. Turkish and the other supported spoken languages remain available independently of the interface language.

Before publishing, check the production build, backend tests, desktop and mobile layouts, and the transcript editing and export flow. Publish source and setup instructions. Keep runtime data, model weights, local transcripts, and test artifacts outside the repository.
