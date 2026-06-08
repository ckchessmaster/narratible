# Echo-Scribe

Echo-Scribe is an end-to-end PDF-to-Ebook/Audiobook creation tool. It parses a PDF, cleans up the text (handling footnotes, margins, and parsing artifacts), organizes the text into chapters with an interactive editor, generates natural-sounding audiobook files (MP3) using local/cloud TTS engines, compiles the book into EPUB, and can optionally upload the results to Audiobookshelf.

## Architecture

The project consists of two main components:
- **Backend**: A Python FastAPI server that handles file processing, text extraction, LLM cleanup, TTS synthesis, and EPUB generation.
- **Frontend**: A React + Vite web application that provides a wizard-driven user interface for uploading, editing, and exporting projects.

## Setup Instructions

*(Detailed setup instructions will be populated as we build out the modules)*
