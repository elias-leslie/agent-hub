/**
 * Framework-agnostic transcription manager.
 *
 * Provides the same dual-engine (Web Speech + Whisper) transcription
 * as useTranscription hook, but as a vanilla TypeScript class for
 * non-React consumers (e.g., Phaser.js, vanilla DOM).
 */

/// <reference path="../types/web-speech.d.ts" />

import type { TranscriptionEngine, TranscriptionStatus, TranscriptionError } from '../hooks/transcription/types';
import { getSpeechRecognitionCtor, resolveEngine, mapSpeechError } from '../hooks/transcription/utils';

export type { TranscriptionEngine, TranscriptionStatus, TranscriptionError };

export interface TranscriptionManagerOptions {
  /** Agent Hub voice WebSocket URL for whisper fallback */
  whisperWsUrl?: string;
  /** Force a specific engine */
  preferredEngine?: 'web-speech' | 'whisper';
  /** Language for Web Speech API (default: navigator.language || 'en-US') */
  lang?: string;
}

export interface TranscriptionCallbacks {
  onFinalTranscript: (text: string) => void;
  onInterimTranscript?: (text: string) => void;
  onStatusChange?: (status: TranscriptionStatus) => void;
  onError?: (error: TranscriptionError) => void;
}

export class TranscriptionManager {
  readonly engine: TranscriptionEngine;
  readonly isSupported: boolean;

  private _status: TranscriptionStatus = 'idle';
  private _callbacks: TranscriptionCallbacks;
  private _options: TranscriptionManagerOptions;

  // Web Speech state
  private _recognition: SpeechRecognition | null = null;
  private _isListening = false;
  private _accumulatedText = '';

  // Whisper state
  private _ws: WebSocket | null = null;
  private _audioContext: AudioContext | null = null;
  private _stream: MediaStream | null = null;
  private _processor: ScriptProcessorNode | null = null;

  constructor(callbacks: TranscriptionCallbacks, options: TranscriptionManagerOptions = {}) {
    this._callbacks = callbacks;
    this._options = options;

    const SpeechRecognition = getSpeechRecognitionCtor();
    this.engine = resolveEngine(
      options.preferredEngine,
      SpeechRecognition !== null,
      Boolean(options.whisperWsUrl),
    );
    this.isSupported = this.engine !== 'none';
  }

  get status(): TranscriptionStatus {
    return this._status;
  }

  get isRecording(): boolean {
    return this._isListening;
  }

  async startRecording(): Promise<void> {
    if (this.engine === 'web-speech') {
      this._startWebSpeech();
    } else if (this.engine === 'whisper') {
      await this._startWhisper();
    }
  }

  stopRecording(): void {
    if (this.engine === 'web-speech') {
      this._stopWebSpeech();
    } else if (this.engine === 'whisper') {
      this._stopWhisper();
    }
  }

  destroy(): void {
    this._isListening = false;
    // Web Speech cleanup
    if (this._recognition) {
      this._recognition.onresult = null;
      this._recognition.onerror = null;
      this._recognition.onend = null;
      this._recognition.abort();
      this._recognition = null;
    }
    // Whisper cleanup
    this._stream?.getTracks().forEach(t => t.stop());
    this._processor?.disconnect();
    this._ws?.close();
    this._audioContext?.close();
    this._stream = null;
    this._processor = null;
    this._ws = null;
    this._audioContext = null;
  }

  // ── Web Speech Engine ────────────────────────────

  private _startWebSpeech(): void {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;

    // Clean up previous instance
    if (this._recognition) {
      this._recognition.onresult = null;
      this._recognition.onerror = null;
      this._recognition.onend = null;
      this._recognition.abort();
      this._recognition = null;
    }

    const recognition = new Ctor();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = this._options.lang ?? navigator?.language ?? 'en-US';

    let finalProcessed = false;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const result = event.results[0];
      if (!result) return;

      if (result.isFinal && !finalProcessed) {
        finalProcessed = true;
        const text = result[0].transcript.trim();
        if (text) {
          this._accumulatedText = this._accumulatedText
            ? `${this._accumulatedText} ${text}`
            : text;
        }
        this._callbacks.onFinalTranscript(this._accumulatedText);
        this._callbacks.onInterimTranscript?.('');
      } else if (!result.isFinal) {
        this._callbacks.onInterimTranscript?.(result[0].transcript);
      }
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === 'no-speech' && this._isListening) return;
      const err = mapSpeechError(event.error);
      this._setStatus('error');
      this._callbacks.onError?.(err);
    };

    recognition.onend = () => {
      if (this._isListening) {
        try {
          this._startWebSpeech();
        } catch {
          this._setStatus('idle');
          this._recognition = null;
          this._isListening = false;
        }
      } else {
        this._setStatus('idle');
        this._recognition = null;
      }
    };

    this._recognition = recognition;
    this._isListening = true;
    this._setStatus('listening');
    this._callbacks.onError?.(null);
    recognition.start();
  }

  private _stopWebSpeech(): void {
    this._isListening = false;
    this._recognition?.stop();
  }

  // ── Whisper Engine ───────────────────────────────

  private async _startWhisper(): Promise<void> {
    const wsUrl = this._options.whisperWsUrl;
    if (!wsUrl) {
      this._callbacks.onError?.('whisper-unavailable');
      this._setStatus('error');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this._stream = stream;

      const separator = wsUrl.includes('?') ? '&' : '?';
      const fullUrl = `${wsUrl}${separator}mode=transcribe`;
      const ws = new WebSocket(fullUrl);
      this._ws = ws;

      ws.onopen = () => {
        const ctx = new AudioContext({ sampleRate: 16000 });
        this._audioContext = ctx;

        const source = ctx.createMediaStreamSource(stream);
        const processor = ctx.createScriptProcessor(4096, 1, 1);

        processor.onaudioprocess = (e) => {
          if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
          const inputData = e.inputBuffer.getChannelData(0);
          const int16Array = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            const s = Math.max(-1, Math.min(1, inputData[i]));
            int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          const blob = new Blob([int16Array.buffer], { type: 'application/octet-stream' });
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64 = (reader.result as string).split(',')[1];
            this._ws?.send(JSON.stringify({ type: 'audio', data: base64 }));
          };
          reader.readAsDataURL(blob);
        };

        source.connect(processor);
        processor.connect(ctx.destination);
        this._processor = processor;

        ws.send(JSON.stringify({ type: 'control', action: 'start' }));
        this._setStatus('listening');
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'transcript') {
          this._accumulatedText = this._accumulatedText
            ? `${this._accumulatedText} ${msg.data}`
            : msg.data;
          this._callbacks.onFinalTranscript(this._accumulatedText);
          this._setStatus('idle');
        }
      };

      ws.onerror = () => {
        this._callbacks.onError?.('whisper-unavailable');
        this._setStatus('error');
      };

      ws.onclose = () => {
        if (this._status !== 'error') this._setStatus('idle');
      };

      this._isListening = true;
      this._callbacks.onError?.(null);
      this._setStatus('listening');
    } catch (e) {
      if (e instanceof DOMException && e.name === 'NotAllowedError') {
        this._callbacks.onError?.('not-allowed');
      } else {
        this._callbacks.onError?.('network');
      }
      this._setStatus('error');
    }
  }

  private _stopWhisper(): void {
    this._isListening = false;
    this._stream?.getTracks().forEach(t => t.stop());
    this._stream = null;
    this._processor?.disconnect();
    this._processor = null;

    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({ type: 'control', action: 'stop' }));
      this._setStatus('processing');
    }

    this._audioContext?.close();
    this._audioContext = null;
  }

  // ── Helpers ──────────────────────────────────────

  private _setStatus(status: TranscriptionStatus): void {
    this._status = status;
    this._callbacks.onStatusChange?.(status);
  }
}
