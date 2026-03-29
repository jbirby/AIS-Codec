#!/usr/bin/env python3
"""
AIS Encoder — Convert vessel data to AIS audio WAV.

Produces a standards-compliant AIS GMSK transmission:
  1. Training sequence (24 alternating bits)
  2. Start flag (HDLC 0x7E)
  3. AIS message payload (bit-stuffed, NRZI-encoded)
  4. CRC-16-CCITT (computed on unstuffed data, inverted before transmission)
  5. End flag (HDLC 0x7E)
  6. Buffer tail (24 bits)

The resulting WAV can be decoded by any AIS decoder and sounds like a real
AIS signal on the VHF marine channels.

Usage:
    python3 ais_encode.py <output.wav> [options]

Options:
    --type N           Message type (1, 5, 18, 24; default 1)
    --mmsi NNNNNNNNN   9-digit MMSI (default 211234567)
    --lat DD.DDDDDD    Latitude in decimal degrees
    --lon DD.DDDDDD    Longitude in decimal degrees
    --sog N.N          Speed over ground in knots
    --cog N.N          Course over ground in degrees
    --heading N        True heading (0-359, 511 for N/A)
    --rot N            Rate of turn (degrees/minute, for Type 1)
    --nav-status N     Navigation status (0-15)
    --name TEXT        Vessel name (for Type 5/24)
    --callsign TEXT    Callsign (for Type 5)
    --destination TEXT Destination (for Type 5)
    --imo NNNNNNN      IMO number (for Type 5)
    --ship-type N      Ship type code (for Type 5)
"""

import sys
import wave
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ais_common import (
    SAMPLE_RATE, DATA_RATE, CENTER_FREQ, BT, HDLC_FLAG,
    pack_uint, bit_stuff, bit_unstuff, nrzi_encode, crc16_ccitt,
    gmsk_modulate,
    build_ais_type1, build_ais_type5, build_ais_type18, build_ais_type24,
)


def encode_ais_frame(payload_bits):
    """
    Encode an AIS message into a complete frame with HDLC framing and CRC.

    Process:
      1. Compute CRC-16 on payload bits
      2. Append inverted CRC
      3. Apply bit stuffing
      4. NRZI encode
      5. Prepend training sequence and start flag
      6. Append end flag and buffer

    Args:
        payload_bits: List of 0/1 integers (message payload)

    Returns:
        List of 0/1 integers (complete frame, NRZI-encoded)
    """
    # Compute CRC
    crc = crc16_ccitt(payload_bits)
    crc_inverted = crc ^ 0xFFFF

    # Append CRC bits (LSB first)
    payload_with_crc = payload_bits + [((crc_inverted >> i) & 1) for i in range(16)]

    # Bit stuffing
    stuffed = bit_stuff(payload_with_crc)

    # Frame building: [training] [start_flag] [stuffed_data] [end_flag] [buffer]
    frame = []

    # Training sequence: 24 alternating bits (0101...01)
    training = [0, 1] * 12
    frame.extend(training)

    # Start flag
    start_flag_bits = [(HDLC_FLAG >> i) & 1 for i in range(8)]
    frame.extend(start_flag_bits)

    # Bit-stuffed payload + CRC
    frame.extend(stuffed)

    # End flag
    end_flag_bits = [(HDLC_FLAG >> i) & 1 for i in range(8)]
    frame.extend(end_flag_bits)

    # Buffer: 24 trailing bits (mark tone = 1s)
    frame.extend([1] * 24)

    # NRZI encode
    frame_nrzi = nrzi_encode(frame)

    return frame_nrzi


def encode(msg_type, output_path, **kwargs):
    """Encode vessel data as an AIS WAV file."""

    print(f"\nAIS Encoder")
    print(f"===========")
    print(f"Message Type: {msg_type}")

    # Build payload based on message type
    if msg_type == 1:
        mmsi = kwargs.get('mmsi', 211234567)
        nav_status = kwargs.get('nav_status', 0)
        rot = kwargs.get('rot', 0)
        sog = kwargs.get('sog', 10.5)
        lat = kwargs.get('lat', 42.0)
        lon = kwargs.get('lon', -70.0)
        cog = kwargs.get('cog', 180.0)
        heading = kwargs.get('heading', 511)
        timestamp = kwargs.get('timestamp', 0)

        payload = build_ais_type1(mmsi, nav_status, rot, sog, lon, lat, cog, heading, timestamp)

        print(f"  MMSI: {mmsi}")
        print(f"  Position: {lat:.4f}°N, {lon:.4f}°E")
        print(f"  SOG: {sog} kts, COG: {cog}°, Heading: {heading}°")

    elif msg_type == 5:
        mmsi = kwargs.get('mmsi', 211234567)
        imo = kwargs.get('imo', 1234567)
        callsign = kwargs.get('callsign', 'W5ABC')
        vessel_name = kwargs.get('vessel_name', 'TEST VESSEL')
        ship_type = kwargs.get('ship_type', 30)
        destination = kwargs.get('destination', 'NEW YORK')

        payload = build_ais_type5(mmsi, imo, callsign, vessel_name, ship_type, destination=destination)

        print(f"  MMSI: {mmsi}")
        print(f"  Vessel: {vessel_name}")
        print(f"  Callsign: {callsign}")
        print(f"  Destination: {destination}")

    elif msg_type == 18:
        mmsi = kwargs.get('mmsi', 211234567)
        sog = kwargs.get('sog', 10.5)
        lat = kwargs.get('lat', 42.0)
        lon = kwargs.get('lon', -70.0)
        cog = kwargs.get('cog', 180.0)
        heading = kwargs.get('heading', 511)
        timestamp = kwargs.get('timestamp', 0)

        payload = build_ais_type18(mmsi, sog=sog, lon=lon, lat=lat, cog=cog, heading=heading, timestamp=timestamp)

        print(f"  MMSI: {mmsi}")
        print(f"  Position: {lat:.4f}°N, {lon:.4f}°E")
        print(f"  SOG: {sog} kts, COG: {cog}°")

    elif msg_type == 24:
        mmsi = kwargs.get('mmsi', 211234567)
        vessel_name = kwargs.get('vessel_name', 'TEST VESSEL')
        ship_type = kwargs.get('ship_type', 30)

        payload = build_ais_type24(mmsi, vessel_name=vessel_name, ship_type=ship_type)

        print(f"  MMSI: {mmsi}")
        print(f"  Vessel: {vessel_name}")

    else:
        print(f"Error: Unsupported message type {msg_type}")
        sys.exit(1)

    print(f"  Payload bits: {len(payload)}")

    # Encode frame
    print(f"  Encoding frame...")
    frame_bits = encode_ais_frame(payload)

    print(f"  Frame bits (NRZI): {len(frame_bits)}")

    # GMSK modulate
    print(f"  GMSK modulating at {DATA_RATE} bps...")
    print(f"    Center frequency: {CENTER_FREQ} Hz")
    print(f"    Sample rate: {SAMPLE_RATE} Hz")
    print(f"    BT product: {BT}")

    audio = gmsk_modulate(frame_bits, SAMPLE_RATE, DATA_RATE, BT, CENTER_FREQ)

    # Normalize
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.90

    # Convert to 16-bit PCM
    pcm = (audio * 32767).astype(np.int16)

    # Write WAV
    with wave.open(output_path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())

    duration = len(pcm) / SAMPLE_RATE
    file_size = os.path.getsize(output_path)

    print(f"\nOutput: {output_path}")
    print(f"  Duration: {duration:.2f}s")
    print(f"  WAV size: {file_size // 1024} KB")
    print(f"  Sample rate: {SAMPLE_RATE} Hz, 16-bit mono")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ais_encode.py <output.wav> [options]")
        print()
        print("Options:")
        print("  --type N           Message type (1, 5, 18, 24; default 1)")
        print("  --mmsi NNNNNNNNN   9-digit MMSI")
        print("  --lat DD.DDDDDD    Latitude")
        print("  --lon DD.DDDDDD    Longitude")
        print("  --sog N.N          Speed over ground (knots)")
        print("  --cog N.N          Course over ground (degrees)")
        print("  --heading N        Heading (0-359, 511 for N/A)")
        print("  --name TEXT        Vessel name (Type 5/24)")
        print("  --callsign TEXT    Callsign (Type 5)")
        print("  --destination TEXT Destination (Type 5)")
        print("  --imo NNNNNNN      IMO number (Type 5)")
        print("  --ship-type N      Ship type code")
        sys.exit(1)

    output_path = sys.argv[1]
    msg_type = 1
    kwargs = {}

    # Parse arguments
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == '--type' and i + 1 < len(args):
            msg_type = int(args[i + 1])
            i += 2
        elif args[i] == '--mmsi' and i + 1 < len(args):
            kwargs['mmsi'] = int(args[i + 1])
            i += 2
        elif args[i] == '--lat' and i + 1 < len(args):
            kwargs['lat'] = float(args[i + 1])
            i += 2
        elif args[i] == '--lon' and i + 1 < len(args):
            kwargs['lon'] = float(args[i + 1])
            i += 2
        elif args[i] == '--sog' and i + 1 < len(args):
            kwargs['sog'] = float(args[i + 1])
            i += 2
        elif args[i] == '--cog' and i + 1 < len(args):
            kwargs['cog'] = float(args[i + 1])
            i += 2
        elif args[i] == '--heading' and i + 1 < len(args):
            kwargs['heading'] = int(args[i + 1])
            i += 2
        elif args[i] == '--rot' and i + 1 < len(args):
            kwargs['rot'] = int(args[i + 1])
            i += 2
        elif args[i] == '--nav-status' and i + 1 < len(args):
            kwargs['nav_status'] = int(args[i + 1])
            i += 2
        elif args[i] == '--name' and i + 1 < len(args):
            kwargs['vessel_name'] = args[i + 1]
            i += 2
        elif args[i] == '--callsign' and i + 1 < len(args):
            kwargs['callsign'] = args[i + 1]
            i += 2
        elif args[i] == '--destination' and i + 1 < len(args):
            kwargs['destination'] = args[i + 1]
            i += 2
        elif args[i] == '--imo' and i + 1 < len(args):
            kwargs['imo'] = int(args[i + 1])
            i += 2
        elif args[i] == '--ship-type' and i + 1 < len(args):
            kwargs['ship_type'] = int(args[i + 1])
            i += 2
        else:
            print(f"Unknown option: {args[i]}")
            sys.exit(1)

    encode(msg_type, output_path, **kwargs)
