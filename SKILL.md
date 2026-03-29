---
name: ais-codec
description: >
  Encode vessel position and voyage data into AIS (Automatic Identification
  System) audio WAV files and decode AIS WAV recordings back into vessel
  information. AIS is the IMO-mandated maritime vessel tracking system used on
  all ships over 300 gross tons on international voyages, broadcasting vessel
  identity, position, course, speed, and voyage data on VHF marine channels.
  Use this skill whenever the user mentions AIS, Automatic Identification
  System, vessel tracking, MMSI, ship tracking, marine VHF data, Class A or B
  transponder, ship position reports, AIS decoder, maritime transponder,
  vessel data broadcast, or wants to create or analyze AIS transmissions.
  Also trigger when the user has a WAV file recorded from an AIS broadcast and
  wants to extract vessel information, or wants to create a WAV that sounds
  like a real AIS signal. Covers encoding (vessel data to WAV) and decoding
  (WAV to vessel information).
---

# AIS Codec

This skill converts between vessel data and AIS (Automatic Identification System)
audio files. AIS is a maritime vessel identification and location reporting system
mandated by the International Maritime Organization (IMO) for all ships over 300
gross tons on international voyages. Each AIS transmission broadcasts the vessel's
MMSI (Maritime Mobile Service Identity), position, course, speed, and voyage-related
data on VHF marine channels using GMSK modulation at 9600 bps.

The generated WAV files are protocol-correct AIS transmissions. They use GMSK
(Gaussian Minimum Shift Keying) modulation with NRZI encoding, bit stuffing,
and CRC-16 frame check sequences — the same standards used by real AIS transponders
and receivers.

## Quick reference: the AIS signal

An AIS transmission consists of:

1. **Training sequence** — 24 bits of alternating 0/1 to establish bit synchronization.

2. **Start flag (HDLC)** — 0x7E (01111110), marking the frame boundary.

3. **Data payload** — NRZI-encoded, bit-stuffed:
   - AIS uses NRZI encoding: a 0 bit causes a frequency transition, a 1 bit does not.
   - Bit stuffing: after five consecutive 1-bits in the data, a 0 bit is inserted
     (and must be removed during decoding).
   - Data is packed into variable-length messages (Type 1, 5, 18, 24, etc.).

4. **CRC-16** — 16-bit Frame Check Sequence (CCITT polynomial 0x1021), computed
   on the raw data bits after bit-stuffing removal. The CRC is inverted (XOR with
   0xFFFF) before transmission.

5. **End flag (HDLC)** — 0x7E, marking the frame end.

6. **Buffer** — 24 trailing bits.

## AIS message types

The skill supports the most common message types:

- **Type 1, 2, 3**: Position Report Class A
  - Fields: MMSI, navigation status, rate of turn (ROT), speed over ground (SOG),
    position accuracy, longitude, latitude, course over ground (COG), heading,
    timestamp.

- **Type 5**: Static and Voyage Related Data (Class A)
  - Fields: MMSI, IMO number, callsign, vessel name, ship type, dimensions,
    destination port, ETA, draught.

- **Type 18**: Standard Class B Position Report
  - Similar to Type 1 but for smaller vessels (Class B).

- **Type 24**: Class B Static Data Report
  - Fields: MMSI, vessel name, ship type, dimensions (or callsign + ship type,
    depending on part).

## Payload encoding

AIS messages use several encoding schemes:

- **6-bit ASCII text**: Characters 0x40–0x5F (@ through _) map to 0–31, and
  0x20–0x3F (space through ?) map to 32–63. The skill automatically converts
  text to/from this 6-bit alphabet.

- **Unsigned integers**: Numeric fields are packed as variable-length unsigned
  integers (6, 8, 10, 12, 28 bits, etc., depending on the field).

- **Position encoding**: Longitude and latitude are encoded as 28-bit and 27-bit
  signed integers respectively, scaled by 1/600,000 degrees. Decoding: `degrees
  = value / 600,000`.

- **Speed**: Speed over ground (SOG) is encoded in 1/10 knot units as a 10-bit
  unsigned integer.

- **Course**: Course over ground (COG) is encoded in 1/10 degree units as a
  12-bit unsigned integer.

## GMSK Modulation (Audio Baseband)

- Data rate: 9600 bps
- BT product: 0.4 (Gaussian filter bandwidth-time product)
- For audio representation: GMSK-to-audio with a center frequency of 2400 Hz
- NRZI encoding: 0 bit = frequency transition, 1 bit = no change
- Bit stuffing: after five consecutive 1-bits in data, insert a 0 bit

## How to use this skill

There are three Python scripts in the `scripts/` directory next to this file.
Use them rather than writing AIS logic from scratch.

### Encoding (vessel data to AIS WAV)

```bash
python3 <skill-path>/scripts/ais_encode.py <output.wav> [options]
```

The encoder:
1. Accepts vessel data via command-line options (MMSI, position, speed, heading, etc.)
2. Builds the appropriate AIS message type (default Type 1 position report)
3. Encodes 6-bit text fields, packs numeric fields
4. Applies bit stuffing and computes CRC-16
5. Prepends start flag and appends end flag (HDLC framing)
6. Applies NRZI encoding
7. GMSK-modulates the bitstream onto audio
8. Writes a 16-bit mono WAV at 48000 Hz

Options:
- `--type N` — Message type (1, 5, 18, 24; default 1)
- `--mmsi NNNNNNNNN` — 9-digit MMSI (default 211234567)
- `--lat DD.DDDDDD` — Latitude in decimal degrees (positive = North, default 42.0)
- `--lon DD.DDDDDD` — Longitude in decimal degrees (positive = East, default -70.0)
- `--sog N.N` — Speed over ground in knots (default 10.5)
- `--cog N.N` — Course over ground in degrees 0–359.9 (default 180.0)
- `--heading N` — True heading in degrees 0–359 or 511 for not available (default 100)
- `--rot N` — Rate of turn in degrees/minute (default 0, for Type 1)
- `--name TEXT` — Vessel name up to 20 characters (for Type 5/24)
- `--callsign TEXT` — Callsign up to 7 characters (for Type 5/24)
- `--destination TEXT` — Destination port up to 20 characters (for Type 5)
- `--imo NNNNNNN` — IMO number 7 digits (for Type 5)
- `--ship-type N` — Ship and cargo type code 0–99 (for Type 5)
- `--nav-status N` — Navigation status code 0–15 (for Type 1/2/3)

### Decoding (AIS WAV to vessel data)

```bash
python3 <skill-path>/scripts/ais_decode.py <input.wav> [output.txt]
```

The decoder:
1. Reads the WAV (any sample rate — resamples to 48000 Hz if needed)
2. GMSK-demodulates by estimating instantaneous frequency
3. Applies Gaussian matched filtering and sample-at-center-bit detection
4. NRZI decodes the recovered bitstream
5. Scans for HDLC start flag (0x7E)
6. Removes bit-stuffed zeros (after five consecutive 1s)
7. Verifies CRC-16 (inverted)
8. Parses the AIS message type and extracts all fields
9. Outputs decoded vessel information in human-readable format

If output is omitted, decoded data is printed to stdout.

### Testing

```bash
python3 <skill-path>/scripts/ais_test.py [--verbose]
```

Runs the full validation suite: message type roundtrips, 6-bit ASCII encoding,
position encoding/decoding precision, bit stuffing/unstuffing, NRZI encode/decode,
CRC calculation, and full GMSK modulation/demodulation roundtrips.

### Typical workflow

**User wants to create an AIS position report WAV:**
1. Run the encoder script with vessel MMSI, position, speed, heading
2. Optionally verify by decoding the WAV back and comparing
3. Deliver the WAV file to the user

**User wants to decode an AIS recording:**
1. Run the decoder script on their WAV
2. Show them the decoded vessel information (MMSI, name, position, speed, etc.)
3. Note: real-world recordings may have noise or interference that affects
   decode quality. The decoder works best on clean signals.

**User wants a roundtrip demonstration:**
1. Encode vessel data to WAV
2. Decode WAV back to vessel data
3. Compare the original and recovered information
4. Report the match quality

**User asks about AIS format details:**
The quick reference section above covers the key parameters. The main things
people care about: AIS uses GMSK at 9600 bps on VHF, MMSI is the 9-digit vessel
identifier, position is encoded with 1/600,000 degree precision, and Type 1
position reports are the most common.

## Dependencies

The scripts use only `numpy` and the standard library `wave` module.
Install if needed:

```bash
pip install numpy --break-system-packages
```
