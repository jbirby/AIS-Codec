#!/usr/bin/env python3
"""
AIS Decoder — Convert AIS audio WAV back to vessel data.

Decodes an AIS GMSK transmission:
  1. Reads and resamples the WAV to 48000 Hz if needed
  2. GMSK-demodulates by estimating instantaneous frequency
  3. NRZI decodes the bitstream
  4. Scans for HDLC start flag (0x7E)
  5. Removes bit-stuffed zeros (after five consecutive 1s)
  6. Verifies CRC-16 (inverted)
  7. Parses the AIS message type and fields
  8. Outputs decoded vessel information

Usage:
    python3 ais_decode.py <input.wav> [output.txt]

If output is omitted, decoded data is printed to stdout.
"""

import sys
import wave
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ais_common import (
    SAMPLE_RATE, DATA_RATE, CENTER_FREQ, BT, HDLC_FLAG,
    gmsk_demodulate, nrzi_decode, bit_unstuff, crc16_ccitt,
    parse_ais_payload,
)


def read_wav(wav_path):
    """Read a WAV file and return audio samples as float64 array."""
    with wave.open(wav_path, 'r') as w:
        sr = w.getframerate()
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)

    if sampwidth == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32767.0
    elif sampwidth == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128.0
    elif sampwidth == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483647.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth}")

    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    print(f"Input: {wav_path}")
    print(f"  Samples: {len(audio):,}, Rate: {sr} Hz, Duration: {len(audio)/sr:.2f}s")

    # Resample if needed
    if sr != SAMPLE_RATE:
        ratio = SAMPLE_RATE / sr
        new_len = int(len(audio) * ratio)
        x_old = np.linspace(0, 1, len(audio))
        x_new = np.linspace(0, 1, new_len)
        audio = np.interp(x_new, x_old, audio)
        print(f"  Resampled {sr} -> {SAMPLE_RATE} Hz")

    return audio


def find_ais_frames(bits):
    """
    Scan a demodulated bitstream for HDLC frames.

    Looks for start flag (0x7E = 01111110), extracts payload until end flag.

    Args:
        bits: List of 0/1 integers

    Returns:
        List of (payload_bits, crc_bits) tuples found
    """
    frames = []
    i = 0
    flag_bits = [0, 1, 1, 1, 1, 1, 1, 0]

    while i <= len(bits) - 8:
        # Check for start flag at current position
        if bits[i:i+8] == flag_bits:
            # Found start flag, scan for end flag
            payload = []
            j = i + 8

            while j <= len(bits) - 8:
                if bits[j:j+8] == flag_bits:
                    # Found end flag
                    frames.append(payload)
                    i = j + 8
                    break
                else:
                    payload.append(bits[j])
                    j += 1
            else:
                # No end flag found, skip and continue
                i += 1
        else:
            i += 1

    return frames


def extract_crc_payload(frame_bits):
    """
    Extract payload and CRC from a bit-stuffed frame.

    Process:
      1. Remove bit stuffing (0 after five 1s)
      2. Separate payload and CRC (last 16 bits)

    Args:
        frame_bits: Bit-stuffed bits between start and end flags

    Returns:
        (payload_bits, crc_bits, crc_ok) tuple
    """
    # Remove bit stuffing
    unstuffed = bit_unstuff(frame_bits)

    if len(unstuffed) < 16:
        return None, None, False

    # Last 16 bits are CRC
    payload = unstuffed[:-16]
    crc_bits = unstuffed[-16:]

    # Verify CRC
    crc_computed = crc16_ccitt(payload)
    crc_computed_inverted = crc_computed ^ 0xFFFF

    # Convert CRC bits to integer (LSB first)
    crc_received = 0
    for i in range(16):
        crc_received |= (crc_bits[i] & 1) << i

    crc_ok = (crc_received == crc_computed_inverted)

    return payload, crc_bits, crc_ok


def decode(wav_path, output_path=None):
    """Decode an AIS WAV file back to vessel data."""

    # Step 1: Read WAV
    audio = read_wav(wav_path)

    # Step 2: GMSK demodulate
    print(f"\nDecoding AIS at {DATA_RATE} bps...")
    print(f"  GMSK demodulating...")
    bits_demod = gmsk_demodulate(audio, SAMPLE_RATE, DATA_RATE, BT, CENTER_FREQ)
    print(f"  Demodulated: {len(bits_demod)} bits")

    # Step 3: NRZI decode
    print(f"  NRZI decoding...")
    bits_nrzi = nrzi_decode(bits_demod)
    print(f"  After NRZI: {len(bits_nrzi)} bits")

    # Step 4: Find HDLC frames
    print(f"  Scanning for HDLC frames...")
    frames = find_ais_frames(bits_nrzi)
    print(f"  Found {len(frames)} frame(s)")

    if not frames:
        print("\nWARNING: No AIS frames found in the signal.")
        print("  The WAV may not contain AIS data, or the modulation parameters")
        print("  may not match the recording.")
        return False

    # Step 5: Process frames
    output_lines = []
    output_lines.append(f"AIS Decode Results\n{'='*40}")

    for frame_idx, frame_bits in enumerate(frames):
        print(f"\n  Frame {frame_idx + 1}: {len(frame_bits)} bits (with stuffing)")

        payload, crc_bits, crc_ok = extract_crc_payload(frame_bits)

        if payload is None:
            output_lines.append(f"\nFrame {frame_idx + 1}: ERROR - Frame too short")
            continue

        print(f"    Payload: {len(payload)} bits, CRC: {'OK' if crc_ok else 'FAIL'}")

        if not crc_ok:
            output_lines.append(f"\nFrame {frame_idx + 1}: CRC check FAILED")

        # Parse payload
        msg_info = parse_ais_payload(payload)

        output_lines.append(f"\nFrame {frame_idx + 1}:")
        output_lines.append(f"  Message Type: {msg_info.get('type', 'Unknown')}")

        if 'error' in msg_info:
            output_lines.append(f"  Error: {msg_info['error']}")
        else:
            for key, value in sorted(msg_info.items()):
                if key != 'type':
                    output_lines.append(f"  {key}: {value}")

    # Output
    output_text = '\n'.join(output_lines)

    if output_path:
        with open(output_path, 'w') as f:
            f.write(output_text)
        print(f"\nOutput: {output_path}")
    else:
        print(f"\n{output_text}")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ais_decode.py <input.wav> [output.txt]")
        sys.exit(1)

    wav_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.isfile(wav_path):
        print(f"Error: Input file not found: {wav_path}")
        sys.exit(1)

    decode(wav_path, output_path)
