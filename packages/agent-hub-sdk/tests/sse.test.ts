// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { SseParser } from '../src';

describe('SseParser', () => {
    it('returns the data of each completed event', () => {
        const parser = new SseParser();
        expect(parser.push('data: {"a":1}\n\ndata: {"a":2}\n\n')).toEqual(['{"a":1}', '{"a":2}']);
    });

    it('waits for the rest of an event split anywhere', () => {
        const parser = new SseParser();
        expect(parser.push('da')).toEqual([]);
        expect(parser.push('ta: {"a"')).toEqual([]);
        expect(parser.push(':1}\n')).toEqual([]);
        expect(parser.push('\ndata: x')).toEqual(['{"a":1}']);
        expect(parser.push('\n\n')).toEqual(['x']);
    });

    it('reads CRLF and CR line ends, also when "\\r" and "\\n" arrive in different chunks', () => {
        const parser = new SseParser();
        expect(parser.push('data: a\r\n\r\ndata: b\r')).toEqual(['a']);
        expect(parser.push('\n\r')).toEqual(['b']);
        expect(parser.push('\ndata: c\r\r')).toEqual(['c']);
        expect(parser.flush()).toEqual([]);
    });

    it('skips comments and fields other than data, and joins multi-line data', () => {
        const parser = new SseParser();
        const out = parser.push(': keepalive\nevent: ping\nid: 7\ndata: one\ndata: two\n\n');
        expect(out).toEqual(['one\ntwo']);
    });

    it('flush delivers an event the stream cut off before its blank line', () => {
        const parser = new SseParser();
        expect(parser.push('data: {"type":"done"}')).toEqual([]);
        expect(parser.flush()).toEqual(['{"type":"done"}']);
        expect(parser.flush()).toEqual([]);
    });
});
